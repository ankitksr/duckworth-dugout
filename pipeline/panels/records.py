"""Records panel — career milestone tracking (cool tier)."""

import asyncio
from datetime import datetime, timezone

from rich.console import Console

from pipeline.context import SyncContext
from pipeline.writer import write_panel

console = Console()


def sync(ctx: SyncContext) -> None:
    """Generate record watchlist."""
    try:
        from pipeline.intel.records import generate_records

        records = asyncio.run(generate_records(ctx.season))
        if records:
            write_panel(
                "records", records,
                data_dir=ctx.data_dir, public_dir=ctx.public_dir,
                db_conn=ctx.db_conn, season=ctx.season,
            )
            ctx.meta["records"] = {"synced_at": _now_iso(), "status": "generated"}
    except Exception as e:
        console.print(f"  [yellow]Records skipped: {e}[/yellow]")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
