"""Intel Log panel — aggregate IPL news from multiple RSS feeds.

Fetches from ESPNcricinfo, CricTracker, CricketAddictor, and Reddit.
Filters to IPL-related items, detects teams, deduplicates, and persists.
"""

import json
from dataclasses import asdict
from datetime import datetime, timezone

from rich.console import Console

from pipeline.config import DATA_DIR
from pipeline.models import IntelLogItem
from pipeline.sources.feeds import FEEDS, INTEL_LOG_FEEDS, detect_teams, is_ipl_item
from pipeline.sources.rss import FeedItem, RSSFetcher

console = Console()

# Persisted log lives in data/war-room/ and is also the export artifact
LOG_PATH = DATA_DIR / "war-room" / "intel-log.json"
MAX_ITEMS = 200


def sync_intel_log() -> list[IntelLogItem]:
    """Fetch all Intel Log feeds, filter/dedup, persist, and return items."""
    # Load existing log for dedup
    existing = _load_log()
    seen_ids: set[str] = {item.id for item in existing}

    new_items: list[IntelLogItem] = []

    for feed_key in INTEL_LOG_FEEDS:
        feed_info = FEEDS[feed_key]
        fetcher = RSSFetcher(feed_info["url"])
        items = fetcher.fetch()

        for item in items:
            if item.guid in seen_ids:
                continue

            text = f"{item.title} {item.description or ''}"
            if not is_ipl_item(text):
                continue

            log_item = _feed_item_to_log_item(item, feed_key, feed_info["name"])
            new_items.append(log_item)
            seen_ids.add(log_item.id)

    if new_items:
        console.print(f"  [green]+{len(new_items)} new intel log items[/green]")
    else:
        console.print("  [dim]No new intel log items[/dim]")

    # Merge: new items first (they're newest), then existing
    merged = new_items + existing
    # Sort by published date, newest first
    merged.sort(key=_sort_key)
    # Cap
    merged = merged[:MAX_ITEMS]

    _save_log(merged)
    return merged


def _feed_item_to_log_item(
    item: FeedItem, feed_key: str, feed_name: str
) -> IntelLogItem:
    """Convert a FeedItem to an IntelLogItem."""
    text = f"{item.title} {item.description or ''}"
    teams = detect_teams(text)

    # Prefer SEO URL if available, fall back to link
    url = item.raw.get("url") or item.link or ""

    # Published as ISO 8601
    published = ""
    if item.published:
        pub = item.published
        if not pub.tzinfo:
            pub = pub.replace(tzinfo=timezone.utc)
        published = pub.isoformat()

    # Image URL
    image_url = item.raw.get("coverImages") or item.raw.get("thumbnail")

    # Author
    author = item.raw.get("creator") or item.raw.get("dc:creator")

    return IntelLogItem(
        id=item.guid,
        title=item.title,
        snippet=item.description,
        source=feed_key,
        source_name=feed_name,
        url=url,
        published=published,
        teams=teams,
        image_url=image_url,
        author=author,
        categories=item.categories,
    )


def _sort_key(item: IntelLogItem) -> float:
    """Sort key: newest first, undated at the end."""
    if item.published:
        try:
            dt = datetime.fromisoformat(item.published)
            return -dt.timestamp()
        except ValueError:
            pass
    return float("inf")


def _load_log() -> list[IntelLogItem]:
    """Load persisted log from disk."""
    if not LOG_PATH.exists():
        return []
    try:
        data = json.loads(LOG_PATH.read_text(encoding="utf-8"))
        return [IntelLogItem(**item) for item in data]
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        console.print(f"[yellow]Intel log: corrupt file, starting fresh: {exc}[/yellow]")
        return []


def _save_log(items: list[IntelLogItem]) -> None:
    """Persist log to disk."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = [asdict(item) for item in items]
    LOG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
