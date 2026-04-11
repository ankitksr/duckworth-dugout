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
@click.argument("what", required=False, default="all")
@click.option("--season", default="2026", help="IPL season (default: 2026)")
@click.option("--watch", is_flag=True, help="Continuous polling mode")
@click.option("--interval", default=300, type=int, help="Polling interval in seconds")
@click.option("--force", is_flag=True, help="Force regeneration (bypass caches)")
def sync(
    what: str,
    season: str,
    watch: bool,
    interval: int,
    force: bool,
) -> None:
    """Sync war room panels.

    WHAT is a comma-separated list of tier names (live, hot, warm, cool,
    all) and/or panel names (e.g. standings, pulse). Defaults to "all".

    \b
    Examples:
      pipeline sync live                  # fast refresh path
      pipeline sync live,hot              # live + intel/wire
      pipeline sync standings             # single panel
      pipeline sync standings,pulse       # two panels
      pipeline sync all                   # everything
    """
    from pipeline.sync import sync_panels

    names = [n.strip() for n in what.split(",") if n.strip()]

    if watch:
        console.print(f"[bold]Watch mode — syncing every {interval}s[/bold]")
        while True:
            try:
                sync_panels(names, season=season, force=force)
                console.print(
                    f"\n[dim]Next sync in {interval}s... (Ctrl+C to stop)[/dim]\n"
                )
                time.sleep(interval)
            except KeyboardInterrupt:
                console.print("\n[bold]Stopped.[/bold]")
                break
    else:
        sync_panels(names, season=season, force=force)


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
