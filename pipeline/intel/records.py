"""Record Watchlist — milestones approaching and season records in danger.

Combines MCP career milestones (historical, no lag concern) with
current-season data from synced caps.json/schedule.json.

Staleness: regenerates daily (milestones don't change fast).

Usage:
    records = await generate_records(season)
"""

import hashlib
import json
import re
from typing import Any

from rich.console import Console

from pipeline.clock import today_ist_iso
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
            SELECT DISTINCT player_name
            FROM ipl_season_squad
            WHERE season = ?
        """, [year]).fetchall()
        return {r[0] for r in rows}
    except Exception as e:
        console.print(f"  [dim]Records: season XI lookup failed: {e}[/dim]")
        return set()


def _get_player_franchises(season: str) -> dict[str, str]:
    """Map player full-name → current franchise short name for team correction.

    The LLM often assigns players to their historical franchise rather
    than their current 2026 team (e.g. Samson → RR instead of CSK).
    Keyed by lowercased full name; surname-only would collide for common
    surnames (Yadav, Kumar, Sharma) and pick a wrong team.
    """
    try:
        from pipeline.db.connection import get_connection
        from pipeline.ipl.franchise_metadata import IPL_FRANCHISES

        year = int(season.split("/")[0]) if "/" in season else int(season)
        conn = get_connection()
        rows = conn.execute("""
            SELECT player_name, franchise_id
            FROM ipl_season_squad
            WHERE season = ?
        """, [year]).fetchall()
        return {
            name.lower(): IPL_FRANCHISES[fid]["short_name"]
            for name, fid in rows
            if fid in IPL_FRANCHISES
        }
    except Exception as e:
        console.print(f"  [dim]Records: franchise lookup failed: {e}[/dim]")
        return {}


def _unavailable_names() -> set[str]:
    """Return the lowercase set of players currently out/doubtful.

    Used to drop milestone-chasers from `imminent` who physically aren't
    going to play in the near-term window the record watch implies.
    Reads from the already-written availability.json — same source the
    rest of the frontend uses.
    """
    av = _load_json("availability.json") or {}
    players = av.get("players") or []
    out: set[str] = set()
    for p in players:
        status = (p.get("status") or "").lower()
        if status in ("out", "doubtful"):
            name = (p.get("player") or "").strip().lower()
            if name:
                out.add(name)
    return out


def _filter_available(
    entries: list[dict], unavailable: set[str],
) -> list[dict]:
    """Drop entries where the milestone-chaser is currently unavailable."""
    if not unavailable:
        return entries
    kept: list[dict] = []
    for e in entries:
        name = (e.get("player") or "").strip().lower()
        if name and name in unavailable:
            continue
        kept.append(e)
    return kept


def _filter_active(entries: list[dict], active: set[str]) -> list[dict]:
    """Drop entries whose player name doesn't match any active squad member.

    Strict full-name match by default (case-insensitive). Falls back to
    initial-style matching ("V Kohli" → "Virat Kohli") only when the LLM
    output starts with a single-letter token. Surname-only matching is
    deliberately avoided — it lets hallucinated names like "Umesh Yadav"
    slip through whenever any other Yadav exists in the squad.
    """
    if not active:
        return entries  # no filter available, keep all

    active_lower = {a.lower() for a in active if a.strip()}
    # Pre-build (initial, surname) → set of full names for the fallback
    by_initial_surname: dict[tuple[str, str], set[str]] = {}
    for full in active_lower:
        toks = full.split()
        if len(toks) >= 2:
            by_initial_surname.setdefault((toks[0][0], toks[-1]), set()).add(full)

    filtered: list[dict] = []
    for e in entries:
        name = e.get("player", "").strip().lower()
        if not name:
            continue
        if name in active_lower:
            filtered.append(e)
            continue
        # Initial-style fallback: "V Kohli" → match if exactly one squad
        # player has surname "kohli" with first name starting with "v".
        toks = name.split()
        if len(toks) >= 2 and len(toks[0]) == 1:
            candidates = by_initial_surname.get((toks[0], toks[-1]), set())
            if len(candidates) == 1:
                filtered.append(e)
    return filtered


def _patch_teams(
    parsed: dict, franchises: dict[str, str],
) -> None:
    """Correct team assignments using current season XI data.

    The LLM assigns teams based on career history, which is often wrong
    for traded players (e.g. Samson → RR instead of CSK in 2026). Lookup
    is by full lowercased name; entries that don't match any squad player
    are left untouched (they should already have been dropped by
    _filter_active, but be defensive).
    """
    if not franchises:
        return
    for section in ("imminent", "on_track"):
        for entry in parsed.get(section, []):
            name = entry.get("player", "").strip().lower()
            if not name:
                continue
            correct = franchises.get(name)
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
    # Cache by date + availability fingerprint so a new injury invalidates
    # the cached list (a milestone-chaser being ruled out should drop them
    # from imminent immediately, not 24h later).
    cache = LLMCache(panel="records")
    today = today_ist_iso()
    unavailable = _unavailable_names()
    avail_marker = (
        f"{len(unavailable)}-"
        + hashlib.sha1(
            "|".join(sorted(unavailable)).encode()
        ).hexdigest()[:6]
    )
    cache_key = f"records_v3_{today}_{avail_marker}"

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
        parsed["imminent"] = _filter_available(parsed.get("imminent", []), unavailable)
        _patch_teams(parsed, franchises)
        return parsed

    mcp_context = _build_mcp_context()
    season_context = _build_season_context()

    # Add availability block so the LLM knows which players to skip at
    # generation time (not just post-filter)
    availability_block = ""
    av = _load_json("availability.json") or {}
    by_team = av.get("by_team") or {}
    if by_team:
        lines = []
        for entries in by_team.values():
            for e in entries:
                player = (e.get("player") or "").strip()
                status = (e.get("status") or "").strip()
                reason = (e.get("reason") or "").strip()
                if player and status:
                    tail = f" — {reason}" if reason else ""
                    lines.append(f"  {player} ({status}){tail}")
        if lines:
            availability_block = (
                "CURRENTLY UNAVAILABLE (do not list these players in "
                "`imminent` — they are not playing):\n"
                + "\n".join(lines)
            )

    if not mcp_context and not season_context:
        return None

    from pipeline.llm.gemini import GeminiProvider

    provider = GeminiProvider(panel="records")
    prompt = _USER_PROMPT.format(
        mcp_context=mcp_context,
        season_context=season_context,
        availability_block=availability_block or "(no players currently unavailable)",
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

    # Drop imminent milestones whose chaser is currently unavailable —
    # belt-and-suspenders against the LLM ignoring the availability block
    if unavailable:
        before = len(parsed.get("imminent", []))
        parsed["imminent"] = _filter_available(parsed.get("imminent", []), unavailable)
        dropped_av = before - len(parsed["imminent"])
        if dropped_av:
            console.print(
                f"  [dim]Records: dropped {dropped_av} milestone(s) for "
                f"unavailable players[/dim]"
            )

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
