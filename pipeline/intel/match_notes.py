"""Match Editorial Notes — one-liner editorial context per completed match.

Generates a short narrative note for each completed match, giving editorial
context beyond the raw scoreline. E.g. "Patidar's 87 sealed the chase after
early wickets fell, lifting RCB to the top of the table."

Staleness: regenerates when schedule results hash changes (new match).

Usage:
    notes = await generate_match_notes(season)
"""

import hashlib
import json
import re
from typing import Any

from rich.console import Console

from pipeline.config import DATA_DIR
from pipeline.intel.prompts import load_prompt
from pipeline.intel.schemas import MatchNote
from pipeline.llm.cache import LLMCache

console = Console()

_CACHE_TASK = "war_room_match_notes"


def _load_json(filename: str) -> Any:
    path = DATA_DIR / "war-room" / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _results_hash(schedule: list[dict]) -> str:
    completed = [
        (m["match_number"], m.get("winner", ""))
        for m in schedule if m.get("status") == "completed"
    ]
    content = json.dumps(completed, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


_SYSTEM_PROMPT = load_prompt("match_notes_system.md")
_USER_PROMPT = load_prompt("match_notes_user.md")


async def generate_match_notes(season: str) -> dict[int, str] | None:
    """Generate editorial notes for all completed matches.

    Returns a dict mapping match_number → note string.
    """
    from pipeline.intel.live_context import (
        build_live_context,
        format_cap_race_block,
    )

    schedule = _load_json("schedule.json")
    standings = _load_json("standings.json")

    if not schedule:
        return None

    completed = [
        m for m in schedule if m.get("status") == "completed"
    ]
    if not completed:
        return None

    # Shared ground-truth bundle — gives the editorial layer the cap race
    # movement so notes can reference milestones that crossed during the
    # match (e.g. "Jaiswal's 92 pushed him past Kohli for the Orange Cap").
    # Match notes don't need a DB connection for wire_recent — they're
    # post-hoc editorial, not live grounding.
    live_ctx = build_live_context(None, season)

    # Check cache
    cache = LLMCache()
    r_hash = _results_hash(schedule)
    cache_key = f"match_notes_v2_{r_hash}"

    cached = cache.get(_CACHE_TASK, cache_key)
    if cached and cached.get("parsed"):
        console.print(
            f"  [dim]Match notes: cache hit ({r_hash[:8]})[/dim]"
        )
        # JSON serialization converts int keys to strings — restore them
        return {int(k): v for k, v in cached["parsed"].items()}

    # Build context
    standings_context = ""
    if standings:
        standings_context = "\n".join(
            f"{s.get('short_name', s['franchise_id'].upper())}:"
            f" #{s['position']} {s['wins']}W-{s['losses']}L"
            f" NRR={s['nrr']}"
            for s in standings
        )

    matches_lines: list[str] = []
    for m in completed:
        t1 = m["team1"].upper()
        t2 = m["team2"].upper()
        line = (
            f"M{m['match_number']}: {t1} vs {t2}"
            f" — {m.get('score1', '?')} vs {m.get('score2', '?')}"
            f" — {m.get('result', '?')}"
        )
        if m.get("hero_name"):
            line += f" (POTM: {m['hero_name']}"
            if m.get("hero_stat"):
                line += f" {m['hero_stat']}"
            line += ")"
        if m.get("toss"):
            line += f"\n  Toss: {m['toss']}"
        if m.get("wiki_notes"):
            line += f"\n  Wikipedia notes: {m['wiki_notes']}"
        b1 = m.get("top_batter1")
        w1 = m.get("top_bowler1")
        if b1 or w1:
            parts: list[str] = []
            if b1:
                not_out = "*" if b1.get("not_out") else ""
                parts.append(f"{b1['name']} {b1['runs']}{not_out}({b1['balls']})")
            if w1:
                parts.append(f"{w1['name']} {w1['wickets']}/{w1['runs']}")
            line += f"\n  Inn 1: {' | '.join(parts)}"
        b2 = m.get("top_batter2")
        w2 = m.get("top_bowler2")
        if b2 or w2:
            parts = []
            if b2:
                not_out = "*" if b2.get("not_out") else ""
                parts.append(f"{b2['name']} {b2['runs']}{not_out}({b2['balls']})")
            if w2:
                parts.append(f"{w2['name']} {w2['wickets']}/{w2['runs']}")
            line += f"\n  Inn 2: {' | '.join(parts)}"
        matches_lines.append(line)
    matches_context = "\n".join(matches_lines)

    # Cap race context — lets notes reference cap rank movement
    cap_context = (
        format_cap_race_block(live_ctx, per_cap=5)
        or "(no cap race data)"
    )

    # LLM call
    from pipeline.llm.gemini import GeminiProvider

    provider = GeminiProvider()
    prompt = _USER_PROMPT.format(
        standings_context=standings_context,
        matches_context=matches_context,
        cap_context=cap_context,
    )

    result = await provider.generate(
        prompt,
        system=_SYSTEM_PROMPT,
        temperature=0.7,
        response_schema=list[MatchNote],
    )

    parsed_list = result.get("parsed")
    if not parsed_list:
        # fallback to text parsing
        text = result.get("text", "").strip()
        if text.startswith("```"):
            text = re.sub(r"```(?:json)?\n?", "", text).strip()
        try:
            parsed_list = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            parsed_list = None

    if not parsed_list or not isinstance(parsed_list, list):
        console.print(
            "  [yellow]Match notes: failed to parse LLM response[/yellow]"
        )
        return None

    # Convert to {match_number: note} dict
    notes: dict[int, str] = {}
    for entry in parsed_list:
        mn = entry.get("match_number")
        note = entry.get("note", "").strip()
        if mn and note:
            notes[int(mn)] = note

    cache.put(_CACHE_TASK, cache_key, {
        "parsed": notes,
        "usage": result.get("usage", {}),
    })

    console.print(
        f"  [green]Match notes: {len(notes)} notes generated[/green]"
    )
    return notes
