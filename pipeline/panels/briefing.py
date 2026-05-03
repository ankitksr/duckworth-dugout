"""Briefing panel — pre-match tactical brief (cool tier).

Looks ahead to the next upcoming match day, not just today. The cache
key (team1+team2+date) prevents redundant LLM calls when the matchup
hasn't changed.
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


def sync(ctx: SyncContext) -> None:
    """Generate pre-match briefings for the next upcoming match(es)."""
    if ctx.db_conn is None:
        return

    # Load full schedule — don't rely on ctx.today_matches
    sched_path = ctx.public_dir / "schedule.json"
    if not sched_path.exists():
        return

    all_matches = json.loads(sched_path.read_text(encoding="utf-8"))
    today_str = today_ist_iso()

    # Find the next date that still has a scheduled/live match.
    upcoming = [
        m for m in all_matches
        if m.get("date", "") >= today_str
        and m.get("status") in ("scheduled", "live")
    ]
    upcoming.sort(key=lambda m: (m["date"], m.get("time", "")))

    if not upcoming:
        return

    next_date = upcoming[0]["date"]

    # Pull non-completed matches on next_date. On double-header days, drop
    # the early match once its status flips to "completed" so the panel
    # focuses on what's still to come (or live). The `upcoming` filter
    # above guarantees at least one non-completed match exists on next_date.
    next_matches = [
        m for m in all_matches
        if m.get("date") == next_date and m.get("status") != "completed"
    ]
    next_matches.sort(key=lambda m: m.get("time", ""))

    targets = [ScheduleMatch.from_schedule_dict(m) for m in next_matches]

    try:
        from pipeline.intel.briefing import generate_briefing

        briefings = []
        for match in targets:
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
                "next_date": next_date,
            }
    except Exception as e:
        console.print(f"  [yellow]Briefing skipped: {e}[/yellow]")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
