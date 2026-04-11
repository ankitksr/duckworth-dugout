"""Direct Cricsheet queries for War Room fallback data.

Queries cricket.duckdb (via duckworth-mcp's ATTACH pattern) for standings,
cap race, and completed match results. No dependency on campaign pipeline.
"""

import duckdb
from rich.console import Console

from pipeline.config import CRICKET_DB_PATH
from pipeline.db.connection import connect_readonly
from pipeline.ipl.franchise_metadata import IPL_FRANCHISES
from pipeline.models import CapEntry, CapsData, StandingsRow

console = Console()

_EVENT = "Indian Premier League"

# Reverse lookups
_CRICSHEET_TO_FID: dict[str, str] = {}
for _fid, _fdata in IPL_FRANCHISES.items():
    if _fdata.get("defunct"):
        continue
    for _name in _fdata["cricsheet_names"]:
        _CRICSHEET_TO_FID[_name] = _fid


def _fid(cricsheet_name: str) -> str:
    return _CRICSHEET_TO_FID.get(cricsheet_name, "")


def _short(fid: str) -> str:
    return IPL_FRANCHISES.get(fid, {}).get("short_name", fid.upper())


def _color(fid: str) -> str:
    """War-room-optimized color for dark backgrounds. Falls back to primary_color."""
    fdata = IPL_FRANCHISES.get(fid, {})
    return fdata.get("war_room_color", fdata.get("primary_color", "#888"))


def _connect() -> duckdb.DuckDBPyConnection:
    return connect_readonly(CRICKET_DB_PATH)


def _db_available() -> bool:
    """True if cricket.duckdb exists on disk.

    Live-update workflows don't restore the cricsheet cache (it's
    ~500MB) so any caller that goes through Cricsheet must be able
    to degrade gracefully when the file isn't there. Helpers below
    short-circuit on this check and return empty results so callers
    fall back to schedule-derived data instead of crashing.
    """
    from pathlib import Path
    return Path(CRICKET_DB_PATH).exists()


def _parse_overs(overs: float | None) -> float:
    """Convert overs (e.g. 19.4) to balls, then back to decimal overs for NRR.

    IPL overs are stored as e.g. 19.4 meaning 19 overs 4 balls = 19.667 overs.
    """
    if overs is None:
        return 0.0
    whole = int(overs)
    balls = round((overs - whole) * 10)
    return whole + balls / 6.0


def query_standings(season: str) -> list[StandingsRow] | None:
    """Compute standings with NRR from Cricsheet match + innings data."""
    conn = _connect()
    try:
        rows = conn.execute("""
            SELECT
                m.outcome_winner, m.team1, m.team2, m.outcome_result,
                i1.batting_team, i1.total_runs, i1.total_overs,
                i2.batting_team, i2.total_runs, i2.total_overs
            FROM matches m
            LEFT JOIN innings i1 ON i1.match_id = m.id AND i1.innings_number = 1
            LEFT JOIN innings i2 ON i2.match_id = m.id AND i2.innings_number = 2
            WHERE m.event_name = ? AND m.season = ?
              AND m.event_stage IS NULL
            ORDER BY m.start_date
        """, [_EVENT, season]).fetchall()
    finally:
        conn.close()

    if not rows:
        return None

    # Per-team accumulators: W/L/NR + runs scored/faced and overs for NRR
    teams: dict[str, dict] = {}
    for fid, fdata in IPL_FRANCHISES.items():
        if fdata.get("defunct"):
            continue
        teams[fid] = {
            "w": 0, "l": 0, "nr": 0, "played": 0,
            "runs_for": 0.0, "overs_for": 0.0,
            "runs_against": 0.0, "overs_against": 0.0,
        }

    for (winner, t1, t2, result,
         inn1_team, inn1_runs, inn1_overs,
         inn2_team, inn2_runs, inn2_overs) in rows:
        f1, f2 = _fid(t1), _fid(t2)
        if not f1 or not f2:
            continue
        for f in (f1, f2):
            if f in teams:
                teams[f]["played"] += 1

        if result == "no result":
            for f in (f1, f2):
                if f in teams:
                    teams[f]["nr"] += 1
        elif winner:
            fw = _fid(winner)
            fl = f2 if fw == f1 else f1
            if fw in teams:
                teams[fw]["w"] += 1
            if fl in teams:
                teams[fl]["l"] += 1

        # Accumulate runs/overs for NRR
        if inn1_runs is not None and inn1_overs is not None:
            f_bat1 = _fid(inn1_team) if inn1_team else None
            f_bowl1 = f2 if f_bat1 == f1 else f1
            ov1 = _parse_overs(inn1_overs)
            if f_bat1 and f_bat1 in teams:
                teams[f_bat1]["runs_for"] += inn1_runs
                teams[f_bat1]["overs_for"] += ov1
            if f_bowl1 and f_bowl1 in teams:
                teams[f_bowl1]["runs_against"] += inn1_runs
                teams[f_bowl1]["overs_against"] += ov1

        if inn2_runs is not None and inn2_overs is not None:
            f_bat2 = _fid(inn2_team) if inn2_team else None
            f_bowl2 = f2 if f_bat2 == f1 else f1
            ov2 = _parse_overs(inn2_overs)
            if f_bat2 and f_bat2 in teams:
                teams[f_bat2]["runs_for"] += inn2_runs
                teams[f_bat2]["overs_for"] += ov2
            if f_bowl2 and f_bowl2 in teams:
                teams[f_bowl2]["runs_against"] += inn2_runs
                teams[f_bowl2]["overs_against"] += ov2

    # Compute NRR: (runs_for / overs_for) - (runs_against / overs_against)
    def _nrr(t: dict) -> float | None:
        if t["overs_for"] == 0 or t["overs_against"] == 0:
            return None
        return (t["runs_for"] / t["overs_for"]) - (t["runs_against"] / t["overs_against"])

    # Sort by points desc, then NRR desc
    played = [(fid, t) for fid, t in teams.items() if t["played"] > 0]
    played.sort(key=lambda x: (-(x[1]["w"] * 2 + x[1]["nr"]), -(_nrr(x[1]) or -999)))
    unplayed = [(fid, t) for fid, t in teams.items() if t["played"] == 0]
    ranked = played + unplayed

    result_rows = []
    for i, (fid, t) in enumerate(ranked, 1):
        pts = t["w"] * 2 + t["nr"]
        nrr = _nrr(t)
        nrr_str = f"{nrr:+.3f}" if nrr is not None else "-"
        result_rows.append(StandingsRow(
            franchise_id=fid,
            short_name=_short(fid),
            primary_color=_color(fid),
            played=t["played"],
            wins=t["w"],
            losses=t["l"],
            no_results=t["nr"],
            points=pts,
            nrr=nrr_str,
            position=i,
            qualified=i <= 4,
        ))

    console.print(f"  [yellow]Standings fallback: {len(result_rows)} teams from Cricsheet[/yellow]")
    return result_rows


def query_caps(season: str, top_n: int = 10) -> CapsData:
    """Query top run-scorers and wicket-takers from Cricsheet scorecards."""
    conn = _connect()
    try:
        batters = conn.execute("""
            SELECT p.name, i.batting_team, SUM(bs.runs) as total_runs
            FROM batting_scorecard bs
            JOIN players p ON bs.player_id = p.id
            JOIN matches m ON bs.match_id = m.id
            JOIN innings i ON i.match_id = m.id AND bs.innings_id = i.id
            WHERE m.event_name = ? AND m.season = ?
            GROUP BY p.name, i.batting_team
            ORDER BY total_runs DESC
            LIMIT ?
        """, [_EVENT, season, top_n]).fetchall()

        bowlers = conn.execute("""
            SELECT p.name, i.bowling_team, SUM(bs.wickets) as total_wkts
            FROM bowling_scorecard bs
            JOIN players p ON bs.player_id = p.id
            JOIN matches m ON bs.match_id = m.id
            JOIN innings i ON i.match_id = m.id AND bs.innings_id = i.id
            WHERE m.event_name = ? AND m.season = ?
            GROUP BY p.name, i.bowling_team
            ORDER BY total_wkts DESC
            LIMIT ?
        """, [_EVENT, season, top_n]).fetchall()
    finally:
        conn.close()

    orange = [
        CapEntry(
            rank=i + 1,
            player=name,
            team=_fid(team),
            team_short=_short(_fid(team)),
            stat=f"{runs} runs",
        )
        for i, (name, team, runs) in enumerate(batters)
    ]

    purple = [
        CapEntry(
            rank=i + 1,
            player=name,
            team=_fid(team),
            team_short=_short(_fid(team)),
            stat=f"{wkts} wkts",
        )
        for i, (name, team, wkts) in enumerate(bowlers)
    ]

    # Best strike rate (min 30 balls faced)
    conn2 = _connect()
    try:
        sr_rows = conn2.execute("""
            SELECT p.name, i.batting_team,
                   ROUND(SUM(bs.runs)::FLOAT / NULLIF(SUM(bs.balls_faced), 0) * 100, 1) as sr,
                   SUM(bs.runs) as runs, SUM(bs.balls_faced) as balls
            FROM batting_scorecard bs
            JOIN players p ON bs.player_id = p.id
            JOIN matches m ON bs.match_id = m.id
            JOIN innings i ON i.match_id = m.id AND bs.innings_id = i.id
            WHERE m.event_name = ? AND m.season = ?
            GROUP BY p.name, i.batting_team
            HAVING SUM(bs.balls_faced) >= 30
            ORDER BY sr DESC
            LIMIT ?
        """, [_EVENT, season, top_n]).fetchall()

        econ_rows = conn2.execute("""
            SELECT p.name, i.bowling_team,
                   ROUND(SUM(bs.runs_conceded)::FLOAT / NULLIF(SUM(bs.overs), 0), 2) as econ,
                   SUM(bs.wickets) as wkts, SUM(bs.overs) as overs
            FROM bowling_scorecard bs
            JOIN players p ON bs.player_id = p.id
            JOIN matches m ON bs.match_id = m.id
            JOIN innings i ON i.match_id = m.id AND bs.innings_id = i.id
            WHERE m.event_name = ? AND m.season = ?
            GROUP BY p.name, i.bowling_team
            HAVING SUM(bs.overs) >= 2
            ORDER BY econ ASC
            LIMIT ?
        """, [_EVENT, season, top_n]).fetchall()
    finally:
        conn2.close()

    best_sr = [
        CapEntry(
            rank=i + 1,
            player=name,
            team=_fid(team),
            team_short=_short(_fid(team)),
            stat=f"{sr:.2f}",
        )
        for i, (name, team, sr, runs, balls) in enumerate(sr_rows)
    ]

    best_econ = [
        CapEntry(
            rank=i + 1,
            player=name,
            team=_fid(team),
            team_short=_short(_fid(team)),
            stat=f"{econ:.2f}",
        )
        for i, (name, team, econ, wkts, overs) in enumerate(econ_rows)
    ]

    total = len(orange) + len(purple) + len(best_sr) + len(best_econ)
    if total:
        console.print(
            f"  [yellow]Caps fallback: {len(orange)} Orange, {len(purple)} Purple, "
            f"{len(best_sr)} SR, {len(best_econ)} Econ from Cricsheet[/yellow]"
        )

    # Use actual latest match date as the "updated" timestamp
    try:
        conn3 = _connect()
        try:
            latest = conn3.execute(
                "SELECT MAX(start_date) FROM matches"
                " WHERE event_name = ? AND season = ?",
                [_EVENT, season],
            ).fetchone()
            updated = str(latest[0]) if latest and latest[0] else None
        finally:
            conn3.close()
    except Exception:
        updated = None
    if not updated:
        from datetime import datetime, timezone
        updated = datetime.now(timezone.utc).isoformat()

    return CapsData(
        orange_cap=orange, purple_cap=purple,
        best_sr=best_sr, best_econ=best_econ,
        updated=updated,
    )


def query_completed_matches(season: str) -> dict[tuple[str, str, str], dict]:
    """Query completed match results from Cricsheet.

    Returns dict keyed by (date, sorted_team1, sorted_team2) → result info.
    Returns empty dict if cricket.duckdb is not present (live-update path).
    """
    if not _db_available():
        return {}
    conn = _connect()
    try:
        rows = conn.execute("""
            SELECT m.start_date, m.team1, m.team2,
                   m.outcome_winner, m.outcome_by_type, m.outcome_by_amount,
                   m.outcome_result, m.player_of_match,
                   i1.total_runs AS t1_runs, i1.total_wickets AS t1_wkts,
                   i1.total_overs AS t1_overs,
                   i2.total_runs AS t2_runs, i2.total_wickets AS t2_wkts,
                   i2.total_overs AS t2_overs
            FROM matches m
            LEFT JOIN innings i1 ON i1.match_id = m.id AND i1.innings_number = 1
            LEFT JOIN innings i2 ON i2.match_id = m.id AND i2.innings_number = 2
            WHERE m.event_name = ? AND m.season = ?
            ORDER BY m.start_date
        """, [_EVENT, season]).fetchall()
    finally:
        conn.close()

    completed: dict[tuple[str, str, str], dict] = {}
    for (date, t1, t2, winner, by_type, by_amount, result,
         potm, t1_runs, t1_wkts, t1_overs, t2_runs, t2_wkts, t2_overs) in rows:

        f1, f2 = _fid(t1), _fid(t2)
        if not f1 or not f2:
            continue

        date_str = str(date)
        k1, k2 = sorted([f1, f2])
        key = (date_str, k1, k2)

        # Format scores
        score1 = f"{t1_runs}/{t1_wkts}" if t1_runs is not None else None
        score2 = f"{t2_runs}/{t2_wkts}" if t2_runs is not None else None

        # Result text
        fw = _fid(winner) if winner else None
        result_text = ""
        if fw and by_amount:
            result_text = f"{_short(fw)} won by {by_amount} {by_type}"
        elif result == "no result":
            result_text = "No result"

        completed[key] = {
            "f1": f1, "f2": f2,
            "score_f1": score1, "score_f2": score2,
            "winner": fw,
            "result_text": result_text,
            "potm": potm,
        }

    return completed


def _query_cricsheet_innings(season: str) -> dict[tuple[str, str], dict]:
    """Fetch per-match innings data from Cricsheet for NRR computation.

    Returns a dict keyed by (date, frozenset(fid1, fid2)) → innings data.
    Returns empty dict if cricket.duckdb is not present so callers
    fall back to schedule-derived NRR.
    """
    if not _db_available():
        return {}
    conn = _connect()
    try:
        rows = conn.execute("""
            SELECT m.start_date, m.team1, m.team2,
                   i1.batting_team, i1.total_runs, i1.total_overs,
                   i2.batting_team, i2.total_runs, i2.total_overs
            FROM matches m
            LEFT JOIN innings i1 ON i1.match_id = m.id AND i1.innings_number = 1
            LEFT JOIN innings i2 ON i2.match_id = m.id AND i2.innings_number = 2
            WHERE m.event_name = ? AND m.season = ?
              AND m.event_stage IS NULL
            ORDER BY m.start_date, m.event_match_number
        """, [_EVENT, season]).fetchall()
    finally:
        conn.close()

    result: dict[tuple[str, str], dict] = {}
    for (start_date, t1, t2,
         inn1_team, inn1_runs, inn1_overs,
         inn2_team, inn2_runs, inn2_overs) in rows:
        f1, f2 = _fid(t1), _fid(t2)
        if not f1 or not f2:
            continue
        pair = "_".join(sorted([f1, f2]))
        key = (str(start_date), pair)
        result[key] = {
            "innings": [
                (f_bat, inn_runs, inn_overs)
                for f_bat_name, inn_runs, inn_overs in [
                    (inn1_team, inn1_runs, inn1_overs),
                    (inn2_team, inn2_runs, inn2_overs),
                ]
                if inn_runs is not None and inn_overs is not None
                and (f_bat := _fid(f_bat_name or ""))
            ],
            "f1": f1,
            "f2": f2,
        }
    return result


def _parse_schedule_score(score: str | None) -> int | None:
    """Parse schedule score like '162/6' or '160' → runs (162 or 160)."""
    if not score:
        return None
    try:
        return int(score.split("/")[0])
    except (ValueError, IndexError):
        return None


def _parse_schedule_overs(overs: str | None) -> float:
    """Parse schedule overs like '18.4 ov' or '20' → decimal overs."""
    if not overs:
        return 0.0
    cleaned = overs.replace("ov", "").strip()
    try:
        return _parse_overs(float(cleaned))
    except (ValueError, TypeError):
        return 0.0


def build_pulse_from_schedule(
    schedule: list[dict],
    standings: list[dict] | None,
    season: str,
) -> list[dict]:
    """Build Season Pulse (Rank River) from the fused schedule.

    Primary data source is the schedule (which already merges Cricsheet +
    standings + live RSS + LLM extraction). Cricsheet innings are used
    for accurate NRR where available; schedule scores fill the gap for
    matches Cricsheet hasn't ingested yet.

    Returns a list of per-team dicts with the same shape as the old
    query_pulse output.
    """
    # Load Cricsheet innings for NRR computation
    cs_innings = _query_cricsheet_innings(season)

    # Build standings lookup for final NRR / position
    std_by_fid: dict[str, dict] = {}
    if standings:
        for row in standings:
            fid = row.get("franchise_id", "")
            if fid:
                std_by_fid[fid] = row

    # Initialize all teams
    teams: dict[str, dict] = {}
    for fid, fdata in IPL_FRANCHISES.items():
        if fdata.get("defunct"):
            continue
        teams[fid] = {
            "w": 0, "l": 0, "nr": 0, "played": 0,
            "runs_for": 0.0, "overs_for": 0.0,
            "runs_against": 0.0, "overs_against": 0.0,
            "snapshots": [],
        }

    match_num_per_team: dict[str, int] = {}

    # Iterate completed matches in fixture order
    completed = [
        m for m in schedule
        if m.get("status") == "completed"
    ]
    # Sort by match_number to ensure correct chronological order
    completed.sort(key=lambda m: m.get("match_number", 0))

    for match in completed:
        f1, f2 = match["team1"], match["team2"]
        if f1 not in teams or f2 not in teams:
            continue

        winner = match.get("winner")
        match_date = match["date"]

        # Update W/L/NR
        for f in (f1, f2):
            teams[f]["played"] += 1
        if not winner:
            # No result
            for f in (f1, f2):
                teams[f]["nr"] += 1
            r1, r2 = "NR", "NR"
        else:
            loser = f2 if winner == f1 else f1
            teams[winner]["w"] += 1
            teams[loser]["l"] += 1
            r1 = "W" if f1 == winner else "L"
            r2 = "W" if f2 == winner else "L"

        # Update NRR accumulators — prefer Cricsheet, fall back to schedule
        pair = "_".join(sorted([f1, f2]))
        cs_key = (match_date, pair)
        cs_data = cs_innings.get(cs_key)

        if cs_data and cs_data["innings"]:
            # Cricsheet innings — accurate
            for f_bat, inn_runs, inn_overs in cs_data["innings"]:
                f_bowl = f2 if f_bat == f1 else f1
                ov = _parse_overs(inn_overs)
                if f_bat in teams:
                    teams[f_bat]["runs_for"] += inn_runs
                    teams[f_bat]["overs_for"] += ov
                if f_bowl in teams:
                    teams[f_bowl]["runs_against"] += inn_runs
                    teams[f_bowl]["overs_against"] += ov
        else:
            # Fall back to schedule scores (from live RSS / LLM extraction)
            runs1 = _parse_schedule_score(match.get("score1"))
            runs2 = _parse_schedule_score(match.get("score2"))
            overs1 = _parse_schedule_overs(match.get("overs1"))
            overs2 = _parse_schedule_overs(match.get("overs2"))

            if runs1 is not None and overs1 > 0:
                teams[f1]["runs_for"] += runs1
                teams[f1]["overs_for"] += overs1
                teams[f2]["runs_against"] += runs1
                teams[f2]["overs_against"] += overs1
            if runs2 is not None and overs2 > 0:
                teams[f2]["runs_for"] += runs2
                teams[f2]["overs_for"] += overs2
                teams[f1]["runs_against"] += runs2
                teams[f1]["overs_against"] += overs2

        # Compute current standings (all teams, sorted by pts then NRR)
        def _nrr(t: dict) -> float:
            if t["overs_for"] == 0 or t["overs_against"] == 0:
                return 0.0
            return (t["runs_for"] / t["overs_for"]) - (
                t["runs_against"] / t["overs_against"]
            )

        ranking = sorted(
            teams.keys(),
            key=lambda fid: (
                -(teams[fid]["w"] * 2 + teams[fid]["nr"]),
                -_nrr(teams[fid]),
                fid,
            ),
        )
        rank_map = {fid: i + 1 for i, fid in enumerate(ranking)}

        # Record snapshot for both teams
        for f, res in [(f1, r1), (f2, r2)]:
            match_num_per_team[f] = match_num_per_team.get(f, 0) + 1
            t = teams[f]
            t["snapshots"].append({
                "match": match_num_per_team[f],
                "date": match_date,
                "result": res,
                "rank": rank_map[f],
                "points": t["w"] * 2 + t["nr"],
                "nrr": round(_nrr(t), 3),
            })

    # Build output — use standings for final NRR/rank where available
    def _final_nrr(t: dict) -> float:
        if t["overs_for"] == 0 or t["overs_against"] == 0:
            return 0.0
        return (t["runs_for"] / t["overs_for"]) - (
            t["runs_against"] / t["overs_against"]
        )

    # Final ranking: prefer standings position, fall back to computed
    if std_by_fid:
        final_ranking = sorted(
            teams.keys(),
            key=lambda fid: std_by_fid.get(fid, {}).get(
                "position", 99
            ),
        )
    else:
        final_ranking = sorted(
            teams.keys(),
            key=lambda fid: (
                -(teams[fid]["w"] * 2 + teams[fid]["nr"]),
                -_final_nrr(teams[fid]),
                fid,
            ),
        )

    result_list = []
    for i, fid in enumerate(final_ranking):
        fdata = IPL_FRANCHISES.get(fid, {})
        t = teams[fid]
        # Prefer standings NRR (authoritative) over computed
        std_row = std_by_fid.get(fid)
        if std_row:
            nrr_str = std_row["nrr"]
            current_rank = std_row["position"]
            points = std_row["points"]
        else:
            nrr = _final_nrr(t)
            nrr_str = f"{nrr:+.3f}" if t["played"] > 0 else "-"
            current_rank = i + 1
            points = t["w"] * 2 + t["nr"]

        result_list.append({
            "fid": fid,
            "short": fdata.get("short_name", fid.upper()),
            "color": _color(fid),
            "current_rank": current_rank,
            "points": points,
            "nrr": nrr_str,
            "played": t["played"],
            "snapshots": t["snapshots"],
        })

    # Sort by current_rank
    result_list.sort(key=lambda e: e["current_rank"])

    console.print(
        f"  [green]Pulse: {len(completed)} schedule matches,"
        f" {len(cs_innings)} from Cricsheet,"
        f" {len(result_list)} teams[/green]"
    )
    return result_list
