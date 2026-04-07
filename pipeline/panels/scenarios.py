"""Scenarios panel — playoff analysis, elimination watch (cool tier)."""

import asyncio
from datetime import datetime, timezone

from rich.console import Console

from pipeline.context import SyncContext
from pipeline.writer import write_panel

console = Console()


def sync(ctx: SyncContext) -> None:
    """Generate playoff scenarios."""
    try:
        from pipeline.intel.scenarios import generate_scenarios

        scenarios = asyncio.run(generate_scenarios(ctx.season))
        if scenarios:
            write_panel(
                "scenarios", scenarios,
                data_dir=ctx.data_dir, public_dir=ctx.public_dir,
                db_conn=ctx.db_conn, season=ctx.season,
            )
            ctx.meta["scenarios"] = {"synced_at": _now_iso(), "status": "generated"}
    except Exception as e:
        console.print(f"  [yellow]Scenarios skipped: {e}[/yellow]")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
