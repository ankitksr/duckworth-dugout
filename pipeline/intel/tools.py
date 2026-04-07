"""Cricket analysis tools for LLM function calling.

Exposes a focused set of Cricsheet queries as Gemini function declarations.
The LLM can call these during briefing/dossier generation to gather
matchup-specific data it finds relevant — filling gaps that pre-canned
queries miss.

Each tool is a (declaration, implementation) pair. Declarations use the
google-genai types; implementations run SQL against cricket.duckdb.
"""

from typing import Any

import duckdb
from rich.console import Console

from pipeline.config import CRICKET_DB_PATH

console = Console()

_EVENT = "Indian Premier League"


def _connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(CRICKET_DB_PATH), read_only=True)


# ── Tool implementations ────────────────────────────────────────────


def get_batter_vs_bowler(batter: str, bowler: str) -> dict[str, Any]:
    """How has a specific batter performed against a specific bowler in IPL?"""
    try:
        conn = _connect()
        row = conn.execute("""
            SELECT
                COUNT(*) as balls,
                SUM(CASE WHEN d.batter_runs > 0 THEN d.batter_runs ELSE 0 END) as runs,
                SUM(CASE WHEN d.is_wicket AND d.player_dismissed = d.batter
                    THEN 1 ELSE 0 END) as dismissals,
                SUM(d.batter_runs = 4) as fours,
                SUM(d.batter_runs = 6) as sixes
            FROM deliveries d
            JOIN players pb ON d.batter_id = pb.id
            JOIN players pw ON d.bowler_id = pw.id
            JOIN matches m ON d.match_id = m.id
            WHERE m.event_name = ?
              AND pb.name LIKE ?
              AND pw.name LIKE ?
        """, [_EVENT, f"%{batter}%", f"%{bowler}%"]).fetchone()
        conn.close()

        if not row or row[0] == 0:
            return {"result": f"No IPL data found for {batter} vs {bowler}"}

        balls, runs, dismissals, fours, sixes = row
        sr = round(runs / balls * 100, 1) if balls else 0
        return {
            "batter": batter,
            "bowler": bowler,
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
                    SUM(d.total_runs) as runs,
                    SUM(CASE WHEN d.is_wicket THEN 1 ELSE 0 END) as wickets
                FROM deliveries d
                JOIN players p ON d.bowler_id = p.id
                JOIN matches m ON d.match_id = m.id
                WHERE m.event_name = ?
                  AND p.name LIKE ?
                GROUP BY 1
                ORDER BY 1
            """, [_EVENT, f"%{player}%"]).fetchall()

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
                    SUM(d.batter_runs) as runs,
                    SUM(d.batter_runs = 4) as fours,
                    SUM(d.batter_runs = 6) as sixes
                FROM deliveries d
                JOIN players p ON d.batter_id = p.id
                JOIN matches m ON d.match_id = m.id
                WHERE m.event_name = ?
                  AND p.name LIKE ?
                GROUP BY 1
                ORDER BY 1
            """, [_EVENT, f"%{player}%"]).fetchall()

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


# ── Tool registry ───────────────────────────────────────────────────

# Maps tool name → implementation function
TOOL_REGISTRY: dict[str, Any] = {
    "get_batter_vs_bowler": get_batter_vs_bowler,
    "get_phase_stats": get_phase_stats,
    "get_recent_h2h": get_recent_h2h,
}


def get_tool_declarations() -> list:
    """Build Gemini function declarations for all registered tools."""
    from google.genai import types

    return [
        types.Tool(function_declarations=[
            types.FunctionDeclaration(
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
            types.FunctionDeclaration(
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
            types.FunctionDeclaration(
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
        ]),
    ]


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
