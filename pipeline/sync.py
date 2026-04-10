"""Sync orchestrator — tier-based panel dispatch.

Usage (via __main__.py):
    uv run python -m pipeline sync                     # all tiers
    uv run python -m pipeline sync --tiers hot,warm    # specific tiers
    uv run python -m pipeline sync --panel standings   # single panel
    uv run python -m pipeline sync --watch             # continuous (5 min)
"""

import importlib
import json
from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel as RichPanel

from pipeline.clock import today_ist_iso
from pipeline.config import DATA_DIR, ROOT_DIR
from pipeline.context import SyncContext
from pipeline.panels import PANEL_ORDER, resolve_panels
from pipeline.sources.rss import RSSFetcher
from pipeline.writer import write_json

console = Console()

WAR_ROOM_DATA = DATA_DIR / "war-room"
PUBLIC_API_DIR = ROOT_DIR / "frontend" / "public" / "api" / "ipl" / "war-room"


def sync_tiers(
    tiers: list[str],
    *,
    season: str = "2026",
    panel: str | None = None,
    force: bool = False,
) -> None:
    """Run sync for the given tiers (or a single panel)."""
    # Resolve which panels to run
    if panel:
        active_panels = {panel}
    else:
        active_panels = resolve_panels(tiers)

    # Determine ordered execution list
    ordered = [p for p in PANEL_ORDER if p in active_panels]

    console.print(RichPanel(
        f"[dim]Season {season} · Panels: {', '.join(ordered)}[/dim]",
        title="[bold]Dugout Sync[/bold]",
        border_style="bright_black",
    ))

    # Build sync context
    ctx = SyncContext(
        season=season,
        data_dir=WAR_ROOM_DATA,
        public_dir=PUBLIC_API_DIR,
    )

    # Fetch shared feeds if any panel that reads articles is active.
    # intel_log + wire are in this set so hot-only runs also ingest
    # fresh articles and run per-article extraction before the wire
    # panel queries war_room_article_extractions.
    needs_feeds = active_panels & {
        "intel_log", "wire",
        "standings", "caps", "pulse", "schedule",
        "scenarios", "records", "briefing", "narratives", "dossier",
        "availability",
    }
    if needs_feeds:
        _fetch_feeds(ctx)
        _init_db_and_articles(ctx)

    # Seed squad rosters (skips if already populated)
    if ctx.db_conn is not None:
        try:
            from pipeline.sources.wikipedia import sync_squads
            sync_squads(season, ctx.db_conn, force=force)
        except Exception as e:
            console.print(f"  [yellow]Squads: {e}[/yellow]")

    # If standings weren't synced but downstream panels need them, load from disk
    def _ensure_standings():
        if ctx.standings_rows is None:
            path = WAR_ROOM_DATA / "standings.json"
            if path.exists():
                ctx.standings_rows = json.loads(path.read_text(encoding="utf-8"))

    # If schedule wasn't synced but downstream panels need today's matches, load
    def _ensure_today_matches():
        if not ctx.today_matches:
            sched_path = PUBLIC_API_DIR / "schedule.json"
            if sched_path.exists():
                from pipeline.models import ScheduleMatch

                today_str = today_ist_iso()
                for m in json.loads(sched_path.read_text(encoding="utf-8")):
                    if m.get("date") == today_str:
                        ctx.today_matches.append(
                            ScheduleMatch.from_schedule_dict(m)
                        )

    # Execute panels in order
    for panel_name in ordered:
        console.print(f"\n[bold]{panel_name.replace('_', ' ').title()}[/bold]")

        # Pre-conditions: ensure upstream data is available
        if panel_name in ("schedule", "pulse"):
            _ensure_standings()
        if panel_name in (
            "ticker", "wire", "briefing", "dossier",
            "scenarios", "records", "narratives",
        ):
            _ensure_today_matches()

        mod = importlib.import_module(f"pipeline.panels.{panel_name}")
        if panel_name == "wire":
            mod.sync(ctx, force=force)
        else:
            mod.sync(ctx)

    # Write meta
    meta_data = {
        "season": season,
        "last_sync": datetime.now(timezone.utc).isoformat(),
        "panels": ctx.meta,
    }
    write_json(WAR_ROOM_DATA / "meta.json", meta_data)
    write_json(PUBLIC_API_DIR / "meta.json", meta_data)

    console.print(f"\n[bold green]Sync complete.[/bold green] Output: {PUBLIC_API_DIR}")


def _fetch_feeds(ctx: SyncContext) -> None:
    """Fetch shared RSS feeds."""
    from pipeline.sources.feeds import FEEDS

    for name, key in [
        ("Wisden", "wisden"),
        ("CricketAddictor", "cricketaddictor"),
        ("CricTracker", "crictracker"),
        ("ESPNcricinfo", "espncricinfo"),
    ]:
        console.print(f"[bold]Fetching {name} feed...[/bold]")
        fetcher = RSSFetcher(FEEDS[key]["url"])
        items = fetcher.fetch()
        console.print(f"  [dim]{len(items)} items[/dim]")

        if key == "wisden":
            ctx.wisden_items = items
        elif key == "cricketaddictor":
            ctx.ca_items = items
        elif key == "crictracker":
            ctx.ct_items = items
        elif key == "espncricinfo":
            ctx.espn_items = items


def _init_db_and_articles(ctx: SyncContext) -> None:
    """Initialize DB, ingest article feeds, and extract structured data.

    Extraction runs here (not inside the availability panel) so every
    tier — including hot-only — drains freshly-ingested articles before
    the wire's newsdesk generator queries war_room_article_extractions.
    Without this, new stories were invisible to newsdesk until the next
    warm cycle up to 4h later.
    """
    try:
        from pipeline.db.connection import get_connection
        from pipeline.intel.articles import crawl_missing_bodies, ingest_all_feeds

        ctx.db_conn = get_connection()

        console.print("\n[bold]Article Store[/bold]")
        feed_map: dict[str, list] = {}
        if ctx.wisden_items:
            feed_map["wisden"] = ctx.wisden_items
        if ctx.ca_items:
            feed_map["cricketaddictor"] = ctx.ca_items
        if ctx.ct_items:
            feed_map["crictracker"] = ctx.ct_items
        if ctx.espn_items:
            feed_map["espncricinfo"] = ctx.espn_items
        ingest_all_feeds(ctx.db_conn, feed_map)
        crawl_missing_bodies(ctx.db_conn)

        try:
            import asyncio

            from pipeline.intel.article_extraction import run_extraction

            ctx.extraction_stats = asyncio.run(
                run_extraction(ctx.db_conn, ctx.season, max_articles=30)
            )
        except Exception as e:
            console.print(f"  [yellow]Article extraction failed: {e}[/yellow]")
            ctx.extraction_stats = {
                "processed": 0, "events": 0, "summaries": 0,
                "errors": 0, "skipped": 0,
            }
    except Exception as e:
        console.print(f"  [yellow]Article store: {e}[/yellow]")
        ctx.db_conn = None
