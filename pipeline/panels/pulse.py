"""Season Pulse (Rank River) panel.

Builds pulse from fused schedule data + Cricsheet innings for NRR.
"""

import json
from dataclasses import asdict
from datetime import datetime, timezone

from rich.console import Console

from pipeline.context import SyncContext
from pipeline.writer import write_panel

console = Console()


def sync(ctx: SyncContext) -> None:
    """Sync the Season Pulse panel."""
    from pipeline.sources.cricsheet import build_pulse_from_schedule

    # Load schedule: prefer ctx data, fall back to saved JSON
    schedule: list[dict] = []
    if ctx.schedule_matches:
        schedule = [
            asdict(m) if hasattr(m, "__dataclass_fields__") else m
            for m in ctx.schedule_matches
        ]
    else:
        sched_path = ctx.public_dir / "schedule.json"
        if sched_path.exists():
            schedule = json.loads(sched_path.read_text(encoding="utf-8"))

    # Normalize standings to dicts
    std_dicts: list[dict] | None = None
    if ctx.standings_rows:
        std_dicts = [
            asdict(r) if hasattr(r, "__dataclass_fields__") else r
            for r in ctx.standings_rows
        ]

    data = build_pulse_from_schedule(schedule, std_dicts, ctx.season)

    if data:
        write_panel(
            "pulse", data,
            data_dir=ctx.data_dir, public_dir=ctx.public_dir,
            db_conn=ctx.db_conn, season=ctx.season,
        )
        ctx.meta["pulse"] = {
            "synced_at": _now_iso(),
            "teams": len(data),
            "source": "schedule+cricsheet",
        }
    else:
        ctx.meta["pulse"] = {
            "synced_at": _now_iso(),
            "teams": 0,
            "error": "no_data",
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
