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
