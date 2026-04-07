"""War Room article store — ingest RSS feeds into DuckDB, query for LLM.

Provides:
  - ingest_feed_items(): RSS FeedItems → war_room_articles table (dedup by guid)
  - crawl_missing_bodies(): fetch full article text for sources without RSS body
  - retrieve_for_match(): query articles about a team pair for score extraction
  - retrieve_for_team(): query articles about a team for narratives/dossiers

The articles table is the shared RAG store for all LLM intelligence features.
Feed ingestion is decoupled from LLM consumption — ingest on every sync,
LLM queries only when output is stale.
"""

import asyncio
import hashlib
import re
import time
from datetime import datetime, timezone

import duckdb
from rich.console import Console

from pipeline.sources.feeds import detect_teams, is_ipl_item
from pipeline.sources.rss import FeedItem

console = Console()

_HTML_TAG_RE = re.compile(r"<[^>]+>")

# Sources that need crawling (RSS has no body text)
_CRAWLABLE_SOURCES = ("espncricinfo",)


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    clean = _HTML_TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", clean).strip()


def _content_hash(title: str, body: str | None) -> str:
    """Deterministic hash for cross-feed dedup."""
    content = f"{title}\n{body or ''}"
    return hashlib.sha256(content.encode()).hexdigest()[:24]


def ingest_feed_items(
    conn: duckdb.DuckDBPyConnection,
    items: list[FeedItem],
    source: str,
) -> int:
    """Ingest RSS feed items into the articles table.

    Uses INSERT OR IGNORE — safe to call on every sync. Only new
    articles (by guid) are inserted. Returns count of new rows.
    """
    if not items:
        return 0

    count = 0
    for item in items:
        if not item.guid:
            continue

        # Check if already ingested
        exists = conn.execute(
            "SELECT 1 FROM war_room_articles WHERE guid = ?",
            [item.guid],
        ).fetchone()
        if exists:
            continue

        # Extract text content
        encoded = item.raw.get("encoded", "")
        body = _strip_html(encoded) if encoded else None
        snippet = item.description

        # Detect teams from title + snippet (not body — body has
        # "Also Read" cross-links that cause false team tagging)
        primary_text = f"{item.title} {snippet or ''}"
        teams = detect_teams(primary_text)
        ipl = is_ipl_item(primary_text)

        # Published timestamp
        published = item.published
        if published and not published.tzinfo:
            published = published.replace(tzinfo=timezone.utc)

        chash = _content_hash(item.title, body)

        conn.execute(
            """
            INSERT OR IGNORE INTO war_room_articles
            (guid, source, title, snippet, body, teams, is_ipl,
             published, ingested_at, content_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                item.guid,
                source,
                item.title,
                snippet,
                body,
                teams,
                ipl,
                published,
                datetime.now(timezone.utc),
                chash,
            ],
        )
        count += 1

    return count


def ingest_all_feeds(
    conn: duckdb.DuckDBPyConnection,
    feed_items: dict[str, list[FeedItem]],
) -> int:
    """Ingest items from multiple feeds. Returns total new articles."""
    total = 0
    for source, items in feed_items.items():
        n = ingest_feed_items(conn, items, source)
        total += n
    if total:
        console.print(
            f"  [green]Articles: {total} new article(s) ingested[/green]"
        )
    else:
        console.print("  [dim]Articles: no new articles[/dim]")
    return total


def _clean_crawled_markdown(md: str) -> str:
    """Clean crawl4ai markdown output — strip noise, normalize whitespace."""
    lines = []
    for line in md.split("\n"):
        stripped = line.strip()
        # Skip noise: lazy images, share buttons, empty markdown artifacts
        if not stripped:
            continue
        if "lazyimage" in stripped.lower():
            continue
        if stripped in ("__", "___", "----"):
            continue
        if stripped.startswith("![") and "svg" in stripped:
            continue
        lines.append(line)
    text = "\n".join(lines)
    # Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def _crawl_single(crawler: object, url: str) -> str | None:
    """Crawl a single URL and return cleaned body text.

    Uses crawl4ai with css_selector="article" to extract just the
    article content. Returns raw_markdown (plain markdown without
    citation markers) — ideal for LLM consumption.
    """
    try:
        from crawl4ai import CrawlerRunConfig
        result = await crawler.arun(  # type: ignore[union-attr]
            url=url,
            config=CrawlerRunConfig(css_selector="article"),
        )
        md_result = result.markdown  # type: ignore[union-attr]
        # Prefer raw_markdown (clean, no citation markers)
        raw = (
            md_result.raw_markdown
            if hasattr(md_result, "raw_markdown")
            else str(md_result)
        ) or ""
        if len(raw) < 100:
            return None
        return _clean_crawled_markdown(raw)
    except Exception as e:
        console.print(f"    [yellow]Crawl failed: {url[:50]}… — {e}[/yellow]")
        return None


def crawl_missing_bodies(
    conn: duckdb.DuckDBPyConnection,
    *,
    rate_limit: float = 1.0,
    max_crawl: int = 20,
) -> int:
    """Crawl full article text for sources that lack RSS body content.

    Only processes articles where body IS NULL and source is in
    _CRAWLABLE_SOURCES. Skips already-crawled articles (body != NULL).
    Rate-limited to respect source servers.

    Returns count of articles successfully crawled.
    """
    placeholders = ", ".join(f"'{s}'" for s in _CRAWLABLE_SOURCES)
    rows = conn.execute(
        f"""
        SELECT guid, title
        FROM war_room_articles
        WHERE source IN ({placeholders})
          AND body IS NULL
          AND is_ipl = TRUE
        ORDER BY published DESC
        LIMIT {max_crawl}
        """,
    ).fetchall()

    if not rows:
        console.print("  [dim]Crawl: no articles need crawling[/dim]")
        return 0

    console.print(
        f"  Crawl: {len(rows)} article(s) to fetch"
    )

    async def _crawl_batch() -> int:
        try:
            from crawl4ai import AsyncWebCrawler
        except ImportError:
            console.print(
                "  [yellow]Crawl: crawl4ai not installed — skipping"
                " (install with: uv add crawl4ai)[/yellow]"
            )
            return 0

        count = 0
        async with AsyncWebCrawler() as crawler:
            for i, (guid, title) in enumerate(rows):
                if i > 0:
                    time.sleep(rate_limit)

                body = await _crawl_single(crawler, guid)
                if not body:
                    continue

                # Update body + rehash content
                chash = _content_hash(title, body)
                conn.execute(
                    """
                    UPDATE war_room_articles
                    SET body = ?, content_hash = ?
                    WHERE guid = ?
                    """,
                    [body, chash, guid],
                )
                count += 1
                console.print(
                    f"    [green]✓[/green] {title[:55]}… "
                    f"({len(body):,} chars)"
                )

        return count

    crawled = asyncio.run(_crawl_batch())
    if crawled:
        console.print(
            f"  [green]Crawl: {crawled}/{len(rows)} articles enriched[/green]"
        )
    return crawled


def retrieve_for_match(
    conn: duckdb.DuckDBPyConnection,
    team1: str,
    team2: str,
    match_date: str,
    *,
    max_articles: int = 5,
    max_chars_per_article: int = 2000,
) -> str:
    """Retrieve article text about a match for LLM extraction.

    Finds IPL articles mentioning both teams, published around the match
    date, ranked by body length (longer = more likely a match report).
    Returns concatenated text, truncated per article to control token count.
    """
    # Primary: articles mentioning BOTH teams
    rows = conn.execute(
        """
        SELECT title, snippet, body, content_hash
        FROM war_room_articles
        WHERE is_ipl = TRUE
          AND list_contains(teams, $1)
          AND list_contains(teams, $2)
          AND published >= (CAST($3 AS DATE) - INTERVAL '1 day')
          AND published <= (CAST($3 AS DATE) + INTERVAL '2 days')
        ORDER BY length(coalesce(body, '')) DESC
        LIMIT $4
        """,
        [team1, team2, match_date, max_articles * 2],
    ).fetchall()

    # Fallback: articles mentioning either team (if few BOTH results)
    if len(rows) < 2:
        extra = conn.execute(
            """
            SELECT title, snippet, body, content_hash
            FROM war_room_articles
            WHERE is_ipl = TRUE
              AND (list_contains(teams, $1)
                   OR list_contains(teams, $2))
              AND published >= (CAST($3 AS DATE) - INTERVAL '1 day')
              AND published <= (CAST($3 AS DATE) + INTERVAL '2 days')
            ORDER BY length(coalesce(body, '')) DESC
            LIMIT $4
            """,
            [team1, team2, match_date, max_articles * 2],
        ).fetchall()
        rows = list(rows) + list(extra)

    if not rows:
        return ""

    # Deduplicate by content_hash
    seen_hashes: set[str] = set()
    selected: list[tuple[str, str | None, str | None]] = []
    for title, snippet, body, chash in rows:
        if chash and chash in seen_hashes:
            continue
        if chash:
            seen_hashes.add(chash)
        selected.append((title, snippet, body))
        if len(selected) >= max_articles:
            break

    # Build combined context
    parts: list[str] = []
    for title, snippet, body in selected:
        text = body or snippet or title
        if len(text) > max_chars_per_article:
            text = text[:max_chars_per_article] + "..."
        parts.append(f"[{title}]\n{text}")

    return "\n\n---\n\n".join(parts)


def retrieve_for_team(
    conn: duckdb.DuckDBPyConnection,
    team: str,
    *,
    since_date: str | None = None,
    max_articles: int = 10,
    max_chars_per_article: int = 1000,
) -> str:
    """Retrieve article text about a team for narratives/dossiers.

    Returns concatenated text from recent IPL articles mentioning the team.
    """
    where = [
        "is_ipl = TRUE",
        "list_contains(teams, $1)",
    ]
    params: list = [team]

    if since_date:
        where.append(f"published >= CAST(${len(params) + 1} AS DATE)")
        params.append(since_date)

    params.append(max_articles * 2)
    limit_param = f"${len(params)}"

    rows = conn.execute(
        f"""
        SELECT title, snippet, body, content_hash
        FROM war_room_articles
        WHERE {' AND '.join(where)}
        ORDER BY published DESC
        LIMIT {limit_param}
        """,
        params,
    ).fetchall()

    if not rows:
        return ""

    # Deduplicate by content_hash
    seen: set[str] = set()
    selected: list[tuple[str, str | None, str | None]] = []
    for title, snippet, body, chash in rows:
        if chash and chash in seen:
            continue
        if chash:
            seen.add(chash)
        selected.append((title, snippet, body))
        if len(selected) >= max_articles:
            break

    parts: list[str] = []
    for title, snippet, body in selected:
        text = body or snippet or title
        if len(text) > max_chars_per_article:
            text = text[:max_chars_per_article] + "..."
        parts.append(f"[{title}]\n{text}")

    return "\n\n---\n\n".join(parts)


def article_count(conn: duckdb.DuckDBPyConnection) -> int:
    """Total articles in the store."""
    row = conn.execute(
        "SELECT COUNT(*) FROM war_room_articles"
    ).fetchone()
    return row[0] if row else 0
