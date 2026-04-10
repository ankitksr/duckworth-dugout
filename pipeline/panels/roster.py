"""Squad roster panel.

Reads ipl_season_squad and current-season appearances; emits
roster.json so the frontend can render team squads in the team file.
Pure read-side — no LLM calls. Lives in warm tier alongside availability.
"""

from datetime import datetime, timezone

from rich.console import Console

from pipeline.context import SyncContext
from pipeline.writer import write_panel

console = Console()


def sync(ctx: SyncContext) -> None:
    """Sync the squad roster panel."""
    db_conn = ctx.db_conn
    if db_conn is None:
        try:
            from pipeline.db.connection import get_connection

            db_conn = get_connection()
            ctx.db_conn = db_conn
        except Exception as e:
            console.print(f"  [yellow]Roster: DB connection failed: {e}[/yellow]")
            return

    try:
        from pipeline.intel.roster_context import _query_appearances, _query_squad
    except Exception as e:
        console.print(f"  [yellow]Roster: import failed: {e}[/yellow]")
        return

    rows = _query_squad(db_conn, ctx.season)
    if not rows:
        console.print("  [yellow]Roster: no squad rows[/yellow]")
        write_panel(
            "roster", _empty_payload(ctx.season),
            data_dir=ctx.data_dir, public_dir=ctx.public_dir,
            db_conn=db_conn, season=ctx.season,
        )
        return

    appearances = _query_appearances(db_conn, ctx.season)

    by_team: dict[str, list[dict]] = {}
    for fid, name, is_cap, is_ovs, price, acq in rows:
        by_team.setdefault(fid, []).append({
            "player": name,
            "is_captain": bool(is_cap),
            "is_overseas": bool(is_ovs),
            "price_inr": price,
            "acquisition_type": acq,
            "appearances": appearances.get(name, 0),
        })

    payload = {
        "generated_at": _now_iso(),
        "season": ctx.season,
        "by_team": by_team,
    }

    write_panel(
        "roster", payload,
        data_dir=ctx.data_dir, public_dir=ctx.public_dir,
        db_conn=db_conn, season=ctx.season,
    )

    ctx.meta["roster"] = {
        "synced_at": _now_iso(),
        "teams": len(by_team),
        "players": sum(len(v) for v in by_team.values()),
    }


def _empty_payload(season: str) -> dict:
    return {
        "generated_at": _now_iso(),
        "season": season,
        "by_team": {},
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
