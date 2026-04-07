"""Narratives panel — per-team season arc narratives (cool tier)."""

import asyncio
from datetime import datetime, timezone

from rich.console import Console

from pipeline.context import SyncContext
from pipeline.writer import write_panel

console = Console()


def sync(ctx: SyncContext) -> None:
    """Generate season narratives."""
    if ctx.db_conn is None:
        return

    try:
        from pipeline.intel.narrative import generate_narratives

        narratives = asyncio.run(generate_narratives(ctx.db_conn, ctx.season))
        if narratives:
            write_panel(
                "narratives", narratives,
                data_dir=ctx.data_dir, public_dir=ctx.public_dir,
                db_conn=ctx.db_conn, season=ctx.season,
            )
            ctx.meta["narratives"] = {
                "synced_at": _now_iso(),
                "count": len(narratives),
            }
    except Exception as e:
        console.print(f"  [yellow]Narratives skipped: {e}[/yellow]")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
