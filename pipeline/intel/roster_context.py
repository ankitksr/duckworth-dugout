"""Roster context builder for LLM prompts.

Queries ipl_season_squad to build compact team roster strings.
Three granularity levels to avoid bloating LLM context:

- summary():      1 line per team (captains + top buys) — for wire, narrative
- for_match():    full squads for 2 teams — for briefing, dossier
- for_team():     full squad for 1 team — for narrative (team-specific)
- active_names(): flat set of all player names — for records filtering
"""

import duckdb

from pipeline.ipl.franchise_metadata import IPL_FRANCHISES

_SHORT = {fid: d["short_name"] for fid, d in IPL_FRANCHISES.items() if not d.get("defunct")}


def _query_squad(
    conn: duckdb.DuckDBPyConnection,
    season: str,
    franchise_id: str | None = None,
) -> list[tuple]:
    """Raw squad query.

    Returns (franchise_id, player_name, is_captain, is_overseas,
    price_inr, acquisition_type).
    """
    sql = """
        SELECT franchise_id, player_name, is_captain, is_overseas, price_inr, acquisition_type
        FROM ipl_season_squad
        WHERE season = ?
    """
    params: list = [int(season)]
    if franchise_id:
        sql += " AND franchise_id = ?"
        params.append(franchise_id)
    sql += " ORDER BY franchise_id, price_inr DESC"

    try:
        return conn.execute(sql, params).fetchall()
    except Exception:
        return []


def _format_player(name: str, is_captain: bool, is_overseas: bool) -> str:
    """Format a player name with (c) and * markers."""
    suffix = ""
    if is_captain:
        suffix += "(c)"
    if is_overseas:
        suffix += "*"
    return f"{name}{suffix}" if suffix else name


def _format_squad_line(short: str, players: list[tuple]) -> str:
    """One-line squad: 'CSK: Gaikwad(c), Samson, Dube, Dhoni, +13 more'."""
    names = [_format_player(p[1], p[2], p[3]) for p in players]
    if len(names) <= 6:
        return f"{short}: {', '.join(names)}"
    shown = names[:5]
    return f"{short}: {', '.join(shown)}, +{len(names) - 5} more"


def _format_full_squad(short: str, players: list[tuple]) -> str:
    """Full squad block for a team."""
    lines = [f"{short} SQUAD ({len(players)} players):"]
    for fid, name, is_cap, is_ovs, price, acq in players:
        tag = _format_player(name, is_cap, is_ovs)
        price_cr = f"₹{price / 1e7:.1f}Cr" if price else ""
        acq_tag = f"[{acq}]" if acq and acq != "auction" else ""
        parts = [f"  {tag}", price_cr, acq_tag]
        lines.append(" ".join(p for p in parts if p))
    return "\n".join(lines)


def summary(conn: duckdb.DuckDBPyConnection, season: str) -> str:
    """Compact 1-line-per-team roster summary. ~10 lines total.

    Use for: wire, narrative, smart_ticker.
    """
    rows = _query_squad(conn, season)
    if not rows:
        return ""

    by_team: dict[str, list[tuple]] = {}
    for r in rows:
        by_team.setdefault(r[0], []).append(r)

    lines = ["CURRENT ROSTERS (IPL {season}):".format(season=season)]
    for fid in sorted(by_team, key=lambda f: _SHORT.get(f, f)):
        short = _SHORT.get(fid, fid.upper())
        lines.append(_format_squad_line(short, by_team[fid]))
    return "\n".join(lines)


def for_match(
    conn: duckdb.DuckDBPyConnection,
    season: str,
    team1: str,
    team2: str,
) -> str:
    """Full squads for both teams in a match. ~40 lines.

    Use for: briefing, dossier.
    """
    parts = []
    for fid in (team1, team2):
        players = _query_squad(conn, season, fid)
        short = _SHORT.get(fid, fid.upper())
        if players:
            parts.append(_format_full_squad(short, players))
        else:
            parts.append(f"{short}: (no squad data)")
    return "\n\n".join(parts)


def all_squads(conn: duckdb.DuckDBPyConnection, season: str) -> str:
    """Full squads for all teams. ~200 lines.

    Use for: wire, narrative — modules that need complete roster awareness.
    """
    rows = _query_squad(conn, season)
    if not rows:
        return ""

    by_team: dict[str, list[tuple]] = {}
    for r in rows:
        by_team.setdefault(r[0], []).append(r)

    parts = [f"CURRENT ROSTERS (IPL {season}):"]
    for fid in sorted(by_team, key=lambda f: _SHORT.get(f, f)):
        short = _SHORT.get(fid, fid.upper())
        parts.append(_format_full_squad(short, by_team[fid]))
    return "\n\n".join(parts)


def for_team(conn: duckdb.DuckDBPyConnection, season: str, team: str) -> str:
    """Full squad for one team. ~20 lines.

    Use for: narrative (per-team), dossier (opposition).
    """
    players = _query_squad(conn, season, team)
    short = _SHORT.get(team, team.upper())
    if players:
        return _format_full_squad(short, players)
    return f"{short}: (no squad data)"


def active_names(conn: duckdb.DuckDBPyConnection, season: str) -> set[str]:
    """Set of all player names in current squads.

    Use for: records (active player filtering).
    """
    rows = _query_squad(conn, season)
    return {r[1] for r in rows}
