"""Sync orchestrator — tier-based panel dispatch.

Usage (via __main__.py):
    uv run python -m pipeline sync                     # all tiers
    uv run python -m pipeline sync --tiers hot,warm    # specific tiers
    uv run python -m pipeline sync --panel standings   # single panel
    uv run python -m pipeline sync --watch             # continuous (5 min)
"""

import importlib
import json
import uuid
from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel as RichPanel

from pipeline.clock import today_ist_iso
from pipeline.config import DATA_DIR, ROOT_DIR
from pipeline.context import SyncContext
from pipeline.llm.usage_ledger import set_sync_id
from pipeline.panels import PANEL_ORDER, resolve_panels
from pipeline.sources.rss import RSSFetcher
from pipeline.writer import write_json

console = Console()

WAR_ROOM_DATA = DATA_DIR / "war-room"
PUBLIC_API_DIR = ROOT_DIR / "frontend" / "public" / "api" / "ipl" / "war-room"


# Per-resource consumer sets — gate the fetch/init steps in sync_tiers
# on whether ANY active panel actually consumes that resource. This
# replaces the old blanket "any of 12 panels active → fetch everything"
# trigger that made `sync --panel pulse` ingest articles and burn LLM
# calls for nothing.
#
# RSS_CONSUMERS read from ctx.wisden_items / ca_items / ct_items /
# espn_items. ARTICLE_CONSUMERS read from war_room_article_extractions
# in the DB and therefore depend on the article ingest + crawl + LLM
# extraction pipeline. DB_CONSUMERS need a connection to enrichment.duckdb
# (with cricket.duckdb attached read-only) for queries or snapshot writes.
RSS_CONSUMERS: set[str] = {"intel_log", "wire", "standings", "caps"}
ARTICLE_CONSUMERS: set[str] = {"intel_log", "wire", "availability"}
DB_CONSUMERS: set[str] = {
    "roster", "availability", "pulse", "schedule", "standings", "caps",
    "wire", "briefing", "dossier", "narratives", "scenarios", "records",
    "match_notes",
}

# Panels that produce LLM-generated output. When NONE of these are
# active in a sync run, ctx.skip_llm is set so other panels (notably
# the schedule panel's inline extract_match_results step) skip their
# own LLM calls — the caller is in a fast/live mode and doesn't want
# to burn LLM credits on opportunistic refinement.
LLM_PANELS: set[str] = {
    "wire", "ticker", "scenarios", "records",
    "briefing", "dossier", "narratives", "match_notes",
}


def sync_panels(
    names: list[str],
    *,
    season: str = "2026",
    force: bool = False,
) -> None:
    """Run sync for a mixed list of tier names and panel names.

    `names` is the parsed CLI arg — comma-split values like ["live"],
    ["live", "hot"], ["standings"], or ["all"]. resolve_panels handles
    expansion and validates each entry.
    """
    active_panels = resolve_panels(names)

    # Tag every LLM call in this sync with a stable id so the ledger
    # can group "what this run cost" without relying on timestamps.
    set_sync_id(uuid.uuid4().hex[:12])

    # Drop the scorecard-crawl in-process cache so this sync gets a
    # fresh read (schedule may have changed since the last run).
    from pipeline.sources.scorecard_crawl import reset_crawl_cache
    reset_crawl_cache()

    # Determine ordered execution list
    ordered = [p for p in PANEL_ORDER if p in active_panels]

    console.print(RichPanel(
        f"[dim]Season {season} · Panels: {', '.join(ordered)}[/dim]",
        title="[bold]Dugout Sync[/bold]",
        border_style="bright_black",
    ))

    # Build sync context. skip_llm flips on when no LLM-output panel
    # is active — so e.g. `pipeline sync live` doesn't trigger the
    # schedule panel's inline LLM extraction even though schedule is
    # in the live tier. active_panels lets downstream panels detect
    # when an upstream they depend on is NOT being refreshed this run.
    ctx = SyncContext(
        season=season,
        data_dir=WAR_ROOM_DATA,
        public_dir=PUBLIC_API_DIR,
        skip_llm=not bool(active_panels & LLM_PANELS),
        active_panels=active_panels,
    )

    # Per-panel resource gating. Only fetch what active panels actually
    # consume. ARTICLE_CONSUMERS implies RSS_CONSUMERS because article
    # ingest reads from ctx.wisden_items / ca_items / ct_items / espn_items.
    if active_panels & (RSS_CONSUMERS | ARTICLE_CONSUMERS):
        _fetch_feeds(ctx)
    if active_panels & DB_CONSUMERS:
        _open_db(ctx)
    if active_panels & ARTICLE_CONSUMERS:
        _init_articles(ctx)

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


def _open_db(ctx: SyncContext) -> None:
    """Open the enrichment.duckdb connection (with cricket.duckdb attached).

    Idempotent — no-op if ctx.db_conn is already set. Catches connection
    failures so panels that defensively re-open (wire, availability)
    can still proceed if the file is missing.
    """
    if ctx.db_conn is not None:
        return
    try:
        from pipeline.db.connection import get_connection
        ctx.db_conn = get_connection()
    except Exception as e:
        console.print(f"  [yellow]DB open failed: {e}[/yellow]")
        ctx.db_conn = None


def _init_articles(ctx: SyncContext) -> None:
    """Ingest article feeds, crawl bodies, run per-article LLM extraction.

    Assumes ctx.db_conn is already set (call _open_db first). Drains
    freshly-ingested articles so the wire newsdesk generator sees new
    stories the same cycle they're published, instead of waiting for
    the next warm tier.
    """
    if ctx.db_conn is None:
        console.print("  [yellow]Article store: no DB connection, skipping[/yellow]")
        return
    try:
        from pipeline.intel.articles import crawl_missing_bodies, ingest_all_feeds

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
