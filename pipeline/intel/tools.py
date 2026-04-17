"""Cricket analysis tools for LLM function calling.

Exposes a focused set of queries as Gemini function declarations. Tools
fall into three categories:

1. **Cricsheet tools** — career/all-time IPL stats from cricket.duckdb
2. **JSON tools** — instant lookups against synced war-room JSON files
3. **Enrichment tools** — squad/article data from enrichment.duckdb

Each tool is a (declaration, implementation) pair. Declarations use the
google-genai types; implementations run SQL or read JSON.
"""

import json
from typing import Any

import duckdb
from rich.console import Console

from pipeline.config import CRICKET_DB_PATH, DATA_DIR
from pipeline.db.connection import connect_readonly
from pipeline.ipl.franchise_metadata import IPL_FRANCHISES

console = Console()

_EVENT = "Indian Premier League"

_SHORT = {fid: d["short_name"] for fid, d in IPL_FRANCHISES.items() if not d.get("defunct")}


def _connect() -> duckdb.DuckDBPyConnection:
    return connect_readonly(CRICKET_DB_PATH)


def _player_like(name: str) -> str:
    """Build a LIKE pattern that matches Cricsheet's initial-based names.

    LLMs send full names ("Yashasvi Jaiswal") but Cricsheet stores
    "YBK Jaiswal". Matching on last name (+ optional first initial)
    handles both forms.
    """
    parts = name.strip().split()
    if len(parts) >= 2:
        # Use last name as primary match — covers "% Jaiswal" → "YBK Jaiswal"
        return f"% {parts[-1]}"
    return f"%{name.strip()}%"


def _load_json(filename: str) -> Any:
    path = DATA_DIR / "war-room" / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _fid_short(fid: str) -> str:
    return _SHORT.get(fid, fid.upper())


# Squad lookup — built lazily per process from ipl_season_squad. Used to stamp
# authoritative team tags onto every player name returned by the tools below,
# so downstream LLM generators can never re-attribute a performance by
# narrative inference (regression guard for the de Kock → PBKS hallucination).
_SQUAD_CACHE: dict[str, dict[str, str]] = {}


def _squad_map(season: str | None = None) -> dict[str, str]:
    """Return {lowercased player name → team short} for the given season.

    Uses the enrichment connection set by the wire orchestrator. Cached per
    season string. Returns an empty map if the connection isn't set (tools
    called outside the wire flow) — callers must treat a missing entry as
    "team unknown" and fall back gracefully.
    """
    key = season or "current"
    if key in _SQUAD_CACHE:
        return _SQUAD_CACHE[key]
    out: dict[str, str] = {}
    if _enrichment_conn is None:
        return out
    try:
        sql = "SELECT franchise_id, player_name FROM ipl_season_squad"
        params: list = []
        if season:
            sql += " WHERE season = ?"
            params.append(int(season))
        rows = _enrichment_conn.execute(sql, params).fetchall()
        for fid, name in rows:
            short = _SHORT.get(fid)
            if short and name:
                out[name.lower()] = short
    except Exception:
        pass
    _SQUAD_CACHE[key] = out
    return out


def _player_team(name: str, squad_map: dict[str, str]) -> str | None:
    """Resolve a player's team short from the squad map. Tries full name then
    surname-only match. Returns None if the name isn't in any seeded squad
    (mid-season signings — caller should degrade gracefully)."""
    if not name:
        return None
    hit = squad_map.get(name.lower())
    if hit:
        return hit
    parts = name.split()
    if len(parts) >= 2:
        last = parts[-1].lower()
        matches = [v for k, v in squad_map.items() if k.split()[-1:] == [last]]
        if len(matches) == 1:
            return matches[0]
    return None


def _utc_iso(value: object) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        text = value.isoformat()
        return text.replace("+00:00", "Z")
    return str(value)


# ── Tool implementations ────────────────────────────────────────────


def get_batter_vs_bowler(batter: str, bowler: str) -> dict[str, Any]:
    """How has a specific batter performed against a specific bowler in IPL?"""
    try:
        conn = _connect()
        row = conn.execute("""
            SELECT
                COUNT(*) as balls,
                SUM(d.runs_batter) as runs,
                SUM(CASE WHEN d.wicket_kind IS NOT NULL AND d.wicket_player_out = d.batter
                    THEN 1 ELSE 0 END) as dismissals,
                SUM(CASE WHEN d.runs_batter = 4 THEN 1 ELSE 0 END) as fours,
                SUM(CASE WHEN d.runs_batter = 6 THEN 1 ELSE 0 END) as sixes
            FROM deliveries d
            JOIN players pb ON d.batter_id = pb.id
            JOIN players pw ON d.bowler_id = pw.id
            JOIN matches m ON d.match_id = m.id
            WHERE m.event_name = ?
              AND pb.name LIKE ?
              AND pw.name LIKE ?
        """, [_EVENT, _player_like(batter), _player_like(bowler)]).fetchone()
        conn.close()

        if not row or row[0] == 0:
            return {"result": f"No IPL data found for {batter} vs {bowler}"}

        balls, runs, dismissals, fours, sixes = row
        sr = round(runs / balls * 100, 1) if balls else 0
        squad = _squad_map()
        return {
            "batter": batter,
            "batter_team": _player_team(batter, squad) or "unknown",
            "bowler": bowler,
            "bowler_team": _player_team(bowler, squad) or "unknown",
            "balls": balls,
            "runs": runs,
            "dismissals": dismissals,
            "strike_rate": sr,
            "fours": fours,
            "sixes": sixes,
            "summary": (
                f"{batter} has scored {runs} off {balls} balls vs {bowler} "
                f"(SR {sr}, dismissed {dismissals} times)"
            ),
        }
    except Exception as e:
        return {"error": str(e)}


def get_phase_stats(player: str, role: str = "bat") -> dict[str, Any]:
    """Get a player's IPL stats split by phase: powerplay (1-6), middle (7-15), death (16-20)."""
    try:
        conn = _connect()

        if role == "bowl":
            rows = conn.execute("""
                SELECT
                    CASE
                        WHEN d.over_number BETWEEN 0 AND 5 THEN 'powerplay'
                        WHEN d.over_number BETWEEN 6 AND 14 THEN 'middle'
                        ELSE 'death'
                    END as phase,
                    COUNT(*) as balls,
                    SUM(d.runs_total) as runs,
                    SUM(CASE WHEN d.wicket_kind IS NOT NULL THEN 1 ELSE 0 END) as wickets
                FROM deliveries d
                JOIN players p ON d.bowler_id = p.id
                JOIN matches m ON d.match_id = m.id
                WHERE m.event_name = ?
                  AND p.name LIKE ?
                GROUP BY 1
                ORDER BY 1
            """, [_EVENT, _player_like(player)]).fetchall()

            if not rows:
                conn.close()
                return {"result": f"No IPL bowling data for {player}"}

            phases = {}
            for phase, balls, runs, wkts in rows:
                overs = balls / 6
                econ = round(runs / overs, 2) if overs else 0
                phases[phase] = {
                    "balls": balls,
                    "runs_conceded": runs,
                    "wickets": wkts,
                    "economy": econ,
                }
            conn.close()
            return {"player": player, "role": "bowler", "phases": phases}

        else:
            rows = conn.execute("""
                SELECT
                    CASE
                        WHEN d.over_number BETWEEN 0 AND 5 THEN 'powerplay'
                        WHEN d.over_number BETWEEN 6 AND 14 THEN 'middle'
                        ELSE 'death'
                    END as phase,
                    COUNT(*) as balls,
                    SUM(d.runs_batter) as runs,
                    SUM(CASE WHEN d.runs_batter = 4 THEN 1 ELSE 0 END) as fours,
                    SUM(CASE WHEN d.runs_batter = 6 THEN 1 ELSE 0 END) as sixes
                FROM deliveries d
                JOIN players p ON d.batter_id = p.id
                JOIN matches m ON d.match_id = m.id
                WHERE m.event_name = ?
                  AND p.name LIKE ?
                GROUP BY 1
                ORDER BY 1
            """, [_EVENT, _player_like(player)]).fetchall()

            if not rows:
                conn.close()
                return {"result": f"No IPL batting data for {player}"}

            phases = {}
            for phase, balls, runs, fours, sixes in rows:
                sr = round(runs / balls * 100, 1) if balls else 0
                phases[phase] = {
                    "balls": balls,
                    "runs": runs,
                    "strike_rate": sr,
                    "fours": fours,
                    "sixes": sixes,
                }
            conn.close()
            return {"player": player, "role": "batter", "phases": phases}

    except Exception as e:
        return {"error": str(e)}


def get_recent_h2h(
    team1: str, team2: str, last_n: int = 5,
) -> dict[str, Any]:
    """Get recent head-to-head results between two IPL teams."""
    try:
        from pipeline.sources.cricsheet import _CRICSHEET_TO_FID

        fid_to_name = {v: k for k, v in _CRICSHEET_TO_FID.items()}

        # Try to resolve franchise IDs or short names to Cricsheet names
        n1 = fid_to_name.get(team1.lower())
        n2 = fid_to_name.get(team2.lower())
        if not n1 or not n2:
            # Try as Cricsheet names directly
            n1 = n1 or team1
            n2 = n2 or team2

        conn = _connect()
        rows = conn.execute("""
            SELECT start_date, team1, team2, outcome_winner,
                   outcome_result, outcome_by_runs, outcome_by_wickets,
                   venue, city
            FROM matches
            WHERE event_name = ?
              AND ((team1 = ? AND team2 = ?)
                   OR (team1 = ? AND team2 = ?))
              AND outcome_winner IS NOT NULL
            ORDER BY start_date DESC
            LIMIT ?
        """, [_EVENT, n1, n2, n2, n1, last_n]).fetchall()
        conn.close()

        if not rows:
            return {"result": f"No H2H data for {team1} vs {team2}"}

        matches = []
        for date, t1, t2, winner, res, by_runs, by_wkts, venue, city in rows:
            margin = (
                f"by {by_runs} runs" if by_runs
                else f"by {by_wkts} wickets" if by_wkts
                else res or ""
            )
            w_fid = _CRICSHEET_TO_FID.get(winner, winner)
            matches.append({
                "date": str(date),
                "winner": w_fid,
                "margin": margin,
                "venue": city or venue,
            })

        return {
            "team1": team1,
            "team2": team2,
            "last_n": len(matches),
            "matches": matches,
        }
    except Exception as e:
        return {"error": str(e)}


# ── JSON-based tools (instant, from synced war-room files) ─────────


def get_team_results(team: str, last_n: int = 5) -> dict[str, Any]:
    """Get a team's recent match results with scores and top performers."""
    schedule = _load_json("schedule.json")
    if not schedule:
        return {"error": "No schedule data available"}

    fid = team.strip().lower()
    completed = [
        m for m in schedule
        if m.get("status") == "completed"
        and fid in (m.get("team1", ""), m.get("team2", ""))
    ]
    recent = completed[-last_n:]
    if not recent:
        return {"result": f"No completed matches found for {team}"}

    matches = []
    for m in recent:
        entry: dict[str, Any] = {
            "match_number": m.get("match_number"),
            "date": m.get("date"),
            "opponent": (
                _fid_short(m["team2"]) if m.get("team1") == fid
                else _fid_short(m["team1"])
            ),
            "result": m.get("result", ""),
            "won": m.get("winner") == fid,
            "score1": f"{_fid_short(m['team1'])} {m.get('score1', '?')}",
            "score2": f"{_fid_short(m['team2'])} {m.get('score2', '?')}",
        }
        if m.get("toss"):
            entry["toss"] = m["toss"]
        # Top performers. Positional convention:
        #   top_batter1 → team1 (batted first), top_batter2 → team2
        #   top_bowler1 → team2 (bowled vs team1), top_bowler2 → team1
        # Team tag is authoritative via squad map; falls back to the positional
        # team short so mid-season signings still carry a tag.
        squad = _squad_map()
        pos = {
            "top_batter1": m.get("team1"),
            "top_batter2": m.get("team2"),
            "top_bowler1": m.get("team2"),
            "top_bowler2": m.get("team1"),
        }

        # Remember each performer's resolved team so the POTM line can inherit
        # it — critical for losing-cause POTMs whose hero_name isn't in the
        # seeded squad (e.g. mid-season signings like de Kock).
        local: dict[str, str] = {}
        for key in ("top_batter1", "top_batter2", "top_bowler1", "top_bowler2"):
            perf = m.get(key)
            if perf and perf.get("name"):
                resolved = (
                    _player_team(perf["name"], squad)
                    or (_fid_short(pos[key]) if pos[key] else None)
                )
                if resolved:
                    local[perf["name"].lower()] = resolved
                tag = f" ({resolved})" if resolved else ""
                if "batter" in key:
                    entry.setdefault("top_batters", []).append(
                        f"{perf['name']}{tag} {perf.get('runs', '?')}"
                        f"({perf.get('balls', '?')})"
                    )
                else:
                    entry.setdefault("top_bowlers", []).append(
                        f"{perf['name']}{tag} {perf.get('wickets', '?')}"
                        f"/{perf.get('runs', '?')}"
                    )
        if m.get("hero_name"):
            hero = m["hero_name"]
            hero_team = _player_team(hero, squad) or local.get(hero.lower())
            hero_tag = f" ({hero_team})" if hero_team else ""
            entry["potm"] = f"{hero}{hero_tag} {m.get('hero_stat', '')}"
        matches.append(entry)

    wins = sum(1 for m in matches if m["won"])
    return {
        "team": _fid_short(fid),
        "last_n": len(matches),
        "wins": wins,
        "losses": len(matches) - wins,
        "matches": matches,
    }


def get_remaining_schedule(team: str) -> dict[str, Any]:
    """Get a team's upcoming/remaining fixtures."""
    schedule = _load_json("schedule.json")
    if not schedule:
        return {"error": "No schedule data available"}

    fid = team.strip().lower()
    upcoming = [
        m for m in schedule
        if m.get("status") in ("scheduled", "live")
        and fid in (m.get("team1", ""), m.get("team2", ""))
    ]
    if not upcoming:
        return {"result": f"No upcoming fixtures for {team}"}

    fixtures = []
    for m in upcoming:
        opponent = (
            _fid_short(m["team2"]) if m.get("team1") == fid
            else _fid_short(m["team1"])
        )
        fixtures.append({
            "match_number": m.get("match_number"),
            "date": m.get("date"),
            "opponent": opponent,
            "venue": m.get("venue", ""),
            "city": m.get("city", ""),
            "home": m.get("home_team") == fid,
        })

    return {
        "team": _fid_short(fid),
        "remaining_matches": len(fixtures),
        "fixtures": fixtures,
    }


def get_cap_leaders(category: str = "orange_cap", top_n: int = 5) -> dict[str, Any]:
    """Get current cap race leaders. Categories: orange_cap, purple_cap, best_sr, best_econ."""
    caps = _load_json("caps.json")
    if not caps:
        return {"error": "No cap race data available"}

    valid = {"orange_cap", "purple_cap", "best_sr", "best_econ"}
    cat = category.strip().lower()
    if cat not in valid:
        return {"error": f"Invalid category '{category}'. Use one of: {', '.join(sorted(valid))}"}

    entries = caps.get(cat, [])[:top_n]
    if not entries:
        return {"result": f"No entries for {category}"}

    return {
        "category": cat,
        "leaders": [
            {
                "rank": e.get("rank"),
                "player": e.get("player"),
                "team": e.get("team_short"),
                "stat": e.get("stat"),
            }
            for e in entries
        ],
    }


# ── Enrichment tools (from enrichment.duckdb) ────────────────────


# Enrichment DB connection — set by wire orchestrator before generation
_enrichment_conn: duckdb.DuckDBPyConnection | None = None


def set_enrichment_conn(conn: duckdb.DuckDBPyConnection) -> None:
    """Set the enrichment DB connection for tools that need it."""
    global _enrichment_conn
    _enrichment_conn = conn


def get_squad_detail(team: str) -> dict[str, Any]:
    """Get full roster for a team: players, prices, overseas status, captain, acquisition type."""
    if not _enrichment_conn:
        return {"error": "No enrichment DB connection"}

    fid = team.strip().lower()
    try:
        rows = _enrichment_conn.execute(
            """
            SELECT player_name, is_captain, is_overseas, price_inr, acquisition_type
            FROM ipl_season_squad
            WHERE franchise_id = ?
            ORDER BY price_inr DESC
            """,
            [fid],
        ).fetchall()
    except Exception as e:
        return {"error": str(e)}

    if not rows:
        return {"result": f"No squad data for {team}"}

    players = []
    for name, is_cap, is_ovs, price, acq in rows:
        entry: dict[str, Any] = {"name": name}
        if is_cap:
            entry["captain"] = True
        if is_ovs:
            entry["overseas"] = True
        if price:
            entry["price_cr"] = round(price / 1e7, 1)
        if acq:
            entry["acquisition"] = acq
        players.append(entry)

    return {
        "team": _fid_short(fid),
        "squad_size": len(players),
        "overseas_count": sum(1 for p in players if p.get("overseas")),
        "players": players,
    }


def search_articles(query: str, limit: int = 5) -> dict[str, Any]:
    """Search recent IPL articles by keyword. Returns title, source, excerpt."""
    if not _enrichment_conn:
        return {"error": "No enrichment DB connection"}

    try:
        rows = _enrichment_conn.execute(
            """
            SELECT source, title, coalesce(snippet, left(body, 300)) as excerpt,
                   published
            FROM war_room_articles
            WHERE is_ipl = TRUE
              AND (title ILIKE ? OR coalesce(snippet, body, '') ILIKE ?)
            ORDER BY published DESC
            LIMIT ?
            """,
            [f"%{query}%", f"%{query}%", limit],
        ).fetchall()
    except Exception as e:
        return {"error": str(e)}

    if not rows:
        return {"result": f"No articles matching '{query}'"}

    return {
        "query": query,
        "count": len(rows),
        "articles": [
            {
                "source": r[0],
                "title": r[1],
                "excerpt": (r[2] or "")[:400],
                "published": _utc_iso(r[3]),
            }
            for r in rows
        ],
    }


# ── Cricsheet tools — career + season stats ──────────────────────


def get_player_career_stats(player: str) -> dict[str, Any]:
    """Get a player's all-time IPL career stats, plus current-season breakdown with freshness date."""
    try:
        conn = _connect()

        result: dict[str, Any] = {"player": player, "scope": "all-time IPL career"}

        # Batting stats — career
        bat_row = conn.execute("""
            SELECT
                COUNT(DISTINCT bs.match_id) as innings,
                SUM(bs.runs) as runs,
                MAX(bs.runs) as highest,
                ROUND(AVG(bs.runs), 1) as avg,
                ROUND(AVG(bs.strike_rate), 1) as sr,
                SUM(bs.fours) as fours,
                SUM(bs.sixes) as sixes
            FROM batting_scorecard bs
            JOIN players p ON bs.player_id = p.id
            JOIN matches m ON bs.match_id = m.id
            WHERE m.event_name = ?
              AND p.name LIKE ?
        """, [_EVENT, _player_like(player)]).fetchone()

        if bat_row and bat_row[0] and bat_row[0] > 0:
            result["batting"] = {
                "innings": bat_row[0],
                "runs": bat_row[1],
                "highest": bat_row[2],
                "average": bat_row[3],
                "strike_rate": bat_row[4],
                "fours": bat_row[5],
                "sixes": bat_row[6],
            }

        # Bowling stats — career
        bowl_row = conn.execute("""
            SELECT
                COUNT(DISTINCT bw.match_id) as innings,
                SUM(bw.wickets) as wickets,
                SUM(bw.runs_conceded) as runs,
                ROUND(AVG(bw.economy), 2) as econ,
                MIN(CASE WHEN bw.wickets >= 1
                    THEN bw.wickets || '/' || bw.runs_conceded END) as best
            FROM bowling_scorecard bw
            JOIN players p ON bw.player_id = p.id
            JOIN matches m ON bw.match_id = m.id
            WHERE m.event_name = ?
              AND p.name LIKE ?
              AND bw.overs > 0
        """, [_EVENT, _player_like(player)]).fetchone()

        if bowl_row and bowl_row[0] and bowl_row[0] > 0:
            result["bowling"] = {
                "innings": bowl_row[0],
                "wickets": bowl_row[1],
                "runs_conceded": bowl_row[2],
                "economy": bowl_row[3],
                "best": bowl_row[4],
            }

        # Current season breakdown — with freshness marker
        # Find the latest season available
        latest = conn.execute("""
            SELECT MAX(m.season) FROM matches m WHERE m.event_name = ?
        """, [_EVENT]).fetchone()
        current_season = latest[0] if latest and latest[0] else None

        if current_season:
            # Get the latest match date in this season for the freshness marker
            freshness = conn.execute("""
                SELECT MAX(m.start_date)::VARCHAR
                FROM matches m
                WHERE m.event_name = ? AND m.season = ?
            """, [_EVENT, current_season]).fetchone()
            data_through = freshness[0] if freshness and freshness[0] else None

            season_bat = conn.execute("""
                SELECT
                    COUNT(DISTINCT bs.match_id) as innings,
                    SUM(bs.runs) as runs,
                    MAX(bs.runs) as highest,
                    ROUND(AVG(bs.runs), 1) as avg,
                    ROUND(AVG(bs.strike_rate), 1) as sr
                FROM batting_scorecard bs
                JOIN players p ON bs.player_id = p.id
                JOIN matches m ON bs.match_id = m.id
                WHERE m.event_name = ? AND m.season = ?
                  AND p.name LIKE ?
            """, [_EVENT, current_season, _player_like(player)]).fetchone()

            season_bowl = conn.execute("""
                SELECT
                    COUNT(DISTINCT bw.match_id) as innings,
                    SUM(bw.wickets) as wickets,
                    SUM(bw.runs_conceded) as runs,
                    ROUND(AVG(bw.economy), 2) as econ
                FROM bowling_scorecard bw
                JOIN players p ON bw.player_id = p.id
                JOIN matches m ON bw.match_id = m.id
                WHERE m.event_name = ? AND m.season = ?
                  AND p.name LIKE ?
                  AND bw.overs > 0
            """, [_EVENT, current_season, _player_like(player)]).fetchone()

            season: dict[str, Any] = {"season": current_season}
            if data_through:
                season["data_through"] = data_through
                season["note"] = (
                    f"Cricsheet data may lag 1-2 days. Stats are through {data_through}. "
                    "For the very latest, cross-reference with get_player_season_stats (RSS)."
                )
            if season_bat and season_bat[0] and season_bat[0] > 0:
                season["batting"] = {
                    "innings": season_bat[0],
                    "runs": season_bat[1],
                    "highest": season_bat[2],
                    "average": season_bat[3],
                    "strike_rate": season_bat[4],
                }
            if season_bowl and season_bowl[0] and season_bowl[0] > 0:
                season["bowling"] = {
                    "innings": season_bowl[0],
                    "wickets": season_bowl[1],
                    "runs_conceded": season_bowl[2],
                    "economy": season_bowl[3],
                }
            if "batting" in season or "bowling" in season:
                result["current_season"] = season

        conn.close()

        if "batting" not in result and "bowling" not in result and "current_season" not in result:
            return {"result": f"No career stats found for {player}"}

        return result
    except Exception as e:
        return {"error": str(e)}


# ── JSON-based tools — current season stats (from RSS, not Cricsheet) ─


def get_player_season_stats(player: str) -> dict[str, Any]:
    """Get a player's current-season stats aggregated from synced JSON (caps + scorecards)."""
    query = player.strip().lower()
    result: dict[str, Any] = {"player": player, "scope": "current season (from RSS feeds)"}

    # Check cap race standings
    caps = _load_json("caps.json")
    if caps:
        for key, label in [
            ("orange_cap", "Orange Cap (runs)"),
            ("purple_cap", "Purple Cap (wickets)"),
            ("best_sr", "Best Strike Rate"),
            ("best_econ", "Best Economy"),
        ]:
            for e in caps.get(key, []):
                name = (e.get("player") or "").lower()
                if query in name or name in query:
                    result.setdefault("cap_rankings", []).append({
                        "category": label,
                        "rank": e.get("rank"),
                        "stat": e.get("stat"),
                        "team": e.get("team_short"),
                    })

    # Aggregate from match scorecards (top performer entries)
    schedule = _load_json("schedule.json")
    if schedule:
        squad = _squad_map()
        batting_entries: list[dict[str, Any]] = []
        bowling_entries: list[dict[str, Any]] = []
        potm_count = 0
        player_team: str | None = None

        for m in schedule:
            if m.get("status") != "completed":
                continue
            mnum = m.get("match_number")
            pos = {
                "top_batter1": m.get("team1"),
                "top_batter2": m.get("team2"),
                "top_bowler1": m.get("team2"),
                "top_bowler2": m.get("team1"),
            }
            def _resolve(nm: str, fallback_fid: str | None) -> str:
                t = _player_team(nm, squad)
                if not t and fallback_fid:
                    t = _fid_short(fallback_fid)
                return t or "unknown"

            # Check top batters
            for bkey in ("top_batter1", "top_batter2"):
                tb = m.get(bkey)
                if tb and tb.get("name") and query in tb["name"].lower():
                    team = _resolve(tb["name"], pos[bkey])
                    if team != "unknown" and not player_team:
                        player_team = team
                    batting_entries.append({
                        "match": mnum,
                        "team": team,
                        "runs": tb.get("runs"),
                        "balls": tb.get("balls"),
                        "not_out": tb.get("not_out", False),
                    })
            # Check top bowlers
            for bkey in ("top_bowler1", "top_bowler2"):
                bw = m.get(bkey)
                if bw and bw.get("name") and query in bw["name"].lower():
                    team = _resolve(bw["name"], pos[bkey])
                    if team != "unknown" and not player_team:
                        player_team = team
                    bowling_entries.append({
                        "match": mnum,
                        "team": team,
                        "wickets": bw.get("wickets"),
                        "runs_conceded": bw.get("runs"),
                    })
            # POTM
            if m.get("hero_name") and query in m["hero_name"].lower():
                potm_count += 1

        if player_team:
            result["team"] = player_team

        if batting_entries:
            total_runs = sum(e["runs"] for e in batting_entries if e.get("runs"))
            result["batting_highlights"] = {
                "appearances_as_top_batter": len(batting_entries),
                "total_runs_in_highlights": total_runs,
                "entries": batting_entries,
            }
        if bowling_entries:
            total_wickets = sum(e["wickets"] for e in bowling_entries if e.get("wickets"))
            result["bowling_highlights"] = {
                "appearances_as_top_bowler": len(bowling_entries),
                "total_wickets_in_highlights": total_wickets,
                "entries": bowling_entries,
            }
        if potm_count:
            result["player_of_the_match_awards"] = potm_count

    if len(result) <= 2:  # only player + scope
        return {"result": f"No current-season data found for {player} in caps or scorecards"}

    return result


def get_venue_stats(city: str) -> dict[str, Any]:
    """Get IPL venue stats: average 1st innings score, chase win%, total matches."""
    try:
        conn = _connect()
        row = conn.execute("""
            SELECT
                ROUND(AVG(i1.total_runs), 1) as avg_first_innings,
                COUNT(*) as total_matches,
                SUM(CASE WHEN m.outcome_winner = i2.batting_team THEN 1 ELSE 0 END) as chase_wins,
                MAX(i1.total_runs) as highest_score,
                MIN(i1.total_runs) as lowest_score
            FROM matches m
            JOIN innings i1 ON i1.match_id = m.id AND i1.innings_number = 1
            JOIN innings i2 ON i2.match_id = m.id AND i2.innings_number = 2
            WHERE m.event_name = ? AND m.city ILIKE ?
              AND i1.total_runs IS NOT NULL AND i2.total_runs IS NOT NULL
              AND m.outcome_result IS DISTINCT FROM 'no result'
        """, [_EVENT, f"%{city}%"]).fetchone()
        conn.close()

        if not row or row[1] == 0:
            return {"result": f"No IPL venue data for {city}"}

        avg_score, total, chase_wins, highest, lowest = row
        chase_pct = round(chase_wins / total * 100) if total else 0
        return {
            "city": city,
            "total_matches": total,
            "avg_first_innings": avg_score,
            "chase_win_pct": chase_pct,
            "highest_score": highest,
            "lowest_score": lowest,
            "summary": (
                f"{city}: {total} IPL matches, avg 1st inn {avg_score}, "
                f"chase wins {chase_pct}% ({chase_wins}/{total})"
            ),
        }
    except Exception as e:
        return {"error": str(e)}


# ── Tool registry ───────────────────────────────────────────────────

# Maps tool name → implementation function
TOOL_REGISTRY: dict[str, Any] = {
    "get_batter_vs_bowler": get_batter_vs_bowler,
    "get_phase_stats": get_phase_stats,
    "get_recent_h2h": get_recent_h2h,
    "get_team_results": get_team_results,
    "get_remaining_schedule": get_remaining_schedule,
    "get_cap_leaders": get_cap_leaders,
    "get_squad_detail": get_squad_detail,
    "search_articles": search_articles,
    "get_player_career_stats": get_player_career_stats,
    "get_player_season_stats": get_player_season_stats,
    "get_venue_stats": get_venue_stats,
}


def get_tool_declarations(tool_names: list[str] | None = None) -> list:
    """Build Gemini function declarations for registered tools.

    Args:
        tool_names: If provided, only include these tools. Otherwise all tools.
    """
    from google.genai import types

    all_decls: dict[str, types.FunctionDeclaration] = {
        "get_batter_vs_bowler": types.FunctionDeclaration(
            name="get_batter_vs_bowler",
            description=(
                "Get how a specific batter has performed against a "
                "specific bowler in IPL history. Use for key matchup "
                "analysis — e.g. how does Kohli fare against Bumrah?"
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "batter": types.Schema(
                        type="STRING",
                        description="Batter's name (e.g. 'Virat Kohli')",
                    ),
                    "bowler": types.Schema(
                        type="STRING",
                        description="Bowler's name (e.g. 'Jasprit Bumrah')",
                    ),
                },
                required=["batter", "bowler"],
            ),
        ),
        "get_phase_stats": types.FunctionDeclaration(
            name="get_phase_stats",
            description=(
                "Get a player's IPL career stats split by match phase: "
                "powerplay (overs 1-6), middle (7-15), death (16-20). "
                "Useful for identifying phase-specific strengths or "
                "weaknesses in batting or bowling."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "player": types.Schema(
                        type="STRING",
                        description="Player's name (e.g. 'Rashid Khan')",
                    ),
                    "role": types.Schema(
                        type="STRING",
                        description="'bat' for batting stats, 'bowl' for bowling stats",
                        enum=["bat", "bowl"],
                    ),
                },
                required=["player", "role"],
            ),
        ),
        "get_recent_h2h": types.FunctionDeclaration(
            name="get_recent_h2h",
            description=(
                "Get the most recent head-to-head IPL match results "
                "between two teams, including venue and margin. Use "
                "franchise IDs (e.g. 'mi', 'csk') or full Cricsheet "
                "names."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "team1": types.Schema(
                        type="STRING",
                        description="First team (franchise ID like 'mi' or full name)",
                    ),
                    "team2": types.Schema(
                        type="STRING",
                        description="Second team",
                    ),
                    "last_n": types.Schema(
                        type="INTEGER",
                        description="Number of recent matches to return (default 5)",
                    ),
                },
                required=["team1", "team2"],
            ),
        ),
        "get_team_results": types.FunctionDeclaration(
            name="get_team_results",
            description=(
                "Get a team's recent match results with scores, top performers, "
                "and win/loss record. Use franchise ID (e.g. 'csk', 'mi')."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "team": types.Schema(
                        type="STRING",
                        description="Franchise ID (e.g. 'csk', 'mi', 'rcb')",
                    ),
                    "last_n": types.Schema(
                        type="INTEGER",
                        description="Number of recent matches (default 5)",
                    ),
                },
                required=["team"],
            ),
        ),
        "get_remaining_schedule": types.FunctionDeclaration(
            name="get_remaining_schedule",
            description=(
                "Get a team's remaining/upcoming fixtures with opponent, "
                "venue, and date. Use franchise ID."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "team": types.Schema(
                        type="STRING",
                        description="Franchise ID (e.g. 'csk', 'mi')",
                    ),
                },
                required=["team"],
            ),
        ),
        "get_cap_leaders": types.FunctionDeclaration(
            name="get_cap_leaders",
            description=(
                "Get current cap race leaders. Categories: 'orange_cap' "
                "(top run-scorers), 'purple_cap' (top wicket-takers), "
                "'best_sr' (best strike rate), 'best_econ' (best economy)."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "category": types.Schema(
                        type="STRING",
                        description="Cap category",
                        enum=["orange_cap", "purple_cap", "best_sr", "best_econ"],
                    ),
                    "top_n": types.Schema(
                        type="INTEGER",
                        description="Number of leaders to return (default 5)",
                    ),
                },
                required=["category"],
            ),
        ),
        "get_squad_detail": types.FunctionDeclaration(
            name="get_squad_detail",
            description=(
                "Get full squad roster for a team: player names, auction prices, "
                "overseas/captain status, acquisition type. Use franchise ID."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "team": types.Schema(
                        type="STRING",
                        description="Franchise ID (e.g. 'csk', 'mi')",
                    ),
                },
                required=["team"],
            ),
        ),
        "search_articles": types.FunctionDeclaration(
            name="search_articles",
            description=(
                "Search recent IPL news articles by keyword. Returns title, "
                "source, and excerpt. Use for injury news, team changes, "
                "or any breaking story you want to verify or react to."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(
                        type="STRING",
                        description="Search keyword (player name, team, topic)",
                    ),
                    "limit": types.Schema(
                        type="INTEGER",
                        description="Max articles to return (default 5)",
                    ),
                },
                required=["query"],
            ),
        ),
        "get_player_career_stats": types.FunctionDeclaration(
            name="get_player_career_stats",
            description=(
                "Get a player's all-time IPL career stats plus current-season "
                "breakdown (with freshness date). Batting: innings, runs, avg, "
                "SR, highest. Bowling: wickets, economy, best. Season data may "
                "lag 1-2 days — cross-reference with get_player_season_stats for latest."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "player": types.Schema(
                        type="STRING",
                        description="Player's name (e.g. 'Virat Kohli')",
                    ),
                },
                required=["player"],
            ),
        ),
        "get_player_season_stats": types.FunctionDeclaration(
            name="get_player_season_stats",
            description=(
                "Get a player's current-season stats from live RSS data: "
                "cap race rankings, match-by-match highlights as top batter/"
                "bowler, and Player of the Match awards. Use for current form."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "player": types.Schema(
                        type="STRING",
                        description="Player's name (e.g. 'Yashasvi Jaiswal')",
                    ),
                },
                required=["player"],
            ),
        ),
        "get_venue_stats": types.FunctionDeclaration(
            name="get_venue_stats",
            description=(
                "Get IPL venue stats for a city: average 1st innings score, "
                "chase win percentage, total matches, highest/lowest scores."
            ),
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "city": types.Schema(
                        type="STRING",
                        description="City name (e.g. 'Mumbai', 'Bengaluru', 'Guwahati')",
                    ),
                },
                required=["city"],
            ),
        ),
    }

    names = tool_names or list(all_decls.keys())
    decls = [all_decls[n] for n in names if n in all_decls]
    if not decls:
        return []
    return [types.Tool(function_declarations=decls)]


def execute_tool(name: str, args: dict) -> dict:
    """Execute a registered tool by name with given arguments."""
    func = TOOL_REGISTRY.get(name)
    if not func:
        return {"error": f"Unknown tool: {name}"}
    try:
        result = func(**args)
        args_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
        console.print(f"  [dim]Tool: {name}({args_str})[/dim]")
        return result
    except Exception as e:
        return {"error": f"Tool {name} failed: {e}"}
