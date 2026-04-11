"""Standings panel — IPL points table.

Cascade: Cricbuzz -> ESPNcricinfo -> Wisden RSS -> CricketAddictor
         -> Wikipedia -> Cricsheet.

The points table is pulled verbatim from upstream sources. No local
derivation from schedule.json: a partial self-patch (e.g. one team
updated from a completed fixture, another blocked by a no-result
filter) produces an inconsistent table, which is worse than a
uniformly-stale one. Accept upstream latency; trust the source.

Cricbuzz and ESPN both refresh within minutes of a match ending.
Wisden / CricketAddictor / Wikipedia publish a new article per match
and lag 30 min – several hours, so they now sit below the live
scrapes as safety nets.
"""

from dataclasses import asdict
from datetime import datetime, timezone

from rich.console import Console

from pipeline.context import SyncContext
from pipeline.writer import write_panel

console = Console()


def sync(ctx: SyncContext) -> None:
    """Sync standings. Updates ctx.standings_rows for downstream panels."""
    from pipeline.sources.cricbuzz import fetch_cricbuzz_standings
    from pipeline.sources.espn_standings import fetch_espn_standings
    from pipeline.sources.standings import parse_standings, parse_standings_from_feed

    source = "cricbuzz"
    rows = fetch_cricbuzz_standings(ctx.season)

    if not rows:
        source = "espn"
        rows = fetch_espn_standings(ctx.season)

    if not rows:
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
