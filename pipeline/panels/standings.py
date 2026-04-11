"""Standings panel — IPL points table.

Cascade: Wisden RSS -> CricketAddictor -> Wikipedia -> Cricsheet.

The points table is pulled verbatim from upstream sources. No local
derivation from schedule.json: a partial self-patch (e.g. one team
updated from a completed fixture, another blocked by a no-result
filter) produces an inconsistent table, which is worse than a
uniformly-stale one. Accept RSS latency; trust the source.
"""

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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
