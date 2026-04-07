"""Standings panel — IPL points table.

Cascade: Wisden RSS -> CricketAddictor -> Wikipedia -> Cricsheet.
"""

import json
from dataclasses import asdict
from datetime import datetime, timezone

from rich.console import Console

from pipeline.context import SyncContext
from pipeline.writer import write_panel

console = Console()


def sync(ctx: SyncContext) -> None:
    """Sync standings. Updates ctx.standings_rows for downstream panels."""
    from pipeline.sources.standings import parse_standings, parse_standings_from_feed

    source = "wisden"
    rows = parse_standings(ctx.wisden_items or [])

    if not rows:
        source = "cricketaddictor"
        rows = parse_standings_from_feed(ctx.ca_items or [], source_name="CricketAddictor")

    if not rows:
        from pipeline.sources.wikipedia import fetch_wikipedia_standings

        source = "wikipedia"
        rows = fetch_wikipedia_standings(ctx.season)

    if not rows:
        from pipeline.sources.cricsheet import query_standings

        source = "cricsheet_fallback"
        rows = query_standings(ctx.season)

    if rows:
        _patch_standings_with_schedule(rows, ctx.public_dir)
        ctx.standings_rows = rows

        data = [asdict(r) for r in rows]
        write_panel(
            "standings", data,
            data_dir=ctx.data_dir, public_dir=ctx.public_dir,
            db_conn=ctx.db_conn, season=ctx.season,
        )
        ctx.meta["standings"] = {
            "synced_at": _now_iso(),
            "teams": len(rows),
            "source": source,
        }
    else:
        ctx.meta["standings"] = {
            "synced_at": _now_iso(),
            "teams": 0,
            "error": "no_data",
        }


def _patch_standings_with_schedule(rows: list, public_dir) -> None:
    """Fix standings rows where the RSS source is stale."""
    from pathlib import Path

    schedule_path = Path(public_dir) / "schedule.json"
    if not schedule_path.exists():
        return

    completed = [
        m for m in json.loads(schedule_path.read_text(encoding="utf-8"))
        if m.get("status") == "completed" and m.get("winner")
    ]

    sched_wins: dict[str, int] = {}
    sched_losses: dict[str, int] = {}
    sched_played: dict[str, int] = {}
    for m in completed:
        for t in (m["team1"], m["team2"]):
            sched_played[t] = sched_played.get(t, 0) + 1
        winner = m["winner"]
        loser = m["team2"] if winner == m["team1"] else m["team1"]
        sched_wins[winner] = sched_wins.get(winner, 0) + 1
        sched_losses[loser] = sched_losses.get(loser, 0) + 1

    patched = []
    for row in rows:
        fid = row.franchise_id
        sp = sched_played.get(fid, 0)
        sw = sched_wins.get(fid, 0)

        if sp > row.played:
            row.played = sp
            row.wins = max(row.wins, sw)
            row.losses = max(row.losses, sched_losses.get(fid, 0))
            row.points = row.wins * 2
            patched.append(row.short_name)

    if patched:
        rows.sort(key=lambda r: (-r.points, -_parse_nrr(r.nrr)))
        for i, r in enumerate(rows):
            r.position = i + 1
        console.print(
            f"  [green]Standings: patched {', '.join(patched)} from schedule[/green]"
        )


def _parse_nrr(nrr: str) -> float:
    try:
        return float(nrr)
    except (ValueError, TypeError):
        return 0.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
