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


# Known name mismatches between ipl_season_squad (Wikipedia-style) and
# cricket.players (Cricsheet-style) that don't resolve via initials/surname.
# Extend as false-matches are discovered. Values are the canonical name in
# cricket.players.
_NAME_ALIASES: dict[str, str] = {
    "Rohit Sharma": "RG Sharma",  # exact "Rohit Sharma" in cricket.players is a different player
    "Axar Patel": "AR Patel",     # single-initial "A Patel" collides with many players
}


def _cricsheet_initials(full_name: str) -> str:
    """'Mitchell Marsh' -> 'M Marsh'. Single-word or already-initials unchanged."""
    parts = full_name.split()
    if len(parts) < 2:
        return full_name
    # If the first token looks like initials already (e.g. "KL", "MS"), leave it
    if parts[0].isupper() and len(parts[0]) <= 3:
        return full_name
    return "".join(p[0] for p in parts[:-1]).upper() + " " + parts[-1]


def _role_tag(playing_role: str | None, bowling_style_broad: str | None) -> str:
    """Compact role annotation. Empty string when unknown."""
    if playing_role:
        pr = playing_role.lower()
        if "wicketkeeper" in pr:
            return "wk-batter"
        if "allrounder" in pr or "all-rounder" in pr:
            return "allrounder"
        if "bowler" in pr:
            return "bowler"
        if "batter" in pr or "batsman" in pr:
            return "batter"
    if bowling_style_broad:
        return f"{bowling_style_broad.lower()}-bowler"
    return ""


def resolve_squad_roles(
    conn: duckdb.DuckDBPyConnection,
    squad_names: list[str],
) -> dict[str, str]:
    """Map squad player names to a short role tag via cricket.players enrichment.

    Resolution order: alias → exact → initials form → fuzzy (surname +
    first-initial). Missing players map to an empty tag, not excluded.
    Safe if cricket.players is unenriched — returns all-empty dict.
    """
    try:
        rows = conn.execute(
            "SELECT name, playing_role, bowling_style_broad FROM cricket.players "
            "WHERE playing_role IS NOT NULL OR bowling_style_broad IS NOT NULL"
        ).fetchall()
    except Exception:
        return {}

    by_name: dict[str, tuple[str | None, str | None]] = {
        r[0]: (r[1], r[2]) for r in rows
    }
    by_surname: dict[str, list[str]] = {}
    for name in by_name:
        surname = name.split()[-1].lower()
        by_surname.setdefault(surname, []).append(name)

    result: dict[str, str] = {}
    for sq_name in squad_names:
        hit: tuple[str | None, str | None] | None = None

        # Tier 1: alias
        alias = _NAME_ALIASES.get(sq_name)
        if alias and alias in by_name:
            hit = by_name[alias]

        # Tier 2: exact
        if hit is None and sq_name in by_name:
            hit = by_name[sq_name]

        # Tier 3: initials form — only accept when playing_role is populated,
        # otherwise "A Patel" / "M Marsh"-style under-specified rows collide
        # with many players and yield wrong tags.
        if hit is None:
            ini = _cricsheet_initials(sq_name)
            cand = by_name.get(ini) if ini != sq_name else None
            if cand and cand[0]:
                hit = cand

        # Tier 4: fuzzy by surname + first-initial. Prefer candidates with
        # playing_role set; fall back to bowling-style-only if that's all
        # we have and it's unique.
        if hit is None:
            parts = sq_name.split()
            if len(parts) >= 2:
                surname = parts[-1].lower()
                first_initial = parts[0][0].upper()
                candidates = [
                    n for n in by_surname.get(surname, [])
                    if n and n[0].upper() == first_initial
                ]
                with_role = [n for n in candidates if by_name[n][0]]
                if len(with_role) == 1:
                    hit = by_name[with_role[0]]
                elif not with_role and len(candidates) == 1:
                    hit = by_name[candidates[0]]

        if hit is not None:
            tag = _role_tag(hit[0], hit[1])
            if tag:
                result[sq_name] = tag

    return result


def _format_squad_line(short: str, players: list[tuple]) -> str:
    """One-line squad: 'CSK: Gaikwad(c), Samson, Dube, Dhoni, +13 more'."""
    names = [_format_player(p[1], p[2], p[3]) for p in players]
    if len(names) <= 6:
        return f"{short}: {', '.join(names)}"
    shown = names[:5]
    return f"{short}: {', '.join(shown)}, +{len(names) - 5} more"


def _build_squad_name_index(
    conn: duckdb.DuckDBPyConnection,
    season: str,
) -> dict[str, str]:
    """Build a surname-based index mapping external names to squad names.

    Cricsheet uses initials ("AR Patel"), ESPNcricinfo uses full names
    ("Axar Patel"), squad table uses registration names ("Axar Patel").
    This maps all variants to the squad name via surname matching.
    """
    try:
        rows = conn.execute(
            "SELECT player_name FROM ipl_season_squad WHERE season = ?",
            [int(season)],
        ).fetchall()
    except Exception:
        return {}

    squad_names = [r[0] for r in rows]

    # surname → list of squad names with that surname
    by_surname: dict[str, list[str]] = {}
    for name in squad_names:
        surname = name.split()[-1].lower().rstrip(".")
        by_surname.setdefault(surname, []).append(name)

    return by_surname


def _resolve_to_squad_name(
    raw_name: str,
    by_surname: dict[str, list[str]],
) -> str:
    """Map an external player name to its squad table equivalent.

    Surname-based fuzzy matching. Used for Cricsheet → squad resolution
    where source names use initials ("AR Patel" → "Axar Patel"). NOT safe
    for freeform article text — use _strict_resolve_squad_name instead.
    """
    # Exact match first
    for candidates in by_surname.values():
        if raw_name in candidates:
            return raw_name

    surname = raw_name.split()[-1].lower().rstrip(".")
    candidates = by_surname.get(surname)
    if not candidates:
        return raw_name
    if len(candidates) == 1:
        return candidates[0]
    # Multiple players with same surname — try first-initial match
    initial = raw_name[0].upper()
    matches = [c for c in candidates if c[0].upper() == initial]
    if len(matches) == 1:
        return matches[0]
    # Still ambiguous — return raw name to avoid wrong attribution
    return raw_name


def _build_flat_squad_names(
    conn: duckdb.DuckDBPyConnection,
    season: str,
) -> set[str]:
    """Flat set of all canonical squad player names for the season."""
    try:
        rows = conn.execute(
            "SELECT player_name FROM ipl_season_squad WHERE season = ?",
            [int(season)],
        ).fetchall()
    except Exception:
        return set()
    return {r[0] for r in rows}


def _strict_resolve_squad_name(
    raw_name: str,
    flat_squad_names: set[str],
) -> str | None:
    """Exact (case-insensitive) match against the squad. Returns canonical
    name on hit, None on miss.

    For article-derived names where false positives matter more than recall:
    a non-squad mention like "Mukul Choudhary" should NOT collapse to a
    squad player like "Mukesh Choudhary" via surname fallback.
    """
    if not raw_name:
        return None
    raw = raw_name.strip()
    if not raw:
        return None
    if raw in flat_squad_names:
        return raw
    raw_lower = raw.lower()
    for squad_name in flat_squad_names:
        if squad_name.lower() == raw_lower:
            return squad_name
    return None


def _query_appearances(
    conn: duckdb.DuckDBPyConnection,
    season: str,
) -> dict[str, int]:
    """Count IPL match appearances per player this season.

    Merges two non-overlapping sources:
    - Cricsheet (canonical, full playing XI, but lags 1-6 days)
    - ESPNcricinfo scorecard crawl (gap-filler for matches Cricsheet doesn't have)
    Summed because they cover different matches. Names are normalized
    to squad table names via surname matching.
    """
    by_surname = _build_squad_name_index(conn, season)

    # Cricsheet: canonical, accurate, may lag
    sql = """
        SELECT p.name, COUNT(DISTINCT x.match_id) AS appearances
        FROM (
            SELECT match_id, player_id FROM cricket.batting_scorecard
            UNION
            SELECT match_id, player_id FROM cricket.bowling_scorecard
        ) x
        JOIN cricket.players p ON x.player_id = p.id
        JOIN cricket.matches m ON x.match_id = m.id
        WHERE m.event_name = 'Indian Premier League'
          AND m.season = ?
        GROUP BY p.name
    """
    result: dict[str, int] = {}
    try:
        rows = conn.execute(sql, [season]).fetchall()
        for name, count in rows:
            squad_name = _resolve_to_squad_name(name, by_surname)
            result[squad_name] = result.get(squad_name, 0) + count
    except Exception:
        pass

    # Scorecard crawl: fills the gap for matches Cricsheet hasn't published
    try:
        from pipeline.sources.scorecard_crawl import crawl_missing_scorecards

        crawled = crawl_missing_scorecards(season, conn)
        for name, count in crawled.items():
            squad_name = _resolve_to_squad_name(name, by_surname)
            result[squad_name] = result.get(squad_name, 0) + count
    except Exception:
        pass

    return result


def _format_availability_tag(info: dict) -> str:
    """Format an availability annotation, e.g. '[OUT - hamstring - exp: season]'."""
    status = (info.get("status") or "").lower()
    if not status or status == "available":
        return ""
    bits = [status.upper()]
    if info.get("reason"):
        bits.append(info["reason"])
    if info.get("expected_return"):
        bits.append(f"exp: {info['expected_return']}")
    return f"[{' - '.join(bits)}]"


def _format_full_squad(
    short: str,
    players: list[tuple],
    appearances: dict[str, int] | None = None,
    availability: dict[str, dict] | None = None,
    roles: dict[str, str] | None = None,
) -> str:
    """Full squad block for a team."""
    lines = [f"{short} SQUAD ({len(players)} players):"]
    for fid, name, is_cap, is_ovs, price, acq in players:
        tag = _format_player(name, is_cap, is_ovs)
        role_tag = f"[{roles[name]}]" if roles and roles.get(name) else ""
        price_cr = f"₹{price / 1e7:.1f}Cr" if price else ""
        acq_tag = f"[{acq}]" if acq and acq != "auction" else ""
        played = ""
        if appearances is not None:
            n = appearances.get(name, 0)
            played = f"({n} matches)" if n else "(yet to play)"
        avail_tag = ""
        if availability and name in availability:
            avail_tag = _format_availability_tag(availability[name])
        parts = [f"  {tag}", role_tag, price_cr, acq_tag, played, avail_tag]
        lines.append(" ".join(p for p in parts if p))
    return "\n".join(lines)


def availability_map(
    conn: duckdb.DuckDBPyConnection,
    season: str,
) -> dict[str, dict]:
    """Current availability state per player. Lazy import to avoid cycles.

    Returns {} if the availability module fails for any reason — never lets
    a broken availability layer break roster context.
    """
    try:
        from pipeline.intel.availability import (
            current_availability,
            last_played_dates,
        )
        played = last_played_dates(conn, season)
        return current_availability(conn, season, played)
    except Exception:
        return {}


def injury_footer(
    conn: duckdb.DuckDBPyConnection,
    season: str,
    max_items: int = 20,
) -> str:
    """Compact one-line-ish injury list for summary-level contexts.

    Format: 'INJURY LIST: Bumrah(MI, back stress, season), Rabada(GT, hamstring, doubtful), ...'
    Returns empty string if there are no unavailable players.
    """
    state = availability_map(conn, season)
    if not state:
        return ""

    entries: list[str] = []
    for player, info in sorted(state.items()):
        status = (info.get("status") or "").lower()
        if not status or status == "available":
            continue
        fid = info.get("franchise_id", "")
        short = _SHORT.get(fid, (fid or "").upper())
        bits = [short]
        if info.get("reason"):
            bits.append(info["reason"])
        if status == "doubtful":
            bits.append("doubtful")
        elif info.get("expected_return"):
            bits.append(info["expected_return"])
        entries.append(f"{player}({', '.join(b for b in bits if b)})")
        if len(entries) >= max_items:
            break

    if not entries:
        return ""
    return "INJURY LIST: " + ", ".join(entries)


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

    footer = injury_footer(conn, season)
    if footer:
        lines.append("")
        lines.append(footer)
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
    appearances = _query_appearances(conn, season)
    avail = availability_map(conn, season)
    parts = []
    all_names: list[str] = []
    team_rows: dict[str, list[tuple]] = {}
    for fid in (team1, team2):
        rows = _query_squad(conn, season, fid)
        team_rows[fid] = rows
        all_names.extend(r[1] for r in rows)
    roles = resolve_squad_roles(conn, all_names)
    for fid in (team1, team2):
        players = team_rows[fid]
        short = _SHORT.get(fid, fid.upper())
        if players:
            parts.append(_format_full_squad(short, players, appearances, avail, roles))
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

    appearances = _query_appearances(conn, season)
    avail = availability_map(conn, season)
    by_team: dict[str, list[tuple]] = {}
    for r in rows:
        by_team.setdefault(r[0], []).append(r)

    roles = resolve_squad_roles(conn, [r[1] for r in rows])
    parts = [f"CURRENT ROSTERS (IPL {season}):"]
    for fid in sorted(by_team, key=lambda f: _SHORT.get(f, f)):
        short = _SHORT.get(fid, fid.upper())
        parts.append(_format_full_squad(short, by_team[fid], appearances, avail, roles))
    return "\n\n".join(parts)


def for_team(conn: duckdb.DuckDBPyConnection, season: str, team: str) -> str:
    """Full squad for one team. ~20 lines.

    Use for: narrative (per-team), dossier (opposition).
    """
    appearances = _query_appearances(conn, season)
    avail = availability_map(conn, season)
    players = _query_squad(conn, season, team)
    short = _SHORT.get(team, team.upper())
    if players:
        roles = resolve_squad_roles(conn, [r[1] for r in players])
        return _format_full_squad(short, players, appearances, avail, roles)
    return f"{short}: (no squad data)"


def active_names(conn: duckdb.DuckDBPyConnection, season: str) -> set[str]:
    """Set of all player names in current squads.

    Use for: records (active player filtering).
    """
    rows = _query_squad(conn, season)
    return {r[1] for r in rows}
