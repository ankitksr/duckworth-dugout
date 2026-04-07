"""Briefing panel — pre-match tactical brief (cool tier, match-day only)."""

import asyncio
from datetime import date, datetime, timezone

from rich.console import Console

from pipeline.context import SyncContext
from pipeline.writer import write_panel

console = Console()


def sync(ctx: SyncContext) -> None:
    """Generate pre-match briefings for today's scheduled matches."""
    if ctx.db_conn is None:
        return

    today_str = date.today().isoformat()
    today_scheduled = [
        m for m in ctx.today_matches
        if m.date == today_str and m.status in ("scheduled", "live")
    ] if ctx.today_matches else []

    if not today_scheduled:
        return

    try:
        from pipeline.intel.briefing import generate_briefing

        briefings = []
        for match in today_scheduled:
            brief = asyncio.run(generate_briefing(ctx.db_conn, ctx.season, match))
            if brief:
                briefings.append(brief)

        if briefings:
            write_panel(
                "briefing", briefings,
                data_dir=ctx.data_dir, public_dir=ctx.public_dir,
                db_conn=ctx.db_conn, season=ctx.season,
            )
            ctx.meta["briefings"] = {
                "synced_at": _now_iso(),
                "count": len(briefings),
            }
    except Exception as e:
        console.print(f"  [yellow]Briefing skipped: {e}[/yellow]")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
