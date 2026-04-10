"""Dossier panel — opposition scouting report (cool tier, match-day only)."""

import asyncio
from datetime import datetime, timezone

from rich.console import Console

from pipeline.clock import today_ist_iso
from pipeline.context import SyncContext
from pipeline.writer import write_panel

console = Console()


def sync(ctx: SyncContext) -> None:
    """Generate opposition dossiers for today's matches."""
    if ctx.db_conn is None:
        return

    today_str = today_ist_iso()
    today_scheduled = [
        m for m in ctx.today_matches
        if m.date == today_str and m.status in ("scheduled", "live")
    ] if ctx.today_matches else []

    if not today_scheduled:
        return

    try:
        from pipeline.intel.dossier import generate_dossier

        dossiers = []
        for match in today_scheduled:
            for perspective, opponent in [
                (match.team1, match.team2),
                (match.team2, match.team1),
            ]:
                dossier = asyncio.run(generate_dossier(
                    ctx.db_conn, ctx.season, opponent, perspective,
                    venue_city=match.city,
                ))
                if dossier:
                    dossiers.append(dossier)

        if dossiers:
            write_panel(
                "dossier", dossiers,
                data_dir=ctx.data_dir, public_dir=ctx.public_dir,
                db_conn=ctx.db_conn, season=ctx.season,
            )
            ctx.meta["dossiers"] = {
                "synced_at": _now_iso(),
                "count": len(dossiers),
            }
    except Exception as e:
        console.print(f"  [yellow]Dossier skipped: {e}[/yellow]")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
