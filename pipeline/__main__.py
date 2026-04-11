"""CLI entry point for duckworth-dugout pipeline.

Usage:
    uv run python -m pipeline sync                          # all tiers
    uv run python -m pipeline sync --tiers hot              # hot tier only
    uv run python -m pipeline sync --tiers hot,warm         # multiple tiers
    uv run python -m pipeline sync --panel standings        # single panel
    uv run python -m pipeline sync --watch --interval 300   # continuous
    uv run python -m pipeline seed-sample                   # copy sample JSON
"""

import shutil
import time

import click
from rich.console import Console

console = Console()


@click.group()
def cli() -> None:
    """Duckworth Dugout — IPL season command center pipeline."""


@cli.command()
@click.option(
    "--tiers",
    default="all",
    help="Comma-separated tiers to sync: hot, warm, cool, all",
)
@click.option(
    "--panel",
    default=None,
    help="Sync a single panel by name (overrides --tiers)",
)
@click.option("--season", default="2026", help="IPL season (default: 2026)")
@click.option("--watch", is_flag=True, help="Continuous polling mode")
@click.option("--interval", default=300, type=int, help="Polling interval in seconds")
@click.option("--force", is_flag=True, help="Force regeneration (bypass caches)")
def sync(
    tiers: str,
    panel: str | None,
    season: str,
    watch: bool,
    interval: int,
    force: bool,
) -> None:
    """Sync war room panels."""
    from pipeline.sync import sync_tiers

    tier_list = [t.strip() for t in tiers.split(",")]

    if watch:
        console.print(f"[bold]Watch mode — syncing every {interval}s[/bold]")
        while True:
            try:
                sync_tiers(tier_list, season=season, panel=panel, force=force)
                console.print(
                    f"\n[dim]Next sync in {interval}s... (Ctrl+C to stop)[/dim]\n"
                )
                time.sleep(interval)
            except KeyboardInterrupt:
                console.print("\n[bold]Stopped.[/bold]")
                break
    else:
        sync_tiers(tier_list, season=season, panel=panel, force=force)


@cli.command("live-update")
@click.option("--season", default="2026", help="IPL season (default: 2026)")
def live_update(season: str) -> None:
    """Live score update — RSS + page crawl for rich live data."""
    import json
    from dataclasses import asdict

    from pipeline.config import ROOT_DIR

    DATA_DIR = ROOT_DIR / "data"
    PUBLIC_API = ROOT_DIR / "frontend" / "public" / "api" / "ipl" / "war-room"

    # Load current schedule from disk
    sched_path = PUBLIC_API / "schedule.json"
    if not sched_path.exists():
        from pipeline.sources.schedule import load_fixtures
        matches = load_fixtures(season)
        if not matches:
            console.print("[red]No schedule data found[/red]")
            return
    else:
        from pipeline.models import ScheduleMatch
        raw = json.loads(sched_path.read_text(encoding="utf-8"))
        matches = []
        for m in raw:
            fields = {k: m.get(k) for k in ScheduleMatch.__dataclass_fields__}
            matches.append(ScheduleMatch(**fields))

    # Reset stale "live" back to "scheduled" so RSS must re-confirm.
    # Prevents stale live status persisting from a previous buggy run.
    for m in matches:
        if m.status == "live":
            m.status = "scheduled"

    # RSS live overlay
    from pipeline.sources.schedule import overlay_live_scores
    matches = overlay_live_scores(matches)

    live = [m for m in matches if m.status == "live"]
    if not live:
        console.print("[dim]No live IPL matches[/dim]")
        return

    # Write schedule so live_crawl can read it
    for path in [PUBLIC_API / "schedule.json", DATA_DIR / "war-room" / "schedule.json"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump([asdict(m) for m in matches], f, ensure_ascii=False, indent=2)
            f.write("\n")

    # Page crawl for rich live data (overs, CRR, RRR, forecast)
    try:
        from pipeline.sources.live_crawl import (
            crawl_live_matches_sync,
            patch_schedule_with_live,
            write_live_archive,
            write_live_snapshot,
        )

        results = crawl_live_matches_sync()
        if results:
            patch_schedule_with_live(results)
            write_live_snapshot(results)
            write_live_archive(results)
    except Exception as e:
        console.print(f"  [yellow]Live crawl: {e}[/yellow]")

    for m in live:
        console.print(
            f"  [green]{m.team1.upper()} {m.score1 or '?'}"
            f" vs {m.team2.upper()} {m.score2 or '?'}[/green]"
        )


@cli.command("refresh-standings")
@click.option("--season", default="2026", help="IPL season (default: 2026)")
def refresh_standings(season: str) -> None:
    """Refresh standings from RSS — no LLM, no article crawl.

    Intended for live-update workflow to keep the points table fresh
    during match windows without running the full warm-tier sync
    (which would trigger article extraction + LLM calls).

    Runs just the standings panel over freshly-fetched Wisden +
    CricketAddictor RSS. Wikipedia/Cricsheet fall back as usual if
    RSS parse is empty.
    """
    from pipeline.config import DATA_DIR, ROOT_DIR
    from pipeline.context import SyncContext
    from pipeline.panels import standings as standings_panel
    from pipeline.sources.feeds import FEEDS
    from pipeline.sources.rss import RSSFetcher

    public_dir = ROOT_DIR / "frontend" / "public" / "api" / "ipl" / "war-room"
    data_dir = DATA_DIR / "war-room"

    ctx = SyncContext(season=season, data_dir=data_dir, public_dir=public_dir)

    console.print("[bold]Fetching Wisden feed...[/bold]")
    ctx.wisden_items = RSSFetcher(FEEDS["wisden"]["url"]).fetch()
    console.print(f"  [dim]{len(ctx.wisden_items)} items[/dim]")

    console.print("[bold]Fetching CricketAddictor feed...[/bold]")
    ctx.ca_items = RSSFetcher(FEEDS["cricketaddictor"]["url"]).fetch()
    console.print(f"  [dim]{len(ctx.ca_items)} items[/dim]")

    standings_panel.sync(ctx)


@cli.command("pull-enrichment")
@click.option("--output", default="data/enrichment.duckdb", help="Output path")
def pull_enrichment(output: str) -> None:
    """Download enrichment.duckdb from the latest GitHub release snapshot."""
    import subprocess
    import sys

    tag = "data-snapshot"
    asset = "enrichment.duckdb"
    cmd = ["gh", "release", "download", tag, "-p", asset, "-D", str(output).rsplit("/", 1)[0], "--clobber"]
    console.print(f"[dim]Downloading {asset} from release '{tag}'…[/dim]")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"[red]Failed: {result.stderr.strip()}[/red]")
        console.print("[dim]Ensure 'gh' is installed and you have repo access.[/dim]")
        sys.exit(1)
    console.print(f"[green]Downloaded to {output}[/green]")


@cli.command("migrate-articles")
@click.option("--season", default="2026", help="IPL season (default: 2026)")
@click.option(
    "--force",
    is_flag=True,
    help="Re-process articles already extracted at the current version",
)
def migrate_articles(season: str, force: bool) -> None:
    """One-shot extraction of every unprocessed article in the local DB.

    Normal sync runs cap article extraction at 30 per cycle to fit the CI
    time budget. This command ignores the cap and processes the entire
    backlog in one go — typically used once after shipping the article
    extraction layer (or after bumping EXTRACTION_VERSION).

    Idempotent: re-running skips already-processed articles. Resumable:
    safe to Ctrl-C and re-run. Use --force to re-process the whole backlog.
    """
    import asyncio

    from pipeline.db.connection import get_connection
    from pipeline.intel.article_extraction import (
        EXTRACTION_VERSION,
        run_migration,
    )

    conn = get_connection()
    console.print(
        f"[bold]Migrating articles for season {season}"
        f" (extraction_version={EXTRACTION_VERSION}"
        f"{', force=True' if force else ''})…[/bold]"
    )
    stats = asyncio.run(run_migration(conn, season, force=force))
    console.print(
        f"[green]Done.[/green] processed={stats['processed']} "
        f"events={stats['events']} summaries={stats['summaries']} "
        f"skipped={stats['skipped']} errors={stats['errors']}"
    )


@cli.command("seed-sample")
def seed_sample() -> None:
    """Copy sample JSON files to frontend public directory."""
    from pipeline.config import ROOT_DIR

    sample_dir = ROOT_DIR / "data" / "sample"
    target_dir = ROOT_DIR / "frontend" / "public" / "api" / "ipl" / "war-room"
    target_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for f in sample_dir.glob("*.json"):
        shutil.copy2(f, target_dir / f.name)
        count += 1

    console.print(f"[green]Seeded {count} sample JSON files to {target_dir}[/green]")


if __name__ == "__main__":
    cli()
