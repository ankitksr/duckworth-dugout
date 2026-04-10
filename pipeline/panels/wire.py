"""AI Wire panel — multi-generator editorial intelligence.

Orchestrates five specialized wire generators (situation, scout, newsdesk,
preview, take) and aggregates their output into a single wire.json feed.
"""

import asyncio
import json
from datetime import datetime, timezone

from rich.console import Console

from pipeline.clock import today_ist_iso
from pipeline.context import SyncContext
from pipeline.models import ScheduleMatch
from pipeline.writer import write_panel

console = Console()


def sync(ctx: SyncContext, *, force: bool = False) -> None:
    """Sync the AI Wire panel."""
    # Ensure DB connection
    db_conn = ctx.db_conn
    if db_conn is None:
        try:
            from pipeline.db.connection import get_connection

            db_conn = get_connection()
            ctx.db_conn = db_conn
        except Exception as e:
            console.print(f"  [yellow]Wire: DB connection failed: {e}[/yellow]")
            return

    # Ensure source column exists (migration for existing DBs)
    try:
        db_conn.execute(
            "ALTER TABLE war_room_wire ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'wire'"
        )
    except Exception:
        pass

    # Ensure hash_version column exists (migration for existing DBs).
    # Used by intel/wire.py to expire legacy same-day rows after a hash bump.
    try:
        db_conn.execute(
            "ALTER TABLE war_room_wire ADD COLUMN IF NOT EXISTS hash_version VARCHAR DEFAULT 'v1'"
        )
    except Exception:
        pass

    # One-time migration: expire legacy entries from the monolithic generator
    try:
        expired = db_conn.execute(
            """
            UPDATE war_room_wire SET expired = TRUE
            WHERE coalesce(source, 'wire') = 'wire' AND expired = FALSE
            RETURNING id
            """
        ).fetchall()
        if expired:
            console.print(
                f"  [dim]Wire: migrated {len(expired)} legacy entries to expired[/dim]"
            )
    except Exception:
        pass

    # Load today's matches if not available
    today_matches = ctx.today_matches
    if not today_matches:
        sched_path = ctx.public_dir / "schedule.json"
        if sched_path.exists():
            today_str = today_ist_iso()
            for m in json.loads(sched_path.read_text(encoding="utf-8")):
                if m.get("date") == today_str:
                    today_matches.append(ScheduleMatch.from_schedule_dict(m))

    try:
        from pipeline.intel.wire import export_wire_json, generate_wire

        asyncio.run(generate_wire(db_conn, ctx.season, today_matches, force=force))
        wire_data = export_wire_json(db_conn, ctx.season)
        if wire_data:
            write_panel(
                "wire", wire_data,
                data_dir=ctx.data_dir, public_dir=ctx.public_dir,
                db_conn=ctx.db_conn, season=ctx.season,
            )
            ctx.meta["wire"] = {"synced_at": _now_iso(), "items": len(wire_data)}
    except Exception as e:
        console.print(f"  [yellow]Wire skipped: {e}[/yellow]")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
