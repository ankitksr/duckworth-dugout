"""Season Narrative Arc — the story of each franchise's season.

Generates a running editorial per team from schedule results, standings,
caps data, and RSS article themes. Entirely current-season — no MCP.

Staleness: regenerates when schedule results hash changes (new match).

Usage:
    narratives = await generate_narratives(conn, season)
"""

import hashlib
import json
import re
from typing import Any

import duckdb
from rich.console import Console

from pipeline.config import DATA_DIR
from pipeline.intel.articles import retrieve_for_team
from pipeline.intel.prompts import load_prompt
from pipeline.intel.schemas import NarrativeEntry
from pipeline.ipl.franchise_metadata import IPL_FRANCHISES
from pipeline.llm.cache import LLMCache

console = Console()

_CACHE_TASK = "war_room_narratives"


def _short(fid: str) -> str:
    return IPL_FRANCHISES.get(fid, {}).get("short_name", fid.upper())


def _load_json(filename: str) -> Any:
    path = DATA_DIR / "war-room" / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _results_hash(schedule: list[dict]) -> str:
    """Hash of completed results — changes when a new match completes."""
    completed = [
        (m["match_number"], m.get("winner", ""))
        for m in schedule if m.get("status") == "completed"
    ]
    content = json.dumps(completed, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


_SYSTEM_PROMPT = load_prompt("narrative_system.md")
_USER_PROMPT = load_prompt("narrative_user.md")


async def generate_narratives(
    conn: duckdb.DuckDBPyConnection,
    season: str,
) -> list[dict] | None:
    """Generate season narrative arcs for all active franchises."""
    standings = _load_json("standings.json") or []
    schedule = _load_json("schedule.json")

    if not standings or not schedule:
        return None

    # Only generate for teams that have played
    active = [s for s in standings if s["played"] > 0]
    if not active:
        return None

    # Check cache
    cache = LLMCache()
    r_hash = _results_hash(schedule)
    cache_key = f"narratives_{r_hash}"

    cached = cache.get(_CACHE_TASK, cache_key)
    if cached and cached.get("parsed"):
        console.print(
            f"  [dim]Narratives: cache hit ({r_hash[:8]})[/dim]"
        )
        return cached["parsed"]

    # Build standings + results context
    standings_lines: list[str] = []
    completed = [
        m for m in schedule if m.get("status") == "completed"
    ]
    for s in active:
        fid = s["franchise_id"]
        team_matches = [
            m for m in completed
            if m["team1"] == fid or m["team2"] == fid
        ]
        results = []
        for m in team_matches:
            won = m.get("winner") == fid
            opp = m["team2"] if m["team1"] == fid else m["team1"]
            hero_name = m.get("hero_name", "")
            hero_stat = m.get("hero_stat", "")
            potm_suffix = (
                f" — POTM: {hero_name} {hero_stat}"
                if hero_name and hero_stat
                else ""
            )
            results.append(
                f"{'W' if won else 'L'} vs {_short(opp)}"
                f" ({m.get('result', '')}){potm_suffix}"
            )
        standings_lines.append(
            f"{_short(fid)}: {s['wins']}W {s['losses']}L"
            f" NRR={s['nrr']} (#{s['position']})"
            f" — {', '.join(results) if results else 'no results'}"
        )
    standings_context = "\n".join(standings_lines)

    # Enrich standings lines with cap race data
    caps = _load_json("caps.json")
    if caps:
        cap_lines: list[str] = []
        for s in active:
            fid = s["franchise_id"]
            cap_tags: list[str] = []
            for e in caps.get("orange_cap", [])[:5]:
                if e.get("team") == fid:
                    cap_tags.append(
                        f"OC {e['player']} #{e['rank']} ({e['stat']})"
                    )
            for e in caps.get("purple_cap", [])[:5]:
                if e.get("team") == fid:
                    cap_tags.append(
                        f"PC {e['player']} #{e['rank']} ({e['stat']})"
                    )
            if cap_tags:
                cap_lines.append(
                    f"{_short(fid)}: {' | '.join(cap_tags)}"
                )
        if cap_lines:
            standings_context += (
                "\n\nCAP RACE (top 5 Orange/Purple):\n"
                + "\n".join(cap_lines)
            )

    # Full roster context — all teams, all players
    try:
        from pipeline.intel.roster_context import all_squads

        roster_text = all_squads(conn, season)
        if roster_text:
            standings_context += f"\n\n{roster_text}"
    except Exception:
        pass

    # Build upcoming fixture context (next match per team)
    upcoming = [
        m for m in schedule if m.get("status") == "scheduled"
    ]
    upcoming.sort(key=lambda m: (m.get("date", ""), m.get("match_number", 0)))
    upcoming_lines: list[str] = []
    seen_teams: set[str] = set()
    for m in upcoming:
        for fid in (m["team1"], m["team2"]):
            if fid not in seen_teams:
                seen_teams.add(fid)
                opp = m["team2"] if m["team1"] == fid else m["team1"]
                upcoming_lines.append(
                    f"{_short(fid)}: next vs {_short(opp)}"
                    f" (M{m['match_number']}, {m.get('date', '')},"
                    f" {m.get('venue', '')})"
                )
    upcoming_context = (
        "\n".join(upcoming_lines)
        if upcoming_lines
        else "(No upcoming fixtures)"
    )

    # Build qualification context from scenarios.json
    scenarios = _load_json("scenarios.json") or {}
    qual_parts: list[str] = []
    for entry in scenarios.get("elimination_watch", []):
        qual_parts.append(
            f"{entry['team']}: risk={entry['risk']},"
            f" {entry['key_metric']}"
            f" — {entry['insight']}"
        )
    for entry in scenarios.get("qualification_math", []):
        qual_parts.append(f"{entry['tag']}: {entry['fact']}")
    qualification_context = (
        "\n".join(qual_parts)
        if qual_parts
        else "(No qualification data available)"
    )

    # Retrieve RSS articles for each active team (from articles store)
    articles_parts: list[str] = []
    season_start = f"{season}-03-01"
    for s in active:
        fid = s["franchise_id"]
        team_articles = retrieve_for_team(
            conn, fid, since_date=season_start,
            max_articles=3, max_chars_per_article=300,
        )
        if team_articles:
            articles_parts.append(
                f"{_short(fid)} coverage:\n{team_articles}"
            )
    articles_context = (
        "\n\n".join(articles_parts)
        if articles_parts
        else "(No RSS coverage available)"
    )

    # LLM call
    from pipeline.config import GEMINI_MODEL_PRO
    from pipeline.llm.gemini import GeminiProvider

    provider = GeminiProvider(model=GEMINI_MODEL_PRO)
    prompt = _USER_PROMPT.format(
        standings_context=standings_context,
        articles_context=articles_context,
        upcoming_context=upcoming_context,
        qualification_context=qualification_context,
    )

    result = await provider.generate(
        prompt,
        system=_SYSTEM_PROMPT,
        temperature=0.7,
        response_schema=list[NarrativeEntry],
    )

    parsed = result.get("parsed")
    if not parsed:
        text = result.get("text", "").strip()
        if text.startswith("```"):
            text = re.sub(r"```(?:json)?\n?", "", text).strip()
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            m = re.search(r"\[.*\]", text, re.DOTALL)
            if m:
                try:
                    parsed = json.loads(m.group())
                except (json.JSONDecodeError, ValueError):
                    pass

    if not parsed or not isinstance(parsed, list):
        console.print(
            "  [yellow]Narratives: failed to parse"
            " LLM response[/yellow]"
        )
        return None

    # Normalize franchise_id to lowercase (LLM may return uppercase)
    for entry in parsed:
        if isinstance(entry, dict) and "franchise_id" in entry:
            entry["franchise_id"] = entry["franchise_id"].lower()

    cache.put(_CACHE_TASK, cache_key, {
        "parsed": parsed,
        "usage": result.get("usage", {}),
    })

    console.print(
        f"  [green]Narratives: {len(parsed)} team arcs"
        " generated[/green]"
    )
    return parsed
