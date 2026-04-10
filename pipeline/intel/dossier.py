"""Opposition Dossier — deep tactical breakdown of the opponent.

The "god mode" feature. Combines:
- Cricsheet historical data: career batting/bowling profiles, venue stats
- RSS current data: this season's form, squad news from articles store

Staleness: cached per matchup (team pair). Regenerated when match day changes.

Usage:
    dossier = await generate_dossier(conn, season, match, perspective_team)
"""

import json
import re
from typing import Any

import duckdb
from rich.console import Console

from pipeline.clock import today_ist_iso
from pipeline.config import CRICKET_DB_PATH, DATA_DIR
from pipeline.db.connection import connect_readonly
from pipeline.intel.articles import retrieve_summaries_for_team
from pipeline.intel.prompts import load_prompt
from pipeline.intel.tools import execute_tool, get_tool_declarations
from pipeline.ipl.franchise_metadata import IPL_FRANCHISES
from pipeline.llm.cache import LLMCache

console = Console()

_CACHE_TASK = "war_room_dossier"
_EVENT = "Indian Premier League"


def _short(fid: str) -> str:
    return IPL_FRANCHISES.get(fid, {}).get("short_name", fid.upper())


def _cricsheet_name(fid: str) -> str | None:
    """Get Cricsheet team name from franchise ID."""
    fdata = IPL_FRANCHISES.get(fid)
    if not fdata:
        return None
    names = fdata.get("cricsheet_names", [])
    return names[0] if names else None


def _load_json(filename: str) -> Any:
    path = DATA_DIR / "war-room" / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _get_current_squad(
    conn: duckdb.DuckDBPyConnection,
    franchise_id: str,
    season: str,
) -> tuple[set[str], list[str]]:
    """Get player IDs and names from ipl_season_squad for the current season.

    Uses the existing connection (enrichment.duckdb with cricket ATTACHed).
    Resolves names to Cricsheet player IDs via cricket.players join.
    Returns (set of player IDs, list of player names). Empty on failure.
    """
    try:
        year = int(season.split("/")[0]) if "/" in season else int(season)
        rows = conn.execute("""
            SELECT p.id, sq.player_name
            FROM ipl_season_squad sq
            JOIN cricket.players p ON p.name = sq.player_name
            WHERE sq.franchise_id = ? AND sq.season = ?
        """, [franchise_id, year]).fetchall()
        return ({r[0] for r in rows}, [r[1] for r in rows])
    except Exception as e:
        console.print(
            f"  [dim]Dossier: season XI lookup failed: {e}[/dim]"
        )
        return (set(), [])


def _query_team_batting_profile(
    opponent: str,
    venue_city: str,
    squad_ids: set[str] | None = None,
) -> str:
    """Query Cricsheet for batting profile of the opponent's current squad.

    When squad_ids is provided, queries career IPL stats across ALL teams
    (not just this franchise) — a traded player's full IPL career matters
    for scouting. Falls back to franchise-scoped query without squad_ids.
    """
    name = _cricsheet_name(opponent)
    if not name:
        return ""

    parts: list[str] = []
    try:
        conn = connect_readonly(CRICKET_DB_PATH)

        if squad_ids:
            # Squad-filtered: career IPL stats across all teams
            placeholders = ", ".join(["?"] * len(squad_ids))
            rows = conn.execute(f"""
                SELECT p.name,
                       SUM(bs.runs) as runs,
                       COUNT(*) as inns,
                       ROUND(AVG(bs.runs), 1) as avg,
                       ROUND(
                         SUM(bs.runs)::FLOAT
                         / NULLIF(SUM(bs.balls_faced), 0) * 100, 1
                       ) as sr,
                       SUM(bs.fours) as fours,
                       SUM(bs.sixes) as sixes
                FROM batting_scorecard bs
                JOIN players p ON bs.player_id = p.id
                JOIN matches m ON bs.match_id = m.id
                WHERE m.event_name = ?
                  AND bs.player_id IN ({placeholders})
                GROUP BY p.name
                ORDER BY runs DESC
            """, [_EVENT, *squad_ids]).fetchall()
        else:
            # Fallback: top scorers for this franchise (original behavior)
            rows = conn.execute("""
                SELECT p.name,
                       SUM(bs.runs) as runs,
                       COUNT(*) as inns,
                       ROUND(AVG(bs.runs), 1) as avg,
                       ROUND(
                         SUM(bs.runs)::FLOAT
                         / NULLIF(SUM(bs.balls_faced), 0) * 100, 1
                       ) as sr,
                       SUM(bs.fours) as fours,
                       SUM(bs.sixes) as sixes
                FROM batting_scorecard bs
                JOIN players p ON bs.player_id = p.id
                JOIN matches m ON bs.match_id = m.id
                JOIN innings i ON i.match_id = m.id AND bs.innings_id = i.id
                WHERE m.event_name = ?
                  AND i.batting_team = ?
                GROUP BY p.name
                HAVING COUNT(*) >= 5
                ORDER BY runs DESC
                LIMIT 8
            """, [_EVENT, name]).fetchall()

        if rows:
            lines = [
                f"  {nm}: {r} runs in {inn} inns"
                f" (avg {av}, SR {sr})"
                for nm, r, inn, av, sr, _, _ in rows
            ]
            header = (
                f"BATTING PROFILE ({_short(opponent)}"
                f" current squad, career IPL):"
                if squad_ids else
                f"BATTING PROFILE ({_short(opponent)}"
                f" career IPL):"
            )
            parts.append(header + "\n" + "\n".join(lines))

        # Venue-specific batting (if venue known) — team-scoped is correct here
        if venue_city:
            rows = conn.execute("""
                SELECT
                    COUNT(DISTINCT m.id) as matches,
                    ROUND(AVG(i.total_runs), 0) as avg_score,
                    MAX(i.total_runs) as highest,
                    MIN(i.total_runs) as lowest
                FROM matches m
                JOIN innings i ON i.match_id = m.id
                WHERE m.event_name = ?
                  AND i.batting_team = ?
                  AND m.city LIKE ?
                  AND i.innings_number <= 2
            """, [_EVENT, name, f"%{venue_city}%"]).fetchall()

            if rows and rows[0][0] > 0:
                mat, avg, hi, lo = rows[0]
                parts.append(
                    f"AT {venue_city.upper()}: {mat} innings,"
                    f" avg {avg}, high {hi}, low {lo}"
                )

        conn.close()
    except Exception as e:
        parts.append(f"(batting query failed: {e})")

    return "\n\n".join(parts)


def _query_team_bowling_profile(
    opponent: str,
    squad_ids: set[str] | None = None,
) -> str:
    """Query Cricsheet for bowling profile of the opponent's current squad.

    Same cross-team logic as batting: with squad_ids, queries full IPL career.
    """
    name = _cricsheet_name(opponent)
    if not name:
        return ""

    parts: list[str] = []
    try:
        conn = connect_readonly(CRICKET_DB_PATH)

        if squad_ids:
            placeholders = ", ".join(["?"] * len(squad_ids))
            rows = conn.execute(f"""
                SELECT p.name,
                       SUM(bs.wickets) as wkts,
                       COUNT(*) as inns,
                       ROUND(
                         SUM(bs.runs_conceded)::FLOAT
                         / NULLIF(SUM(bs.overs), 0), 2
                       ) as econ,
                       SUM(bs.overs) as overs
                FROM bowling_scorecard bs
                JOIN players p ON bs.player_id = p.id
                JOIN matches m ON bs.match_id = m.id
                WHERE m.event_name = ?
                  AND bs.player_id IN ({placeholders})
                GROUP BY p.name
                ORDER BY wkts DESC
            """, [_EVENT, *squad_ids]).fetchall()
        else:
            rows = conn.execute("""
                SELECT p.name,
                       SUM(bs.wickets) as wkts,
                       COUNT(*) as inns,
                       ROUND(
                         SUM(bs.runs_conceded)::FLOAT
                         / NULLIF(SUM(bs.overs), 0), 2
                       ) as econ,
                       SUM(bs.overs) as overs
                FROM bowling_scorecard bs
                JOIN players p ON bs.player_id = p.id
                JOIN matches m ON bs.match_id = m.id
                JOIN innings i ON i.match_id = m.id AND bs.innings_id = i.id
                WHERE m.event_name = ?
                  AND i.bowling_team = ?
                GROUP BY p.name
                HAVING COUNT(*) >= 5
                ORDER BY wkts DESC
                LIMIT 8
            """, [_EVENT, name]).fetchall()

        if rows:
            lines = [
                f"  {nm}: {w} wkts in {inn} inns"
                f" (econ {ec})"
                for nm, w, inn, ec, _ in rows
            ]
            header = (
                f"BOWLING PROFILE ({_short(opponent)}"
                f" current squad, career IPL):"
                if squad_ids else
                f"BOWLING PROFILE ({_short(opponent)}"
                f" career IPL):"
            )
            parts.append(header + "\n" + "\n".join(lines))

        conn.close()
    except Exception as e:
        parts.append(f"(bowling query failed: {e})")

    return "\n\n".join(parts)


def _build_form_context(opponent: str) -> str:
    """Current-season form from synced data."""
    parts: list[str] = []

    standings = _load_json("standings.json") or []
    schedule = _load_json("schedule.json") or []
    caps = _load_json("caps.json")

    s = next(
        (s for s in standings if s["franchise_id"] == opponent),
        None,
    )
    if s:
        parts.append(
            f"IPL 2026: {_short(opponent)}"
            f" {s['wins']}W {s['losses']}L"
            f" NRR={s['nrr']} (#{s['position']})"
        )

    # Recent results
    team_matches = [
        m for m in schedule
        if m.get("status") == "completed"
        and (m["team1"] == opponent or m["team2"] == opponent)
    ]
    for m in team_matches[-3:]:
        won = m.get("winner") == opponent
        opp = m["team2"] if m["team1"] == opponent else m["team1"]
        parts.append(
            f"  M{m['match_number']}: {'W' if won else 'L'}"
            f" vs {_short(opp)}"
            f" ({m.get('result', '')})"
        )

    # Cap race entries for this team
    if caps:
        for cap_type in ("orange_cap", "purple_cap"):
            entries = [
                e for e in caps.get(cap_type, [])
                if e.get("team") == opponent
            ]
            for e in entries[:2]:
                parts.append(
                    f"  {e['player']}: {e['stat']}"
                )

    return "\n".join(parts)


_SYSTEM_PROMPT = load_prompt("dossier_system.md")
_USER_PROMPT = load_prompt("dossier_user.md")


async def generate_dossier(
    conn: duckdb.DuckDBPyConnection,
    season: str,
    opponent: str,
    perspective: str,
    venue_city: str = "",
) -> dict | None:
    """Generate an opposition dossier.

    Args:
        conn: DuckDB connection (for articles store)
        season: IPL season
        opponent: franchise ID of the team being scouted
        perspective: franchise ID of the team preparing
        venue_city: match venue city for venue-specific data
    """
    cache = LLMCache()
    # Include today's date so dossier refreshes daily with new match data
    cache_key = f"dossier_{perspective}_{opponent}_{season}_{today_ist_iso()}"

    cached = cache.get(_CACHE_TASK, cache_key)
    if cached and cached.get("parsed"):
        console.print(
            f"  [dim]Dossier: cache hit"
            f" ({_short(perspective)} vs"
            f" {_short(opponent)})[/dim]"
        )
        return cached["parsed"]

    # Get current-season squad (player IDs) for Cricsheet query filtering
    squad_ids, squad_names = _get_current_squad(conn, opponent, season)

    # Full squad context with prices/roles for the LLM
    try:
        from pipeline.intel.roster_context import for_team

        squad_context = for_team(conn, season, opponent)
    except Exception:
        squad_context = ", ".join(sorted(squad_names)) if squad_names else "(not available)"

    # Build context from Cricsheet (historical), filtered to current squad
    batting_profile = _query_team_batting_profile(
        opponent, venue_city, squad_ids=squad_ids or None,
    )
    bowling_profile = _query_team_bowling_profile(
        opponent, squad_ids=squad_ids or None,
    )
    form_context = _build_form_context(opponent)

    # Articles about the opponent
    season_start = f"{season}-03-01"
    articles_context = retrieve_summaries_for_team(
        conn, opponent, since_date=season_start,
        max_articles=5,
    ) or "(No recent articles)"

    # LLM call
    from pipeline.config import GEMINI_MODEL_PRO
    from pipeline.llm.gemini import GeminiProvider

    provider = GeminiProvider(model=GEMINI_MODEL_PRO)
    prompt = _USER_PROMPT.format(
        opponent=_short(opponent),
        opponent_short=_short(opponent),
        perspective=_short(perspective),
        season=season,
        squad_context=squad_context,
        batting_profile=batting_profile,
        bowling_profile=bowling_profile,
        form_context=form_context,
        articles_context=articles_context,
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
            "  [yellow]Dossier: failed to parse"
            " LLM response[/yellow]"
        )
        return None

    cache.put(_CACHE_TASK, cache_key, {
        "parsed": parsed,
        "usage": result.get("usage", {}),
    })

    console.print(
        f"  [green]Dossier: {_short(opponent)} scouted for"
        f" {_short(perspective)}[/green]"
    )
    return parsed
