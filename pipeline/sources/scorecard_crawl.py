"""Scorecard crawl — extract playing XI from ESPNcricinfo scorecards.

Fills the gap between Cricsheet (canonical but lags 1-6 days) and the
current match day. Crawls scorecard pages for completed matches that
Cricsheet doesn't have yet, extracts player names from batting/bowling
tables, and caches permanently (scorecards are immutable).

Usage:
    appearances = crawl_missing_scorecards("2026", conn)
    # → {"Axar Patel": 3, "Mitchell Starc": 0, ...}
"""

import asyncio
import concurrent.futures
import json
import re

from rich.console import Console

from pipeline.cache.manager import CacheManager
from pipeline.config import DATA_DIR, ROOT_DIR

console = Console()

# Matches player links in scorecard tables: [Name](cricketers/url)
_PLAYER_LINK_RE = re.compile(
    r"\[([^\]]+?)\s*\]\(https?://www\.espncricinfo\.com/cricketers/"
)

_cache = CacheManager()

# Per-sync result cache keyed by season. Populated on first call to
# crawl_missing_scorecards; subsequent callers in the same sync get the
# cached dict without re-querying Cricsheet or re-logging. Reset by
# reset_crawl_cache() at the start of each sync (called from sync.py).
_result_cache: dict[str, dict[str, int]] = {}


def reset_crawl_cache() -> None:
    """Drop the in-process result cache. Call once at the start of each sync."""
    _result_cache.clear()


def _clean_name(raw: str) -> str:
    """Strip captain/keeper markers and punctuation from player name."""
    name = raw.replace("†", "").strip().rstrip(",")
    name = re.sub(r"\s*\(c\)\s*", " ", name).strip()
    return name


def parse_scorecard_players(md: str) -> list[str]:
    """Extract unique player names from a scorecard markdown page."""
    names: set[str] = set()
    in_scorecard = False

    for line in md.splitlines():
        # Start of scorecard zone (innings header)
        if re.search(r"\d+ ovs? maximum\)|T:\s*\d+", line):
            in_scorecard = True
        # End of scorecard zone (match details section)
        if line.startswith("Match Flow") or line.startswith("Match Details"):
            in_scorecard = False

        if not in_scorecard:
            continue

        # Extract from table rows and "Did not bat" lines
        if not line.startswith("|"):
            continue

        for raw in _PLAYER_LINK_RE.findall(line):
            name = _clean_name(raw)
            if name and name not in ("Extras", "Total"):
                names.add(name)

    return sorted(names)


async def _crawl_single(match_url: str) -> str | None:
    """Crawl a scorecard page and return markdown."""
    try:
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

        async with AsyncWebCrawler(verbose=False) as crawler:
            result = await crawler.arun(
                url=match_url,
                config=CrawlerRunConfig(),
            )
            md = result.markdown
            if hasattr(md, "raw_markdown"):
                md = md.raw_markdown
            return md if md else None
    except Exception as e:
        console.print(f"  [yellow]Scorecard crawl error: {e}[/yellow]")
        return None


def _run_async(coro: object) -> object:
    """Run a coroutine from synchronous code, even inside a running event loop.

    asyncio.run() raises RuntimeError when a loop is already running (e.g. when
    called from an async function via a sync helper). In that case we spin up a
    fresh thread — which has no event loop — and run the coroutine there instead.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    return asyncio.run(coro)


def _crawl_and_parse(match_url: str, match_number: int) -> list[str] | None:
    """Crawl a scorecard and extract player names, with caching."""
    cache_key = f"m{match_number}"

    # Check cache first
    cached = _cache.read_json("crawl", "scorecard", cache_key)
    if cached is not None:
        return cached.get("players", [])

    # Crawl — use _run_async so this works whether called from sync or async code
    md = _run_async(_crawl_single(match_url))
    if not md:
        return None

    players = parse_scorecard_players(md)
    if not players:
        return None

    # Cache permanently (scorecards are immutable)
    _cache.write_json("crawl", "scorecard", cache_key, {"players": players})
    console.print(f"  [green]M{match_number}: {len(players)} players[/green]")
    return players


def crawl_missing_scorecards(
    season: str,
    conn: object,
) -> dict[str, int]:
    """Crawl scorecards for completed matches not yet in Cricsheet.

    Returns {player_name: appearance_count} from crawled data only.
    Matches already in Cricsheet are skipped — Cricsheet is canonical.

    Result is cached for the lifetime of the sync (reset_crawl_cache() at
    sync start) so repeated callers (roster, availability, briefing, dossier,
    narratives) share one crawl instead of logging and querying nine times.
    """
    if season in _result_cache:
        return _result_cache[season]

    # Load schedule
    for path in (
        DATA_DIR / "war-room" / "schedule.json",
        ROOT_DIR / "frontend" / "public" / "api" / "ipl" / "war-room" / "schedule.json",
    ):
        if path.exists():
            break
    else:
        _result_cache[season] = {}
        return {}

    schedule = json.loads(path.read_text(encoding="utf-8"))

    # Get matches Cricsheet already has
    cricsheet_dates: set[tuple] = set()
    try:
        from pipeline.sources.cricsheet import query_completed_matches

        for key in query_completed_matches(season):
            cricsheet_dates.add(key)  # (date, sorted_team1, sorted_team2)
    except Exception:
        pass

    # Find completed matches with URLs that Cricsheet doesn't have
    to_crawl: list[dict] = []
    for m in schedule:
        if m.get("status") != "completed" or not m.get("match_url"):
            continue
        key = (m["date"], *sorted([m["team1"], m["team2"]]))
        if key not in cricsheet_dates:
            to_crawl.append(m)

    if not to_crawl:
        _result_cache[season] = {}
        return {}

    console.print(
        f"  [dim]Scorecard crawl: {len(to_crawl)} match(es)"
        f" not in Cricsheet[/dim]"
    )

    # Crawl and aggregate appearances
    counts: dict[str, int] = {}
    for m in to_crawl:
        players = _crawl_and_parse(m["match_url"], m["match_number"])
        if players:
            for name in players:
                counts[name] = counts.get(name, 0) + 1

    _result_cache[season] = counts
    return counts
