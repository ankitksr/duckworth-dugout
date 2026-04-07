"""Playoff Scenario Engine — what does tonight's result mean?

Generates elimination watch, qualification paths, and "if tonight"
branches from current standings + remaining schedule.

All current-season data — no MCP dependency.
Staleness: regenerates when standings hash changes.

Usage:
    scenarios = await generate_scenarios(season)
"""

import hashlib
import json
import re
from datetime import date
from typing import Any

from rich.console import Console

from pipeline.config import DATA_DIR
from pipeline.intel.prompts import load_prompt
from pipeline.intel.schemas import ScenariosResponse
from pipeline.ipl.franchise_metadata import IPL_FRANCHISES
from pipeline.llm.cache import LLMCache

console = Console()

_CACHE_TASK = "war_room_scenarios"


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


def _standings_hash(standings: list[dict]) -> str:
    content = json.dumps(
        [(s["short_name"], s["played"], s["wins"], s["losses"])
         for s in standings],
        sort_keys=True,
    )
    return hashlib.sha256(content.encode()).hexdigest()[:16]


_SYSTEM_PROMPT = load_prompt("scenarios_system.md")
_USER_PROMPT = load_prompt("scenarios_user.md")


async def generate_scenarios(season: str) -> dict | None:
    """Generate playoff scenarios from standings + schedule."""
    standings = _load_json("standings.json") or []
    schedule = _load_json("schedule.json")

    if not standings or not schedule:
        return None

    # Check cache
    cache = LLMCache()
    s_hash = _standings_hash(standings)
    cache_key = f"scenarios_{s_hash}"

    cache_key_v = f"{cache_key}_v4"  # v4: structured qualification_math
    cached = cache.get(_CACHE_TASK, cache_key_v)
    if cached and cached.get("parsed"):
        console.print(
            f"  [dim]Scenarios: cache hit ({s_hash[:8]})[/dim]"
        )
        return cached["parsed"]

    # Build context
    completed = [
        m for m in schedule if m.get("status") == "completed"
    ]
    matches_played = len(completed)

    standings_lines = []
    for s in standings:
        standings_lines.append(
            f"  {s['position']}. {s['short_name']}"
            f" P={s['played']} W={s['wins']} L={s['losses']}"
            f" Pts={s['points']} NRR={s['nrr']}"
        )
    standings_text = "\n".join(standings_lines)

    today_str = date.today().isoformat()
    upcoming = [
        m for m in schedule
        if m.get("status") in ("scheduled", "live")
    ]
    # Build H2H lookup from Cricsheet for upcoming fixtures
    h2h_map: dict[tuple[str, str], tuple[int, int]] = {}
    try:
        from pipeline.sources.cricsheet import _CRICSHEET_TO_FID, _EVENT, _connect
        _fid_to_name = {v: k for k, v in _CRICSHEET_TO_FID.items()}
        _cs_conn = _connect()
        for m in upcoming[:10]:
            f1, f2 = m["team1"], m["team2"]
            pair = (f1, f2)
            if pair not in h2h_map:
                n1 = _fid_to_name.get(f1)
                n2 = _fid_to_name.get(f2)
                if n1 and n2:
                    h2h_rows = _cs_conn.execute("""
                        SELECT outcome_winner, COUNT(*) as cnt
                        FROM matches
                        WHERE event_name = ?
                          AND ((team1 = ? AND team2 = ?)
                               OR (team1 = ? AND team2 = ?))
                          AND outcome_winner IS NOT NULL
                        GROUP BY outcome_winner
                    """, [_EVENT, n1, n2, n2, n1]).fetchall()
                    wins = {_CRICSHEET_TO_FID.get(r[0], ""): r[1] for r in h2h_rows}
                    h2h_map[pair] = (wins.get(f1, 0), wins.get(f2, 0))
        _cs_conn.close()
    except Exception:
        pass

    upcoming_lines = []
    for m in upcoming[:10]:
        prefix = "TODAY → " if m["date"] == today_str else ""
        f1, f2 = m["team1"], m["team2"]
        h2h_suffix = ""
        if (f1, f2) in h2h_map:
            w1, w2 = h2h_map[(f1, f2)]
            h2h_suffix = f" (H2H: {_short(f1)} {w1}-{w2} {_short(f2)})"
        upcoming_lines.append(
            f"  {prefix}M{m['match_number']}: {_short(f1)} vs"
            f" {_short(f2)} on {m['date']}{h2h_suffix}"
        )
    upcoming_text = "\n".join(upcoming_lines) or "  None remaining"

    # LLM call
    from pipeline.llm.gemini import GeminiProvider

    provider = GeminiProvider()
    prompt = _USER_PROMPT.format(
        matches_played=matches_played,
        standings_text=standings_text,
        upcoming_text=upcoming_text,
        today=today_str,
    )

    result = await provider.generate(
        prompt,
        system=_SYSTEM_PROMPT,
        temperature=0.5,
        response_schema=ScenariosResponse,
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
            "  [yellow]Scenarios: failed to parse"
            " LLM response[/yellow]"
        )
        return None

    # Cache
    cache.put(_CACHE_TASK, cache_key_v, {
        "parsed": parsed,
        "usage": result.get("usage", {}),
    })

    console.print(
        "  [green]Scenarios: playoff analysis generated[/green]"
    )
    return parsed
