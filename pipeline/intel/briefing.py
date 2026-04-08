"""Pre-Match Intel Brief — tactical scouting report for today's fixture.

Combines:
- Cricsheet historical data: H2H all-time, venue stats (direct SQL, authoritative)
- RSS current data: squad news, injuries, playing XI predictions
- Synced data: current standings, form, caps

Hybrid pattern: numbers from source (Cricsheet/standings), narratives from LLM.
Post-LLM injection enriches the response with authoritative venue_stats, form,
and match metadata — the LLM only generates editorial prose.

Staleness: regenerates per match day + matchup.

Usage:
    briefing = await generate_briefing(conn, season, match)
"""

import json
import re
from typing import Any

import duckdb
from rich.console import Console

from pipeline.config import CRICKET_DB_PATH, DATA_DIR, MEGA_AUCTION_SEASON
from pipeline.intel.articles import retrieve_for_match
from pipeline.intel.prompts import load_prompt
from pipeline.intel.tools import execute_tool, get_tool_declarations
from pipeline.ipl.franchise_metadata import IPL_FRANCHISES
from pipeline.llm.cache import LLMCache
from pipeline.models import ScheduleMatch

console = Console()

_CACHE_TASK = "war_room_briefing"
_EVENT = "Indian Premier League"


def _short(fid: str) -> str:
    return IPL_FRANCHISES.get(fid, {}).get("short_name", fid.upper())


def _cricsheet_name(fid: str) -> str | None:
    """Get primary Cricsheet team name from franchise ID."""
    fdata = IPL_FRANCHISES.get(fid)
    if not fdata:
        return None
    names = fdata.get("cricsheet_names", [])
    return names[0] if names else None


def _cricsheet_names(fid: str) -> list[str]:
    """Get all Cricsheet team name variants for a franchise ID."""
    fdata = IPL_FRANCHISES.get(fid)
    if not fdata:
        return []
    return fdata.get("cricsheet_names", [])


def _load_json(filename: str) -> Any:
    path = DATA_DIR / "war-room" / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _query_phase_for_scope(
    conn: duckdb.DuckDBPyConnection,
    names: list[str],
    season_filter: str,
) -> dict[str, Any]:
    """Run powerplay + death queries for a single team/scope."""
    placeholders = ", ".join(["?"] * len(names))
    stats: dict[str, Any] = {}

    bat_rows = conn.execute(f"""
        SELECT
            CASE WHEN d.over_number BETWEEN 0 AND 5 THEN 'pp'
                 ELSE 'death' END as phase,
            COUNT(*) as balls,
            SUM(d.runs_batter) as runs
        FROM deliveries d
        JOIN innings i ON d.innings_id = i.id
        JOIN matches m ON d.match_id = m.id
        WHERE m.event_name = ?
          AND i.batting_team IN ({placeholders})
          AND d.over_number NOT BETWEEN 6 AND 14
          AND m.season >= ?
        GROUP BY 1
    """, [_EVENT, *names, season_filter]).fetchall()

    bowl_rows = conn.execute(f"""
        SELECT
            CASE WHEN d.over_number BETWEEN 0 AND 5 THEN 'pp'
                 ELSE 'death' END as phase,
            COUNT(*) as balls,
            SUM(d.runs_total) as runs,
            SUM(CASE WHEN d.wicket_kind IS NOT NULL
                THEN 1 ELSE 0 END) as wkts
        FROM deliveries d
        JOIN innings i ON d.innings_id = i.id
        JOIN matches m ON d.match_id = m.id
        WHERE m.event_name = ?
          AND i.bowling_team IN ({placeholders})
          AND d.over_number NOT BETWEEN 6 AND 14
          AND m.season >= ?
        GROUP BY 1
    """, [_EVENT, *names, season_filter]).fetchall()

    for phase, balls, runs in bat_rows:
        if balls and balls > 0:
            stats[f"{phase}_bat_sr"] = round(runs / balls * 100, 1)

    for phase, balls, runs, wkts in bowl_rows:
        if balls and balls > 0:
            overs = balls / 6
            stats[f"{phase}_bowl_econ"] = round(runs / overs, 2)

    return stats


def _query_phase_stats(match: ScheduleMatch) -> dict[str, dict]:
    """Query Cricsheet for team-level powerplay and death overs stats.

    Returns {team_short: {pp_bat_sr, ..., since, season: {pp_bat_sr, ...}}}
    with post-auction baseline and current-season overlay.
    """
    current_season = match.date[:4] if match.date else "2026"
    result: dict[str, dict] = {}
    try:
        conn = duckdb.connect(str(CRICKET_DB_PATH), read_only=True)

        for fid in (match.team1, match.team2):
            names = _cricsheet_names(fid)
            if not names:
                continue
            short = _short(fid)

            # Post-auction baseline
            stats = _query_phase_for_scope(conn, names, MEGA_AUCTION_SEASON)
            if stats:
                stats["since"] = MEGA_AUCTION_SEASON

            # Current-season overlay (only if we have data)
            szn = _query_phase_for_scope(conn, names, current_season)
            if szn:
                # Count completed matches this season for label
                match_count = conn.execute(f"""
                    SELECT COUNT(*) FROM matches
                    WHERE event_name = ?
                      AND season = ?
                      AND outcome_winner IS NOT NULL
                      AND (team1 IN ({", ".join(["?"] * len(names))})
                           OR team2 IN ({", ".join(["?"] * len(names))}))
                """, [_EVENT, current_season, *names, *names]).fetchone()
                szn["matches"] = match_count[0] if match_count else 0

                # Find the latest match number for "till M#" label
                last_match = conn.execute(f"""
                    SELECT MAX(m.event_match_number) FROM matches m
                    WHERE m.event_name = ?
                      AND m.season = ?
                      AND m.outcome_winner IS NOT NULL
                      AND (m.team1 IN ({", ".join(["?"] * len(names))})
                           OR m.team2 IN ({", ".join(["?"] * len(names))}))
                """, [_EVENT, current_season, *names, *names]).fetchone()
                if last_match and last_match[0]:
                    szn["till_match"] = last_match[0]

                stats["season"] = szn

            if stats:
                result[short] = stats

        conn.close()
    except Exception as e:
        console.print(f"  [yellow]Phase stats query failed: {e}[/yellow]")

    return result


def _query_venue_stats(match: ScheduleMatch) -> dict:
    """Query Cricsheet for rich venue statistics.

    Returns a structured dict with authoritative numbers — NOT LLM-generated.
    These are injected into the briefing JSON post-LLM.
    """
    city = match.city or match.venue.split(",")[0]
    venue_name = match.venue.split(",")[0].strip()
    stats: dict[str, Any] = {
        "name": venue_name,
        "city": city,
    }

    try:
        conn = duckdb.connect(str(CRICKET_DB_PATH), read_only=True)

        # ── Core averages (from innings join) ──
        row = conn.execute("""
            SELECT
                COUNT(DISTINCT m.id) as matches,
                ROUND(AVG(CASE WHEN i.innings_number = 1
                          THEN i.total_runs END), 0) as avg_1st,
                ROUND(AVG(CASE WHEN i.innings_number = 2
                          THEN i.total_runs END), 0) as avg_2nd,
                MAX(CASE WHEN i.innings_number = 1
                    THEN i.total_runs END) as highest_1st,
                MIN(CASE WHEN i.innings_number = 1
                    THEN i.total_runs END) as lowest_1st
            FROM matches m
            JOIN innings i ON i.match_id = m.id
            WHERE m.event_name = ?
              AND m.city LIKE ?
              AND i.innings_number <= 2
              AND m.outcome_winner IS NOT NULL
        """, [_EVENT, f"%{city}%"]).fetchone()

        if row and row[0] > 0:
            matches = row[0]
            stats["matches"] = matches
            stats["avg_1st_inn"] = int(row[1] or 0)
            stats["avg_2nd_inn"] = int(row[2] or 0)
            stats["highest"] = int(row[3] or 0)
            stats["lowest"] = int(row[4] or 0)

        # ── Toss data (from matches only, no innings join) ──
        toss_row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN toss_decision = 'field'
                    THEN 1 ELSE 0 END) as chose_field
            FROM matches
            WHERE event_name = ?
              AND city LIKE ?
              AND outcome_winner IS NOT NULL
        """, [_EVENT, f"%{city}%"]).fetchone()

        if toss_row and toss_row[0] > 0:
            stats["toss_field_pct"] = round(
                (toss_row[1] or 0) / toss_row[0] * 100
            )

        # ── Chase win % ──
        chase_row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN m.outcome_winner != i.batting_team
                    THEN 1 ELSE 0 END) as chase_wins
            FROM matches m
            JOIN innings i ON i.match_id = m.id
            WHERE m.event_name = ?
              AND m.city LIKE ?
              AND i.innings_number = 1
              AND m.outcome_winner IS NOT NULL
        """, [_EVENT, f"%{city}%"]).fetchone()

        if chase_row and chase_row[0] > 0:
            stats["chase_win_pct"] = round(
                (chase_row[1] or 0) / chase_row[0] * 100
            )

        # ── Powerplay avg score at venue ──
        pp_query = """
            SELECT COUNT(*), ROUND(AVG(pp_runs), 0)
            FROM (
                SELECT SUM(d.runs_total) as pp_runs
                FROM deliveries d
                JOIN innings i ON d.innings_id = i.id
                JOIN matches m ON d.match_id = m.id
                WHERE m.event_name = ?
                  AND m.city LIKE ?
                  AND d.over_number BETWEEN 0 AND 5
                  AND m.outcome_winner IS NOT NULL
                  {season_filter}
                GROUP BY d.match_id, i.innings_number
            )
        """
        # Since 2023 (recent era baseline)
        pp_recent = conn.execute(
            pp_query.format(season_filter="AND m.season >= '2023'"),
            [_EVENT, f"%{city}%"],
        ).fetchone()
        if pp_recent and pp_recent[0] and pp_recent[0] >= 6:
            stats["avg_pp_score"] = int(pp_recent[1])

        # ── Recent era (last 3 seasons) ──
        recent_row = conn.execute("""
            SELECT
                COUNT(DISTINCT m.id) as matches,
                ROUND(AVG(CASE WHEN i.innings_number = 1
                          THEN i.total_runs END), 0) as avg_1st,
                ROUND(AVG(CASE WHEN i.innings_number = 2
                          THEN i.total_runs END), 0) as avg_2nd
            FROM matches m
            JOIN innings i ON i.match_id = m.id
            WHERE m.event_name = ?
              AND m.city LIKE ?
              AND i.innings_number <= 2
              AND m.outcome_winner IS NOT NULL
              AND m.season >= '2023'
        """, [_EVENT, f"%{city}%"]).fetchone()

        if recent_row and (recent_row[0] or 0) >= 6:
            stats["avg_1st_inn_recent"] = int(recent_row[1] or 0)
            stats["avg_2nd_inn_recent"] = int(recent_row[2] or 0)

        # ── Defend thresholds ──
        defend_rows = conn.execute("""
            SELECT
                CASE
                    WHEN i.total_runs >= 180 THEN '180+'
                    WHEN i.total_runs >= 160 THEN '160-179'
                    ELSE 'under_160'
                END as band,
                COUNT(*) as attempts,
                SUM(CASE WHEN m.outcome_winner = i.batting_team
                    THEN 1 ELSE 0 END) as defended
            FROM innings i
            JOIN matches m ON i.match_id = m.id
            WHERE m.event_name = ?
              AND m.city LIKE ?
              AND i.innings_number = 1
              AND m.outcome_winner IS NOT NULL
            GROUP BY 1
        """, [_EVENT, f"%{city}%"]).fetchall()

        for band, attempts, defended in defend_rows:
            pct = round((defended or 0) / attempts * 100) if attempts else 0
            if band == "180+":
                stats["defend_180_pct"] = pct
            elif band == "160-179":
                stats["defend_160_pct"] = pct
            else:
                stats["defend_under_160_pct"] = pct

        # ── Last 5 first-innings scores ──
        recent_scores = conn.execute("""
            SELECT i.total_runs
            FROM innings i
            JOIN matches m ON i.match_id = m.id
            WHERE m.event_name = ?
              AND m.city LIKE ?
              AND i.innings_number = 1
            ORDER BY m.start_date DESC
            LIMIT 5
        """, [_EVENT, f"%{city}%"]).fetchall()

        if recent_scores:
            stats["last_5_1st_inn"] = [int(r[0]) for r in recent_scores]

        # ── Last 5 second-innings scores ──
        recent_2nd = conn.execute("""
            SELECT i.total_runs
            FROM innings i
            JOIN matches m ON i.match_id = m.id
            WHERE m.event_name = ?
              AND m.city LIKE ?
              AND i.innings_number = 2
            ORDER BY m.start_date DESC
            LIMIT 5
        """, [_EVENT, f"%{city}%"]).fetchall()

        if recent_2nd:
            stats["last_5_2nd_inn"] = [int(r[0]) for r in recent_2nd]

        # ── Team records at this venue ──
        team_records: dict[str, dict] = {}
        for fid in (match.team1, match.team2):
            names = _cricsheet_names(fid)
            if not names:
                continue
            placeholders = ", ".join(["?"] * len(names))
            tr = conn.execute(f"""
                SELECT
                    COUNT(*) as played,
                    SUM(CASE WHEN outcome_winner IN ({placeholders})
                        THEN 1 ELSE 0 END) as wins
                FROM matches
                WHERE event_name = ?
                  AND city LIKE ?
                  AND outcome_winner IS NOT NULL
                  AND (team1 IN ({placeholders}) OR team2 IN ({placeholders}))
            """, [*names, _EVENT, f"%{city}%", *names, *names]).fetchone()

            if tr and tr[0] > 0:
                team_records[_short(fid)] = {
                    "played": tr[0],
                    "wins": tr[1],
                    "losses": tr[0] - tr[1],
                }
        if team_records:
            stats["team_records"] = team_records

        # ── Player records at this venue (from current squads) ──
        player_stats = _query_player_venue_stats(conn, match, city)
        if player_stats:
            stats["player_venue_stats"] = player_stats

        conn.close()
    except Exception as e:
        console.print(f"  [yellow]Venue stats query failed: {e}[/yellow]")

    return stats


def _query_player_venue_stats(
    conn: duckdb.DuckDBPyConnection,
    match: ScheduleMatch,
    city: str,
) -> list[dict]:
    """Query per-player batting/bowling stats at this venue.

    Returns top 2 batters (by runs) + top 1 bowler (by wickets) per team,
    filtered to current season squads. Min 3 innings at venue.
    """
    from pipeline.db.connection import get_connection

    # Get squad names from enrichment DB (separate connection)
    try:
        econn = get_connection()
        squad_map = _get_squad_names_for_match(econn, match, "2026")
    except Exception:
        return []

    if not squad_map:
        return []

    # Build surname → (squad_name, team_short) index
    surname_to_squad: dict[str, tuple[str, str]] = {}
    for team_short, names in squad_map.items():
        for name in names:
            surname = name.split()[-1].lower()
            # Avoid collisions — first match wins (rare for same venue)
            if surname not in surname_to_squad:
                surname_to_squad[surname] = (name, team_short)

    city_pattern = f"%{city}%"
    results: list[dict] = []

    # ── Batting at venue ──
    bat_rows = conn.execute("""
        SELECT p.name,
               COUNT(*) as innings,
               SUM(bs.runs) as runs,
               ROUND(AVG(bs.runs), 1) as avg,
               ROUND(
                   SUM(bs.runs)::FLOAT
                   / NULLIF(SUM(bs.balls_faced), 0) * 100, 1
               ) as sr,
               MAX(bs.runs) as highest
        FROM batting_scorecard bs
        JOIN players p ON bs.player_id = p.id
        JOIN matches m ON bs.match_id = m.id
        WHERE m.event_name = ?
          AND m.city LIKE ?
        GROUP BY p.id, p.name
        HAVING COUNT(*) >= 3
        ORDER BY SUM(bs.runs) DESC
    """, [_EVENT, city_pattern]).fetchall()

    # Match Cricsheet names to squad by surname
    seen_players: set[str] = set()  # track squad names already used
    team_bat_count: dict[str, int] = {}
    for name, innings, runs, avg, sr, highest in bat_rows:
        surname = name.split()[-1].lower()
        if surname not in surname_to_squad:
            continue
        squad_name, team_short = surname_to_squad[surname]
        if squad_name in seen_players:
            continue
        if team_bat_count.get(team_short, 0) >= 2:
            continue
        seen_players.add(squad_name)
        team_bat_count[team_short] = team_bat_count.get(team_short, 0) + 1
        results.append({
            "player": squad_name,
            "team": team_short,
            "type": "bat",
            "matches": innings,
            "runs": int(runs),
            "avg": round(float(avg), 1) if avg else 0,
            "sr": round(float(sr), 1) if sr else 0,
            "highest": int(highest),
        })

    # ── Bowling at venue ──
    bowl_rows = conn.execute("""
        SELECT p.name,
               COUNT(*) as innings,
               SUM(bs.wickets) as wickets,
               ROUND(
                   SUM(bs.runs_conceded)::FLOAT
                   / NULLIF(SUM(bs.overs), 0), 2
               ) as econ
        FROM bowling_scorecard bs
        JOIN players p ON bs.player_id = p.id
        JOIN matches m ON bs.match_id = m.id
        WHERE m.event_name = ?
          AND m.city LIKE ?
        GROUP BY p.id, p.name
        HAVING COUNT(*) >= 3
        ORDER BY SUM(bs.wickets) DESC
    """, [_EVENT, city_pattern]).fetchall()

    team_bowl_count: dict[str, int] = {}
    for name, innings, wickets, econ in bowl_rows:
        surname = name.split()[-1].lower()
        if surname not in surname_to_squad:
            continue
        squad_name, team_short = surname_to_squad[surname]
        if squad_name in seen_players:
            continue
        if team_bowl_count.get(team_short, 0) >= 1:
            continue
        seen_players.add(squad_name)
        team_bowl_count[team_short] = team_bowl_count.get(team_short, 0) + 1
        results.append({
            "player": squad_name,
            "team": team_short,
            "type": "bowl",
            "matches": innings,
            "wickets": int(wickets),
            "econ": round(float(econ), 2) if econ else 0,
        })

    return results


def _build_venue_context(venue_stats: dict) -> str:
    """Format venue stats as text context for the LLM prompt."""
    parts: list[str] = []
    name = venue_stats.get("name", "Unknown")
    city = venue_stats.get("city", "")
    matches = venue_stats.get("matches", 0)

    parts.append(f"VENUE ({name}, {city}): {matches} IPL matches.")

    avg_1st = venue_stats.get("avg_1st_inn")
    avg_recent = venue_stats.get("avg_1st_inn_recent")
    if avg_1st:
        line = f"  Par score (1st innings): {avg_1st} all-time"
        if avg_recent and abs(avg_recent - avg_1st) >= 10:
            line += f", {avg_recent} recent (2023-26)"
        parts.append(line)

    chase = venue_stats.get("chase_win_pct")
    toss = venue_stats.get("toss_field_pct")
    if chase:
        parts.append(f"  Chase win rate: {chase}%.")
    if toss:
        parts.append(f"  Toss winners choose to field: {toss}%.")

    d180 = venue_stats.get("defend_180_pct")
    d160 = venue_stats.get("defend_160_pct")
    d_under = venue_stats.get("defend_under_160_pct")
    if d180 is not None:
        parts.append(
            f"  Defend thresholds: 180+ defended {d180}%,"
            f" 160-179 defended {d160}%,"
            f" under 160 defended {d_under}%."
        )

    last5 = venue_stats.get("last_5_1st_inn")
    if last5:
        parts.append(f"  Last 5 first-innings scores: {', '.join(map(str, last5))}.")

    # Player records at this venue (from squad members)
    pvs = venue_stats.get("player_venue_stats", [])
    if pvs:
        lines = ["PLAYER RECORDS AT THIS VENUE:"]
        for p in pvs:
            if p["type"] == "bat":
                lines.append(
                    f"  {p['player']} ({p['team']}): {p['matches']} inn,"
                    f" {p['runs']} runs, avg {p['avg']}, SR {p['sr']},"
                    f" HS {p['highest']}"
                )
            else:
                lines.append(
                    f"  {p['player']} ({p['team']}): {p['matches']} inn,"
                    f" {p['wickets']} wkts, econ {p['econ']}"
                )
        parts.append("\n".join(lines))

    return "\n".join(parts)


def _query_h2h(match: ScheduleMatch) -> dict:
    """Query Cricsheet for franchise H2H (all name variants)."""
    names1 = _cricsheet_names(match.team1)
    names2 = _cricsheet_names(match.team2)
    if not names1 or not names2:
        return {"total": 0, f"{_short(match.team1)}_wins": 0, f"{_short(match.team2)}_wins": 0}

    try:
        conn = duckdb.connect(str(CRICKET_DB_PATH), read_only=True)
        ph1 = ", ".join(["?"] * len(names1))
        ph2 = ", ".join(["?"] * len(names2))
        rows = conn.execute(f"""
            SELECT outcome_winner, COUNT(*) as cnt
            FROM matches
            WHERE event_name = ?
              AND ((team1 IN ({ph1}) AND team2 IN ({ph2}))
                   OR (team1 IN ({ph2}) AND team2 IN ({ph1})))
              AND outcome_winner IS NOT NULL
            GROUP BY outcome_winner
        """, [_EVENT, *names1, *names2, *names2, *names1]).fetchall()
        conn.close()

        from pipeline.sources.cricsheet import _CRICSHEET_TO_FID

        wins: dict[str, int] = {}
        for r in rows:
            fid = _CRICSHEET_TO_FID.get(r[0], "")
            if fid:
                wins[fid] = wins.get(fid, 0) + r[1]

        w1 = wins.get(match.team1, 0)
        w2 = wins.get(match.team2, 0)
        s1 = _short(match.team1)
        s2 = _short(match.team2)
        return {"total": w1 + w2, f"{s1}_wins": w1, f"{s2}_wins": w2}
    except Exception:
        return {"total": 0, f"{_short(match.team1)}_wins": 0, f"{_short(match.team2)}_wins": 0}


def _build_h2h_context(match: ScheduleMatch) -> str:
    """Build H2H text context for LLM prompt."""
    h2h = _query_h2h(match)
    s1 = _short(match.team1)
    s2 = _short(match.team2)
    w1 = h2h.get(f"{s1}_wins", 0)
    w2 = h2h.get(f"{s2}_wins", 0)
    if w1 + w2 == 0:
        return f"ALL-TIME H2H: {s1} and {s2} have never met."
    return f"ALL-TIME H2H: {s1} {w1} - {w2} {s2}"


def _build_form_context(match: ScheduleMatch) -> str:
    """Build current-season context from synced data (text for LLM)."""
    parts: list[str] = []

    standings = _load_json("standings.json") or []
    schedule = _load_json("schedule.json") or []

    for fid in (match.team1, match.team2):
        s = next(
            (s for s in standings if s["franchise_id"] == fid),
            None,
        )
        if s:
            team_matches = [
                m for m in schedule
                if m.get("status") == "completed"
                and (m["team1"] == fid or m["team2"] == fid)
            ]
            form = "".join(
                "W" if m.get("winner") == fid
                else ("NR" if m.get("winner") is None else "L")
                for m in team_matches[-5:]
            )
            parts.append(
                f"{_short(fid)}: {s['wins']}W {s['losses']}L"
                f" NRR={s['nrr']} (#{s['position']})"
                f" Form: {form or 'N/A'}"
            )

    return "\n".join(parts)


def _get_structured_form(match: ScheduleMatch) -> dict[str, dict]:
    """Extract structured form data from standings/schedule (not LLM).

    Returns dict keyed by team short name with authoritative numbers.
    """
    standings = _load_json("standings.json") or []
    schedule = _load_json("schedule.json") or []
    result: dict[str, dict] = {}

    for fid in (match.team1, match.team2):
        short = _short(fid)
        s = next(
            (s for s in standings if s["franchise_id"] == fid),
            None,
        )
        if not s:
            continue

        team_matches = [
            m for m in schedule
            if m.get("status") == "completed"
            and (m["team1"] == fid or m["team2"] == fid)
        ]
        last5 = [
            "W" if m.get("winner") == fid
            else ("NR" if m.get("winner") is None else "L")
            for m in team_matches[-5:]
        ]

        result[short] = {
            "wins": s["wins"],
            "losses": s["losses"],
            "nrr": s["nrr"],
            "position": s["position"],
            "last5": last5,
        }

    return result


def _inject_post_llm(
    parsed: dict,
    match: ScheduleMatch,
    venue_stats: dict,
) -> dict:
    """Enrich LLM response with authoritative source data.

    Numbers from Cricsheet/standings override any LLM-generated values.
    LLM-generated narratives (trend, venue note, h2h note) are preserved.
    """
    # ── Match metadata (from ScheduleMatch, not LLM) ──
    parsed["team1_id"] = match.team1
    parsed["team2_id"] = match.team2
    parsed["date"] = match.date
    parsed["time"] = match.time
    parsed["match_number"] = match.match_number

    # ── Venue stats (from Cricsheet queries, not LLM) ──
    venue_note = parsed.pop("venue_note", None)
    parsed.pop("venue_profile", None)
    venue_stats["note"] = venue_note or ""
    parsed["venue_stats"] = venue_stats

    # ── H2H (from Cricsheet queries, note from LLM) ──
    h2h = _query_h2h(match)
    llm_h2h = parsed.get("h2h", {})
    h2h["note"] = llm_h2h.get("note", "") if isinstance(llm_h2h, dict) else ""
    parsed["h2h"] = h2h

    # ── Form data (structured from standings, trend from LLM) ──
    structured_form = _get_structured_form(match)
    llm_form = parsed.get("form", {})
    for short, data in structured_form.items():
        llm_entry = llm_form.get(short, {})
        data["trend"] = llm_entry.get("trend", "")
        llm_form[short] = data
    parsed["form"] = llm_form

    # ── Phase stats (from Cricsheet, not LLM) ──
    parsed["phase_stats"] = _query_phase_stats(match)

    return parsed


def _build_espn_context(match: ScheduleMatch) -> str:
    """Build ESPNcricinfo article context from intel-log.json (title + URL)."""
    log_path = DATA_DIR / "war-room" / "intel-log.json"
    if not log_path.exists():
        return ""
    items = json.loads(log_path.read_text(encoding="utf-8"))
    t1, t2 = match.team1, match.team2
    relevant = []
    for item in items:
        if item.get("source") != "espncricinfo":
            continue
        teams = set(item.get("teams", []))
        if t1 in teams or t2 in teams:
            relevant.append(f"- [{item['title']}]({item['url']})")
        if len(relevant) >= 8:
            break
    return "\n".join(relevant) if relevant else ""


def _get_squad_names_for_match(
    conn: duckdb.DuckDBPyConnection,
    match: ScheduleMatch,
    season: str,
) -> dict[str, list[str]]:
    """Get player names per team for the current season.

    Uses the existing connection (enrichment.duckdb with cricket ATTACHed).
    Returns {team_short: [player names]} for both teams in the match.
    """
    result: dict[str, list[str]] = {}
    try:
        year = int(season.split("/")[0]) if "/" in season else int(season)
        for fid in (match.team1, match.team2):
            rows = conn.execute("""
                SELECT player_name
                FROM ipl_season_squad
                WHERE franchise_id = ? AND season = ?
            """, [fid, year]).fetchall()
            result[_short(fid)] = [r[0] for r in rows]
    except Exception as e:
        console.print(
            f"  [dim]Briefing: season XI lookup failed: {e}[/dim]"
        )
    return result


_SYSTEM_PROMPT = load_prompt("briefing_system.md")
_USER_PROMPT = load_prompt("briefing_user.md")


async def generate_briefing(
    conn: duckdb.DuckDBPyConnection,
    season: str,
    match: ScheduleMatch,
) -> dict | None:
    """Generate a pre-match intel brief for a specific fixture."""
    cache = LLMCache()
    cache_key = (
        f"brief_v2_{match.team1}_{match.team2}_{match.date}"
    )

    # Query venue stats upfront (needed for both cache hit + miss)
    venue_stats = _query_venue_stats(match)

    cached = cache.get(_CACHE_TASK, cache_key)
    if cached and cached.get("parsed"):
        console.print(
            f"  [dim]Briefing: cache hit"
            f" ({_short(match.team1)} vs"
            f" {_short(match.team2)})[/dim]"
        )
        # Re-inject source data even on cache hit (standings may have changed)
        return _inject_post_llm(cached["parsed"], match, venue_stats)

    # Build context for LLM
    venue_context = _build_venue_context(venue_stats)
    h2h_context = _build_h2h_context(match)
    form_context = _build_form_context(match)
    articles_context = retrieve_for_match(
        conn, match.team1, match.team2, match.date,
        max_articles=5, max_chars_per_article=500,
    ) or "(No recent articles)"

    # Supplement with ESPNcricinfo articles from intel-log (title + URL only)
    espn_context = _build_espn_context(match)

    # Full squad context for both teams (from ipl_season_squad)
    try:
        from pipeline.intel.roster_context import for_match

        squad_context = for_match(conn, season, match.team1, match.team2)
    except Exception:
        # Fallback to season XI names
        squad_map = _get_squad_names_for_match(conn, match, season)
        squad_lines: list[str] = []
        for short, names in squad_map.items():
            if names:
                squad_lines.append(f"{short}: {', '.join(names)}")
        squad_context = "\n".join(squad_lines) or "(not available)"

    # LLM call
    from pipeline.config import GEMINI_MODEL_PRO
    from pipeline.llm.gemini import GeminiProvider

    provider = GeminiProvider(model=GEMINI_MODEL_PRO)
    prompt = _USER_PROMPT.format(
        team1=_short(match.team1),
        team2=_short(match.team2),
        team1_short=_short(match.team1),
        team2_short=_short(match.team2),
        date=match.date,
        time=match.time,
        venue=match.venue,
        city=match.city,
        venue_context=venue_context,
        h2h_context=h2h_context,
        form_context=form_context,
        squad_context=squad_context,
        articles_context=articles_context,
        espn_context=espn_context or "(No ESPNcricinfo articles)",
    )

    result = await provider.generate_with_tools(
        prompt,
        system=_SYSTEM_PROMPT,
        tools=get_tool_declarations(),
        tool_executor=execute_tool,
        temperature=0.5,
    )

    parsed = result.get("parsed")
    if not parsed:
        text = result.get("text", "").strip()
        if text.startswith("```"):
            text = re.sub(r"```(?:json)?\n?", "", text).strip()
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                try:
                    parsed = json.loads(m.group())
                except (json.JSONDecodeError, ValueError):
                    pass

    if not parsed:
        console.print(
            "  [yellow]Briefing: failed to parse"
            " LLM response[/yellow]"
        )
        return None

    # Inject authoritative source data over LLM output
    parsed = _inject_post_llm(parsed, match, venue_stats)

    cache.put(_CACHE_TASK, cache_key, {
        "parsed": parsed,
        "usage": result.get("usage", {}),
    })

    console.print(
        f"  [green]Briefing: {_short(match.team1)} vs"
        f" {_short(match.team2)} generated[/green]"
    )
    return parsed
