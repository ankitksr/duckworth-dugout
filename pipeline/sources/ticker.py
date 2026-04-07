"""Ticker panel — scrolling intel items.

Generates ticker items from available War Room data (standings, schedule)
and Cricsheet H2H queries for today's matches.
"""

import json

from rich.console import Console

from pipeline.config import DATA_DIR
from pipeline.ipl.franchise_metadata import IPL_FRANCHISES
from pipeline.models import ScheduleMatch, TickerItem

console = Console()


def _short(fid: str) -> str:
    return IPL_FRANCHISES.get(fid, {}).get("short_name", fid.upper())


def _h2h_from_cricsheet(fid1: str, fid2: str) -> str | None:
    """Query all-time H2H between two franchises from Cricsheet."""
    try:
        from pipeline.sources.cricsheet import _CRICSHEET_TO_FID, _EVENT, _connect

        # Reverse lookup: fid → cricsheet name
        fid_to_name = {v: k for k, v in _CRICSHEET_TO_FID.items()}
        name1, name2 = fid_to_name.get(fid1), fid_to_name.get(fid2)
        if not name1 or not name2:
            return None

        conn = _connect()
        try:
            rows = conn.execute("""
                SELECT outcome_winner, COUNT(*) as cnt
                FROM matches
                WHERE event_name = ?
                  AND ((team1 = ? AND team2 = ?) OR (team1 = ? AND team2 = ?))
                  AND outcome_winner IS NOT NULL
                GROUP BY outcome_winner
            """, [_EVENT, name1, name2, name2, name1]).fetchall()
        finally:
            conn.close()

        wins = {_CRICSHEET_TO_FID.get(r[0], ""): r[1] for r in rows}
        w1, w2 = wins.get(fid1, 0), wins.get(fid2, 0)
        if w1 == 0 and w2 == 0:
            return None
        return f"{_short(fid1)} vs {_short(fid2)}: {_short(fid1)} {w1}-{w2}"
    except Exception:
        return None


def generate_ticker_items(
    today_matches: list[ScheduleMatch],
    season: str,
) -> list[TickerItem]:
    items: list[TickerItem] = []

    # H2H for today's matches
    for match in today_matches:
        h2h = _h2h_from_cricsheet(match.team1, match.team2)
        if h2h:
            items.append(TickerItem(category="H2H", text=h2h))

    # Standings headline
    standings_path = DATA_DIR / "war-room" / "standings.json"
    if standings_path.exists():
        try:
            standings = json.loads(standings_path.read_text(encoding="utf-8"))
            if standings:
                top = standings[0]
                items.append(TickerItem(
                    category="STANDINGS",
                    text=(
                        f"{top['short_name']} lead the table:"
                        f" {top['wins']}W {top['losses']}L,"
                        f" NRR {top['nrr']}"
                    ),
                ))
        except (json.JSONDecodeError, KeyError):
            pass

    if items:
        console.print(f"  [green]Ticker: {len(items)} items generated[/green]")
    else:
        console.print("  [dim]Ticker: no items (no data available)[/dim]")

    return items
