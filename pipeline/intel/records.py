"""Record Watchlist — milestones approaching and season records in danger.

Combines MCP career milestones (historical, no lag concern) with
current-season data from synced caps.json/schedule.json.

Staleness: regenerates daily (milestones don't change fast).

Usage:
    records = await generate_records(season)
"""

import json
import re
from datetime import date
from typing import Any

from rich.console import Console

from pipeline.config import DATA_DIR
from pipeline.intel.prompts import load_prompt
from pipeline.intel.schemas import RecordsResponse
from pipeline.llm.cache import LLMCache

console = Console()


def _get_active_players(season: str) -> set[str]:
    """Get names of players in current season XI (across all franchises).

    Reuses the shared enrichment+cricket connection via get_connection()
    to avoid DuckDB file-handle conflicts during sync.
    """
    try:
        from pipeline.db.connection import get_connection

        year = int(season.split("/")[0]) if "/" in season else int(season)
        conn = get_connection()
        rows = conn.execute("""
            SELECT DISTINCT p.name
            FROM ipl_season_xi xi
            JOIN cricket.players p ON xi.player_id = p.id
            WHERE xi.season = ?
        """, [year]).fetchall()
        return {r[0] for r in rows}
    except Exception as e:
        console.print(f"  [dim]Records: season XI lookup failed: {e}[/dim]")
        return set()


def _get_player_franchises(season: str) -> dict[str, str]:
    """Map player last-name → current franchise_id for team correction.

    The LLM often assigns players to their historical franchise rather
    than their current 2026 team (e.g. Samson → RR instead of CSK).
    """
    try:
        from pipeline.db.connection import get_connection

        year = int(season.split("/")[0]) if "/" in season else int(season)
        conn = get_connection()
        rows = conn.execute("""
            SELECT p.name, f.short_name
            FROM ipl_season_xi xi
            JOIN cricket.players p ON xi.player_id = p.id
            JOIN ipl_franchise f ON xi.franchise_id = f.id
            WHERE xi.season = ?
        """, [year]).fetchall()
        # Key by last name (same convention as _filter_active)
        return {name.split()[-1].lower(): short for name, short in rows}
    except Exception as e:
        console.print(f"  [dim]Records: franchise lookup failed: {e}[/dim]")
        return {}


def _filter_active(entries: list[dict], active: set[str]) -> list[dict]:
    """Drop entries whose player name doesn't match any active squad member.

    Cricsheet uses abbreviated names (e.g. "V Kohli", "B Kumar") while
    LLM output uses full names ("Virat Kohli", "Bhuvneshwar Kumar").
    Match by last name (last token) which is reliable for cricket names.
    """
    if not active:
        return entries  # no filter available, keep all
    # Build a set of last names for fast matching
    active_lasts = {a.split()[-1].lower() for a in active if a.strip()}
    filtered = []
    for e in entries:
        name = e.get("player", "").strip()
        if not name:
            continue
        last = name.split()[-1].lower()
        if last in active_lasts:
            filtered.append(e)
    return filtered


def _patch_teams(
    parsed: dict, franchises: dict[str, str],
) -> None:
    """Correct team assignments using current season XI data.

    The LLM assigns teams based on career history, which is often wrong
    for traded players (e.g. Samson → RR instead of CSK in 2026).
    """
    if not franchises:
        return
    for section in ("imminent", "on_track"):
        for entry in parsed.get(section, []):
            name = entry.get("player", "").strip()
            if not name:
                continue
            last = name.split()[-1].lower()
            correct = franchises.get(last)
            if correct and entry.get("team") != correct:
                entry["team"] = correct

_CACHE_TASK = "war_room_records"


def _load_json(filename: str) -> Any:
    path = DATA_DIR / "war-room" / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _build_mcp_context() -> str:
    """Query MCP for career milestone data (all-time, no season filter)."""
    parts: list[str] = []

    try:
        from pipeline.sources.cricsheet import _EVENT, _connect

        conn = _connect()

        # All-time IPL run leaders approaching round numbers
        rows = conn.execute("""
            SELECT p.name, SUM(bs.runs) as total
            FROM batting_scorecard bs
            JOIN players p ON bs.player_id = p.id
            JOIN matches m ON bs.match_id = m.id
            WHERE m.event_name = ?
            GROUP BY p.name
            HAVING total >= 3000
            ORDER BY total DESC
            LIMIT 15
        """, [_EVENT]).fetchall()
        if rows:
            lines = []
            for name, total in rows:
                # Flag round-number proximity
                for milestone in (10000, 9000, 8000, 7000, 6000, 5000, 4000):
                    if total < milestone and total >= milestone - 500:
                        lines.append(
                            f"  {name}: {total} runs"
                            f" ({milestone - total} to {milestone})"
                        )
                        break
                else:
                    lines.append(f"  {name}: {total} runs")
            parts.append(
                "IPL CAREER RUN LEADERS:\n" + "\n".join(lines)
            )

        # All-time IPL wicket leaders
        rows = conn.execute("""
            SELECT p.name, SUM(bs.wickets) as total
            FROM bowling_scorecard bs
            JOIN players p ON bs.player_id = p.id
            JOIN matches m ON bs.match_id = m.id
            WHERE m.event_name = ?
            GROUP BY p.name
            HAVING total >= 100
            ORDER BY total DESC
            LIMIT 15
        """, [_EVENT]).fetchall()
        if rows:
            lines = []
            for name, total in rows:
                for milestone in (250, 200, 150):
                    if total < milestone and total >= milestone - 20:
                        lines.append(
                            f"  {name}: {total} wkts"
                            f" ({milestone - total} to {milestone})"
                        )
                        break
                else:
                    lines.append(f"  {name}: {total} wkts")
            parts.append(
                "IPL CAREER WICKET LEADERS:\n" + "\n".join(lines)
            )

        # All-time IPL records (single-innings bests)
        rows = conn.execute("""
            SELECT p.name, bs.runs, bs.balls_faced,
                   m.start_date, m.season
            FROM batting_scorecard bs
            JOIN players p ON bs.player_id = p.id
            JOIN matches m ON bs.match_id = m.id
            WHERE m.event_name = ?
            ORDER BY bs.runs DESC
            LIMIT 5
        """, [_EVENT]).fetchall()
        if rows:
            lines = [
                f"  {name}: {runs} off {balls} ({season})"
                for name, runs, balls, _, season in rows
            ]
            parts.append(
                "ALL-TIME HIGHEST IPL SCORES:\n" + "\n".join(lines)
            )

        conn.close()
    except Exception as e:
        parts.append(f"(MCP query failed: {e})")

    return "\n\n".join(parts)


def _build_season_context() -> str:
    """Build current-season context from synced data."""
    parts: list[str] = []

    caps = _load_json("caps.json")
    if caps:
        for cap_type, label in [
            ("orange_cap", "ORANGE CAP (IPL 2026)"),
            ("purple_cap", "PURPLE CAP (IPL 2026)"),
        ]:
            entries = caps.get(cap_type, [])[:10]
            if entries:
                lines = [
                    f"  {e['player']} ({e['team_short']})"
                    f" — {e['stat']}"
                    for e in entries
                ]
                parts.append(f"{label}:\n" + "\n".join(lines))

    schedule = _load_json("schedule.json")
    if schedule:
        completed = [
            m for m in schedule if m.get("status") == "completed"
        ]
        parts.append(
            f"MATCHES COMPLETED: {len(completed)} of 70 league matches"
        )

    return "\n\n".join(parts)


_SYSTEM_PROMPT = load_prompt("records_system.md")
_USER_PROMPT = load_prompt("records_user.md")


async def generate_records(season: str) -> dict | None:
    """Generate the record watchlist."""
    # Cache by date (daily refresh)
    cache = LLMCache()
    today = date.today().isoformat()
    cache_key = f"records_{today}"

    # Active player filter + franchise lookup runs on every path
    active = _get_active_players(season)
    franchises = _get_player_franchises(season)

    cached = cache.get(_CACHE_TASK, cache_key)
    if cached and cached.get("parsed"):
        console.print(
            f"  [dim]Records: cache hit ({today})[/dim]"
        )
        parsed = cached["parsed"]
        if active:
            parsed["imminent"] = _filter_active(parsed.get("imminent", []), active)
            parsed["on_track"] = _filter_active(parsed.get("on_track", []), active)
        _patch_teams(parsed, franchises)
        return parsed

    mcp_context = _build_mcp_context()
    season_context = _build_season_context()

    if not mcp_context and not season_context:
        return None

    from pipeline.llm.gemini import GeminiProvider

    provider = GeminiProvider()
    prompt = _USER_PROMPT.format(
        mcp_context=mcp_context,
        season_context=season_context,
    )

    result = await provider.generate(
        prompt,
        system=_SYSTEM_PROMPT,
        temperature=0.4,
        response_schema=RecordsResponse,
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
            "  [yellow]Records: failed to parse LLM response[/yellow]"
        )
        return None

    # Filter against active season XI to drop retired/traded players
    if active:
        before_i = len(parsed.get("imminent", []))
        before_o = len(parsed.get("on_track", []))
        parsed["imminent"] = _filter_active(parsed.get("imminent", []), active)
        parsed["on_track"] = _filter_active(parsed.get("on_track", []), active)
        dropped = (before_i + before_o) - len(parsed["imminent"]) - len(parsed["on_track"])
        if dropped:
            console.print(f"  [dim]Records: filtered {dropped} inactive players[/dim]")

    # Correct team assignments from season XI (LLM uses historical teams)
    _patch_teams(parsed, franchises)

    cache.put(_CACHE_TASK, cache_key, {
        "parsed": parsed,
        "usage": result.get("usage", {}),
    })

    imminent = len(parsed.get("imminent", []))
    on_track = len(parsed.get("on_track", []))
    console.print(
        f"  [green]Records: {imminent} imminent,"
        f" {on_track} on-track milestones[/green]"
    )
    return parsed
