"""Smart Ticker — LLM-generated dynamic insights for the War Room ticker.

Replaces the static H2H/standings ticker with surprising, contextual
insights synthesized from:
- MCP career milestones and all-time records (historical, no lag concern)
- Current-season data from synced JSON (standings, caps, schedule)

Staleness: regenerates when standings hash changes (i.e. after a match).
Cached otherwise — resyncs don't burn LLM calls.

Usage:
    items = await generate_smart_ticker(season, today_matches)
"""

import hashlib
import json
import re
from typing import Any

from rich.console import Console

from pipeline.clock import today_ist_iso
from pipeline.config import DATA_DIR
from pipeline.intel.live_context import format_availability_block
from pipeline.intel.prompts import load_prompt
from pipeline.intel.schemas import TickerItemResponse
from pipeline.ipl.franchise_metadata import IPL_FRANCHISES
from pipeline.llm.cache import LLMCache
from pipeline.models import ScheduleMatch, TickerItem

console = Console()

_CACHE_TASK = "war_room_ticker"


def _short(fid: str) -> str:
    return IPL_FRANCHISES.get(fid, {}).get("short_name", fid.upper())


def _load_json(filename: str) -> Any:
    """Load a war-room JSON file, returning None on failure."""
    path = DATA_DIR / "war-room" / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _standings_hash(standings: list[dict]) -> str:
    """Hash of standings state — changes when a match result lands."""
    content = json.dumps(
        [(s["short_name"], s["played"], s["wins"], s["losses"])
         for s in standings],
        sort_keys=True,
    )
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _get_active_last_names(season: str) -> set[str]:
    """Get last names of players in current season squads for filtering."""
    try:
        from pipeline.db.connection import get_connection

        year = int(season.split("/")[0]) if "/" in season else int(season)
        conn = get_connection()
        rows = conn.execute(
            "SELECT DISTINCT player_name FROM ipl_season_squad WHERE season = ?",
            [year],
        ).fetchall()
        return {r[0].split()[-1].lower() for r in rows if r[0].strip()}
    except Exception:
        return set()


def _is_active(name: str, active_lasts: set[str]) -> bool:
    """Check if a player name matches any active squad member by last name."""
    if not active_lasts:
        return True  # no filter available, keep all
    return name.split()[-1].lower() in active_lasts


def _build_mcp_context(
    today_matches: list[ScheduleMatch],
    active_lasts: set[str],
) -> str:
    """Query MCP for historical data relevant to ticker insights.

    Only includes players who are in the current season's squads.
    """
    parts: list[str] = []

    try:
        from pipeline.sources.cricsheet import _EVENT, _connect

        conn = _connect()

        # All-time IPL run leaders — filtered to active players
        rows = conn.execute("""
            SELECT p.name, SUM(bs.runs) as total
            FROM batting_scorecard bs
            JOIN players p ON bs.player_id = p.id
            JOIN matches m ON bs.match_id = m.id
            WHERE m.event_name = ?
            GROUP BY p.name
            ORDER BY total DESC
            LIMIT 30
        """, [_EVENT]).fetchall()
        if rows:
            lines = [
                f"  {name}: {total} runs"
                for name, total in rows
                if _is_active(name, active_lasts)
            ][:10]
            if lines:
                parts.append(
                    "ALL-TIME IPL RUN LEADERS (active players):\n"
                    + "\n".join(lines)
                )

        # All-time IPL wicket leaders — filtered to active players
        rows = conn.execute("""
            SELECT p.name, SUM(bs.wickets) as total
            FROM bowling_scorecard bs
            JOIN players p ON bs.player_id = p.id
            JOIN matches m ON bs.match_id = m.id
            WHERE m.event_name = ?
            GROUP BY p.name
            ORDER BY total DESC
            LIMIT 30
        """, [_EVENT]).fetchall()
        if rows:
            lines = [
                f"  {name}: {total} wkts"
                for name, total in rows
                if _is_active(name, active_lasts)
            ][:10]
            if lines:
                parts.append(
                    "ALL-TIME IPL WICKET LEADERS (active players):\n"
                    + "\n".join(lines)
                )

        # H2H for today's matches
        for match in today_matches:
            from pipeline.sources.cricsheet import (
                _CRICSHEET_TO_FID,
            )
            fid_to_name = {v: k for k, v in _CRICSHEET_TO_FID.items()}
            n1 = fid_to_name.get(match.team1)
            n2 = fid_to_name.get(match.team2)
            if n1 and n2:
                h2h = conn.execute("""
                    SELECT outcome_winner, COUNT(*) as cnt
                    FROM matches
                    WHERE event_name = ?
                      AND ((team1 = ? AND team2 = ?)
                           OR (team1 = ? AND team2 = ?))
                      AND outcome_winner IS NOT NULL
                    GROUP BY outcome_winner
                """, [_EVENT, n1, n2, n2, n1]).fetchall()
                wins = {
                    _CRICSHEET_TO_FID.get(r[0], ""): r[1]
                    for r in h2h
                }
                w1 = wins.get(match.team1, 0)
                w2 = wins.get(match.team2, 0)
                parts.append(
                    f"H2H {_short(match.team1)} vs"
                    f" {_short(match.team2)}: {w1}-{w2} all-time"
                )

        conn.close()
    except Exception as e:
        parts.append(f"(MCP query failed: {e})")

    # Toss trends from completed schedule matches
    try:
        schedule = _load_json("schedule.json") or []
        toss_matches = [
            m for m in schedule
            if m.get("status") == "completed" and m.get("toss")
        ]
        if toss_matches:
            total = len(toss_matches)
            field_first = sum(
                1 for m in toss_matches
                if m["toss"].get("decision") == "field"
            )
            toss_winner_won = sum(
                1 for m in toss_matches
                if m["toss"].get("winner") == m.get("winner")
            )
            parts.append(
                f"TOSS TRENDS ({total} matches):"
                f" Field first chosen {field_first}/{total}"
                f" ({round(field_first / total * 100)}%)."
                f" Toss winner won match {toss_winner_won}/{total}"
                f" ({round(toss_winner_won / total * 100)}%)."
            )
    except Exception:
        pass

    return "\n\n".join(parts)


def _build_season_context(
    standings: list[dict],
    caps: dict | None,
    schedule: list[dict] | None,
    availability: dict | None = None,
) -> str:
    """Build current-season context from synced JSON data."""
    parts: list[str] = []

    # Standings
    if standings:
        lines = []
        for s in standings:
            lines.append(
                f"  {s['position']}. {s['short_name']}"
                f" P={s['played']} W={s['wins']}"
                f" L={s['losses']} NRR={s['nrr']}"
            )
        parts.append(
            "CURRENT IPL 2026 STANDINGS:\n" + "\n".join(lines)
        )

    # Cap race leaders
    if caps:
        for cap_type in ("orange_cap", "purple_cap"):
            entries = caps.get(cap_type, [])[:5]
            if entries:
                label = "ORANGE CAP" if "orange" in cap_type else (
                    "PURPLE CAP"
                )
                lines = [
                    f"  {e['rank']}. {e['player']}"
                    f" ({e['team_short']}) {e['stat']}"
                    for e in entries
                ]
                parts.append(f"{label} LEADERS:\n" + "\n".join(lines))

    # Recent results
    if schedule:
        completed = [
            m for m in schedule if m.get("status") == "completed"
        ]
        if completed:
            lines = []
            for m in completed[-5:]:
                result = m.get("result", "")
                lines.append(
                    f"  M{m['match_number']}: {result}"
                    f" ({m.get('score1', '?')} vs {m.get('score2', '?')})"
                )
            parts.append("RECENT RESULTS:\n" + "\n".join(lines))

        # Today's/upcoming matches
        today_str = today_ist_iso()
        upcoming = [
            m for m in schedule
            if m.get("status") == "scheduled" and m["date"] >= today_str
        ][:3]
        if upcoming:
            lines = [
                f"  M{m['match_number']}: {_short(m['team1'])} vs"
                f" {_short(m['team2'])} on {m['date']}"
                for m in upcoming
            ]
            parts.append("UPCOMING:\n" + "\n".join(lines))

    avail_block = format_availability_block({"availability": availability})
    if avail_block:
        parts.append(avail_block)

    return "\n\n".join(parts)


_SYSTEM_PROMPT = load_prompt("ticker_system.md")
_USER_PROMPT = load_prompt("ticker_user.md")


async def generate_smart_ticker(
    season: str,
    today_matches: list[ScheduleMatch],
) -> list[TickerItem]:
    """Generate smart ticker items via Gemini Flash.

    Uses MCP historical data + current-season synced JSON.
    Cached by standings hash — only regenerates after match results.
    """
    # Load current-season data
    standings = _load_json("standings.json") or []
    caps = _load_json("caps.json")
    schedule = _load_json("schedule.json")
    availability = _load_json("availability.json")

    if not standings:
        console.print(
            "  [yellow]Ticker: no standings data available[/yellow]"
        )
        return []

    # Check staleness — cache key includes the availability event count so
    # the ticker regenerates whenever a new injury/availability fact lands,
    # even when the points table hasn't moved. The "v2" prefix invalidates
    # legacy cached entries that were generated without availability grounding
    # (and were therefore prone to fabricated injury claims).
    cache = LLMCache()
    s_hash = _standings_hash(standings)
    avail_marker = (availability or {}).get("total_unavailable", 0)
    cache_key = f"ticker_v2_{s_hash}_a{avail_marker}"

    cached = cache.get(_CACHE_TASK, cache_key)
    if cached and cached.get("items"):
        console.print(
            f"  [dim]Ticker: cache hit ({s_hash[:8]})[/dim]"
        )
        return [TickerItem(**item) for item in cached["items"]]

    # Active player filter — only feed active names to the LLM
    active_lasts = _get_active_last_names(season)

    # Build context
    mcp_context = _build_mcp_context(today_matches, active_lasts)
    season_context = _build_season_context(
        standings, caps, schedule, availability,
    )

    # Add roster summary so LLM has a positive reference of active players
    try:
        from pipeline.db.connection import get_connection
        from pipeline.intel.roster_context import summary as roster_summary

        roster_ctx = roster_summary(get_connection(), season)
        if roster_ctx:
            season_context += "\n\n" + roster_ctx
    except Exception:
        pass

    # LLM call
    from pipeline.llm.gemini import GeminiProvider

    provider = GeminiProvider()
    prompt = _USER_PROMPT.format(
        mcp_context=mcp_context,
        season_context=season_context,
    )

    result = await provider.generate(
        prompt,
        system=_SYSTEM_PROMPT,
        temperature=0.8,
        response_schema=list[TickerItemResponse],
    )

    # Parse response
    parsed = result.get("parsed")
    if not parsed:
        text = result.get("text", "").strip()
        if text.startswith("```"):
            text = re.sub(r"```(?:json)?\n?", "", text).strip()
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            parsed = None

    items: list[TickerItem] = []
    if parsed and isinstance(parsed, list):
        for entry in parsed:
            cat = entry.get("category", "INSIGHT")
            txt = entry.get("text", "")
            if txt:
                items.append(TickerItem(category=cat, text=txt))

    if not items:
        console.print(
            "  [yellow]Ticker: LLM returned no valid items[/yellow]"
        )
        return []

    # Cache
    cache.put(_CACHE_TASK, cache_key, {
        "items": [
            {"category": i.category, "text": i.text} for i in items
        ],
        "usage": result.get("usage", {}),
    })

    console.print(
        f"  [green]Ticker: {len(items)} smart items generated[/green]"
    )
    return items
