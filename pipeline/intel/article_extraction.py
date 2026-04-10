"""Per-article structured extraction via LLM.

The foundational extraction layer: one LLM call per unprocessed article,
producing a structured payload (relevance, story type, summary, takeaway,
mentioned players, availability events, match result claim, key quotes).

Cached at the article level — once extracted at the current
EXTRACTION_VERSION, an article is never re-processed unless the version
bumps or someone passes force=True.

Two write targets per extraction:
  - war_room_article_extractions (one row per article_guid + version)
  - war_room_player_availability_events (one row per availability event)

Steady-state usage:
    stats = await run_extraction(conn, season, max_articles=30)

Backlog migration (one-shot, no cap):
    stats = await run_migration(conn, season)
"""

import json
import re
from dataclasses import dataclass
from typing import Any

import duckdb
from rich.console import Console

from pipeline.intel.schemas import ArticleExtraction
from pipeline.llm.cache import LLMCache

console = Console()

EXTRACTION_VERSION = 1
_CACHE_TASK = "war_room_article_extraction"

# Articles older than this are skipped (covers full season + run-up)
_LOOKBACK_DAYS = 120

# Body must be at least this many chars to be worth extracting
_MIN_BODY_LEN = 200

# Max chars sent to the LLM per article (prevents giant payloads)
_MAX_BODY_CHARS = 4000

# Allowed story_type values; anything else is normalized to "other"
_STORY_TYPES = {
    "match_preview", "match_report", "injury_update", "team_news",
    "transfer_auction", "interview", "opinion", "controversy", "other",
}

# Allowed availability status values
_STATUSES = {"out", "doubtful", "available"}


@dataclass
class _ArticleRow:
    guid: str
    source: str
    title: str
    snippet: str | None
    body: str | None
    teams: list[str]
    published: Any  # datetime or None


_SYSTEM_PROMPT = """\
You are an IPL article analyst. Given one cricket article, extract structured \
information about its content.

Extract these fields:

- is_relevant: false if the article is not actually about IPL, is pure \
syndication noise, or contains no extractable signal.
- story_type: one of match_preview, match_report, injury_update, team_news, \
transfer_auction, interview, opinion, controversy, other.
- summary: 2-3 factual sentences. Neutral tone. Capture the most important \
facts a downstream reader would need.
- headline_takeaway: one-line "so what" — the single most important point \
in <=15 words.
- mentioned_players: list of player names mentioned. Match the spelling in \
the squad whitelist when possible.
- availability_events: explicit statements about a player being injured, \
ruled out, rested, dropped, doubtful, or returning. ONLY for players in the \
squad whitelist. Do NOT infer from poor performance or speculation.
  - status 'out': ruled out, injured, suspended, withdrawn
  - status 'doubtful': fitness test pending, race against time, may miss
  - status 'available': returned to training, cleared, fit again
- match_result_claim: if the article is a match report, populate scores, \
winner, margin, POTM. Use empty strings for missing fields. If not a match \
report, return all empty strings.
- key_quotes: short verbatim quotes from players or coaches with attribution. \
Skip generic platitudes — only extract substantive quotes.

Return empty lists / empty strings / false where appropriate. Do not invent."""


_USER_PROMPT = """\
SQUAD WHITELIST (only extract availability events for these players):
{squad_whitelist}

ARTICLE (source: {source}, published: {published}):
Title: {title}

{body}

Extract structured data as JSON."""


# ── Article selection ───────────────────────────────────────────────

def _unprocessed_articles(
    conn: duckdb.DuckDBPyConnection,
    limit: int | None,
    *,
    force: bool = False,
) -> list[_ArticleRow]:
    """Select articles not yet extracted at the current version.

    When force=True, returns ALL articles in the lookback window
    (the caller is expected to delete existing extraction rows first
    or otherwise handle re-processing).
    """
    if force:
        sql = f"""
            SELECT guid, source, title, snippet, body, teams, published
            FROM war_room_articles
            WHERE is_ipl = TRUE
              AND published >= CURRENT_DATE - INTERVAL '{_LOOKBACK_DAYS} days'
              AND coalesce(length(body), length(snippet), 0) > {_MIN_BODY_LEN}
            ORDER BY published DESC NULLS LAST
        """
        params: list = []
    else:
        sql = f"""
            SELECT a.guid, a.source, a.title, a.snippet, a.body, a.teams, a.published
            FROM war_room_articles a
            LEFT JOIN war_room_article_extractions e
              ON e.article_guid = a.guid AND e.extraction_version = ?
            WHERE a.is_ipl = TRUE
              AND e.article_guid IS NULL
              AND a.published >= CURRENT_DATE - INTERVAL '{_LOOKBACK_DAYS} days'
              AND coalesce(length(a.body), length(a.snippet), 0) > {_MIN_BODY_LEN}
            ORDER BY a.published DESC NULLS LAST
        """
        params = [EXTRACTION_VERSION]

    if limit is not None:
        sql += f" LIMIT {int(limit)}"

    try:
        rows = conn.execute(sql, params).fetchall()
    except Exception as e:
        console.print(f"  [yellow]Article selection failed: {e}[/yellow]")
        return []

    return [
        _ArticleRow(
            guid=r[0], source=r[1], title=r[2], snippet=r[3],
            body=r[4], teams=list(r[5] or []), published=r[6],
        )
        for r in rows
    ]


# ── Squad whitelist (LLM grounding) ─────────────────────────────────

def _build_squad_whitelist(
    conn: duckdb.DuckDBPyConnection,
    season: str,
) -> str:
    """Comma-joined 'Player (TEAM)' list for the LLM grounding prompt."""
    from pipeline.intel.roster_context import _query_squad
    from pipeline.ipl.franchise_metadata import IPL_FRANCHISES

    short_map = {
        fid: d["short_name"]
        for fid, d in IPL_FRANCHISES.items()
        if not d.get("defunct")
    }

    rows = _query_squad(conn, season)
    if not rows:
        return "(no squad data available)"

    # rows: (franchise_id, player_name, is_captain, is_overseas, price_inr, acquisition_type)
    parts = []
    for fid, name, _is_cap, _is_ovs, _price, _acq in rows:
        short = short_map.get(fid, fid.upper())
        parts.append(f"{name} ({short})")
    return ", ".join(parts)


# ── LLM call ────────────────────────────────────────────────────────

async def _extract_one(
    article: _ArticleRow,
    squad_whitelist: str,
    cache: LLMCache,
) -> dict[str, Any] | None:
    """Single-article LLM call. Cached by article_guid."""
    from pipeline.llm.gemini import GeminiProvider

    # Cache key = article_guid + extraction_version
    cache_key = f"v{EXTRACTION_VERSION}_{article.guid}"
    cached = cache.get(_CACHE_TASK, cache_key)
    if cached and cached.get("parsed"):
        return cached["parsed"]

    # Build the prompt
    body = (article.body or article.snippet or "").strip()
    if len(body) > _MAX_BODY_CHARS:
        body = body[:_MAX_BODY_CHARS] + "..."

    published_str = ""
    if article.published is not None:
        try:
            published_str = article.published.strftime("%Y-%m-%d")
        except Exception:
            published_str = str(article.published)

    prompt = _USER_PROMPT.format(
        squad_whitelist=squad_whitelist,
        source=article.source,
        published=published_str,
        title=article.title,
        body=body,
    )

    provider = GeminiProvider()
    result = await provider.generate(
        prompt,
        system=_SYSTEM_PROMPT,
        temperature=0.1,
        response_schema=ArticleExtraction,
    )

    parsed = result.get("parsed")
    if not parsed:
        # Fall back to manual JSON parsing
        text = (result.get("text") or "").strip()
        if text.startswith("```"):
            text = re.sub(r"```(?:json)?\n?", "", text).strip().rstrip("`")
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                try:
                    parsed = json.loads(m.group())
                except (json.JSONDecodeError, ValueError):
                    parsed = None

    if not parsed:
        return None

    cache.put(_CACHE_TASK, cache_key, {
        "parsed": parsed,
        "usage": result.get("usage", {}),
    })
    return parsed


# ── Persistence ─────────────────────────────────────────────────────

def _normalize_story_type(raw: str) -> str:
    s = (raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    return s if s in _STORY_TYPES else "other"


def _resolve_event_name(
    raw_name: str,
    by_surname: dict[str, list[str]],
) -> str | None:
    """Resolve a raw player name to a squad name. Returns None if unresolvable."""
    from pipeline.intel.roster_context import _resolve_to_squad_name
    if not raw_name or not raw_name.strip():
        return None
    resolved = _resolve_to_squad_name(raw_name.strip(), by_surname)
    # _resolve_to_squad_name returns the raw name on failure — we treat
    # any name not present in the squad index as unresolvable.
    flat_squad_names = {n for names in by_surname.values() for n in names}
    if resolved in flat_squad_names:
        return resolved
    return None


def _resolve_franchise(
    franchise_hint: str,
    article_teams: list[str],
) -> str | None:
    """Resolve a franchise hint (or fall back to article team tag)."""
    from pipeline.sources.feeds import detect_teams
    if franchise_hint:
        teams = detect_teams(franchise_hint)
        if teams:
            return teams[0]
    if len(article_teams) == 1:
        return article_teams[0]
    return None


def _persist_extraction(
    conn: duckdb.DuckDBPyConnection,
    season: str,
    article: _ArticleRow,
    payload: dict[str, Any],
    by_surname: dict[str, list[str]],
) -> tuple[int, bool]:
    """Write extraction row + zero-or-more availability event rows.

    Returns (events_written, was_relevant).
    """
    is_relevant = bool(payload.get("is_relevant"))
    story_type = _normalize_story_type(payload.get("story_type", ""))
    summary = (payload.get("summary") or "").strip()
    takeaway = (payload.get("headline_takeaway") or "").strip()

    # Resolve mentioned players to squad names
    raw_players = payload.get("mentioned_players") or []
    resolved_players = []
    for raw in raw_players:
        n = _resolve_event_name(str(raw), by_surname)
        if n and n not in resolved_players:
            resolved_players.append(n)

    match_claim = payload.get("match_result_claim") or {}
    key_quotes = payload.get("key_quotes") or []

    # Upsert into war_room_article_extractions
    conn.execute(
        """
        DELETE FROM war_room_article_extractions
        WHERE article_guid = ? AND extraction_version = ?
        """,
        [article.guid, EXTRACTION_VERSION],
    )
    conn.execute(
        """
        INSERT INTO war_room_article_extractions
            (article_guid, extraction_version, season, is_relevant,
             story_type, summary, headline_takeaway, mentioned_players,
             match_result_claim, key_quotes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            article.guid,
            EXTRACTION_VERSION,
            season,
            is_relevant,
            story_type,
            summary,
            takeaway,
            resolved_players,
            json.dumps(match_claim),
            json.dumps(key_quotes),
        ],
    )

    if not is_relevant:
        return 0, False

    # Write availability events
    events = payload.get("availability_events") or []
    written = 0
    for ev in events:
        raw_name = (ev.get("player_name") or "").strip()
        player = _resolve_event_name(raw_name, by_surname)
        if not player:
            continue

        status = (ev.get("status") or "").strip().lower()
        if status not in _STATUSES:
            continue

        franchise_id = _resolve_franchise(
            ev.get("franchise_hint") or "",
            article.teams,
        )
        if not franchise_id:
            continue

        # Manual ID assignment (matches war_room_wire convention)
        next_id = conn.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM war_room_player_availability_events"
        ).fetchone()[0]

        conn.execute(
            """
            INSERT INTO war_room_player_availability_events
                (id, season, player_name, franchise_id, status, reason,
                 expected_return, article_guid, article_published,
                 source, confidence, quote)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                next_id,
                season,
                player,
                franchise_id,
                status,
                (ev.get("reason") or "").strip() or None,
                (ev.get("expected_return") or "").strip() or None,
                article.guid,
                article.published,
                article.source,
                (ev.get("confidence") or "").strip().lower() or None,
                (ev.get("quote") or "").strip()[:500] or None,
            ],
        )
        written += 1

    return written, True


def _persist_failure(
    conn: duckdb.DuckDBPyConnection,
    season: str,
    article: _ArticleRow,
) -> None:
    """Write a sentinel row so the failed article isn't retried forever."""
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO war_room_article_extractions
                (article_guid, extraction_version, season, is_relevant,
                 story_type, summary, headline_takeaway, mentioned_players,
                 match_result_claim, key_quotes)
            VALUES (?, ?, ?, NULL, NULL, NULL, NULL, [], NULL, NULL)
            """,
            [article.guid, EXTRACTION_VERSION, season],
        )
    except Exception:
        pass


# ── Public entry points ─────────────────────────────────────────────

async def run_extraction(
    conn: duckdb.DuckDBPyConnection,
    season: str,
    *,
    max_articles: int | None = 30,
    force: bool = False,
) -> dict[str, int]:
    """Run extraction on up to max_articles unprocessed articles.

    Returns stats: {processed, events, summaries, errors, skipped}.
    """
    if force:
        # Clear existing extraction rows so they get re-processed
        conn.execute(
            "DELETE FROM war_room_article_extractions WHERE extraction_version = ?",
            [EXTRACTION_VERSION],
        )

    articles = _unprocessed_articles(conn, max_articles, force=force)
    if not articles:
        console.print("  [dim]Article extraction: no unprocessed articles[/dim]")
        return {"processed": 0, "events": 0, "summaries": 0, "errors": 0, "skipped": 0}

    console.print(
        f"  [dim]Article extraction: processing {len(articles)} article(s)"
        f" (version {EXTRACTION_VERSION})[/dim]"
    )

    cache = LLMCache()
    squad_whitelist = _build_squad_whitelist(conn, season)

    # Build name index once
    from pipeline.intel.roster_context import _build_squad_name_index
    by_surname = _build_squad_name_index(conn, season)

    stats = {"processed": 0, "events": 0, "summaries": 0, "errors": 0, "skipped": 0}

    for article in articles:
        try:
            payload = await _extract_one(article, squad_whitelist, cache)
        except Exception as e:
            console.print(
                f"    [yellow]Extract failed for {article.guid[:30]}: {e}[/yellow]"
            )
            _persist_failure(conn, season, article)
            stats["errors"] += 1
            continue

        if not payload:
            _persist_failure(conn, season, article)
            stats["errors"] += 1
            continue

        try:
            events_written, was_relevant = _persist_extraction(
                conn, season, article, payload, by_surname,
            )
        except Exception as e:
            console.print(
                f"    [yellow]Persist failed for {article.guid[:30]}: {e}[/yellow]"
            )
            stats["errors"] += 1
            continue

        stats["processed"] += 1
        stats["events"] += events_written
        if was_relevant:
            stats["summaries"] += 1
        else:
            stats["skipped"] += 1

    console.print(
        f"  [green]Article extraction: processed={stats['processed']}"
        f" events={stats['events']} summaries={stats['summaries']}"
        f" skipped={stats['skipped']} errors={stats['errors']}[/green]"
    )
    return stats


async def run_migration(
    conn: duckdb.DuckDBPyConnection,
    season: str,
    *,
    force: bool = False,
) -> dict[str, int]:
    """One-shot extraction of every unprocessed article (no cap).

    When force=True, also re-processes articles already extracted at the
    current version.
    """
    return await run_extraction(conn, season, max_articles=None, force=force)
