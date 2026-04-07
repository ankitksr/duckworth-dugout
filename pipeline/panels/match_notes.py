"""Match Notes panel — post-match editorial one-liners (cool tier)."""

import asyncio
from datetime import datetime, timezone

from rich.console import Console

from pipeline.context import SyncContext
from pipeline.writer import write_panel

console = Console()


def sync(ctx: SyncContext) -> None:
    """Generate and write match notes."""
    try:
        from pipeline.intel.match_notes import generate_match_notes

        notes = asyncio.run(generate_match_notes(ctx.season))
        if notes:
            write_panel(
                "match-notes", notes,
                data_dir=ctx.data_dir, public_dir=ctx.public_dir,
                db_conn=ctx.db_conn, season=ctx.season,
            )
            ctx.meta["match_notes"] = {
                "synced_at": _now_iso(),
                "count": len(notes),
            }
    except Exception as e:
        console.print(f"  [yellow]Match notes skipped: {e}[/yellow]")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
