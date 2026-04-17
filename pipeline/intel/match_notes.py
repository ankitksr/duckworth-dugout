"""Match Editorial Notes — one-liner editorial context per completed match.

Incremental generator: reads the existing `match-notes.json` from disk and
only calls the LLM for matches without a note. A completed match's data is
immutable once stored in the schedule, so its note is written exactly once
and stays stable forever (no voice drift across syncs).

Per-match Pro call includes:
  - current standings + cap race (shared context)
  - prior notes for the two teams in this match (voice + callback hook)
  - the match detail block (same grounded format as before)

Usage:
    notes = await generate_match_notes(season)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from rich.console import Console

from pipeline.config import DATA_DIR, GEMINI_MODEL_PRO
from pipeline.intel.prompts import load_prompt
from pipeline.intel.schemas import MatchNoteResponse

console = Console()

# Cap how many prior notes per involved team we send as voice reference.
# Late season, a team plays up to 14 league matches — scoping to the most
# recent few keeps the prompt focused and costs bounded.
_PRIOR_NOTES_PER_TEAM = 3

_SYSTEM_PROMPT = load_prompt("match_notes_system.md")
_USER_PROMPT = load_prompt("match_notes_user.md")


def _load_json(filename: str) -> Any:
    path = DATA_DIR / "war-room" / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _load_existing_notes() -> dict[int, str]:
    """Load previously-generated match notes keyed by int match_number.

    Reads the canonical `data/war-room/match-notes.json` (the pipeline
    writer writes both data/ and frontend/public copies with identical
    content, so either works — we use data/ as the source of truth).
    JSON only has string keys, so int-ify on load.
    """
    raw = _load_json("match-notes.json")
    if not isinstance(raw, dict):
        return {}
    result: dict[int, str] = {}
    for k, v in raw.items():
        if isinstance(v, str) and v.strip():
            try:
                result[int(k)] = v.strip()
            except (TypeError, ValueError):
                continue
    return result


def _format_match_detail(m: dict) -> str:
    """Render one completed match as a grounded multi-line block.

    Mirrors the per-innings tagging the old mega-prompt used — the LLM
    never has to infer team attribution from the narrative.
    """
    t1 = m["team1"].upper()
    t2 = m["team2"].upper()
    lines = [
        f"M{m['match_number']}: {t1} vs {t2}"
        f" — {m.get('score1', '?')} vs {m.get('score2', '?')}"
        f" — {m.get('result', '?')}"
    ]
    if m.get("hero_name"):
        tail = f"  (POTM: {m['hero_name']}"
        if m.get("hero_stat"):
            tail += f" {m['hero_stat']}"
        tail += ")"
        lines[-1] += tail
    if m.get("toss"):
        lines.append(f"  Toss: {m['toss']}")
    if m.get("wiki_notes"):
        lines.append(f"  Wikipedia notes: {m['wiki_notes']}")

    b1, w1 = m.get("top_batter1"), m.get("top_bowler1")
    if b1 or w1:
        parts: list[str] = []
        if b1:
            not_out = "*" if b1.get("not_out") else ""
            parts.append(
                f"{b1['name']} ({t1}) {b1['runs']}{not_out}({b1['balls']})"
            )
        if w1:
            parts.append(f"{w1['name']} ({t2}) {w1['wickets']}/{w1['runs']}")
        lines.append(f"  Inn 1 ({t1} bat): {' | '.join(parts)}")

    b2, w2 = m.get("top_batter2"), m.get("top_bowler2")
    if b2 or w2:
        parts = []
        if b2:
            not_out = "*" if b2.get("not_out") else ""
            parts.append(
                f"{b2['name']} ({t2}) {b2['runs']}{not_out}({b2['balls']})"
            )
        if w2:
            parts.append(f"{w2['name']} ({t1}) {w2['wickets']}/{w2['runs']}")
        lines.append(f"  Inn 2 ({t2} bat): {' | '.join(parts)}")

    return "\n".join(lines)


def _prior_notes_block(
    target: dict,
    completed: list[dict],
    notes: dict[int, str],
) -> str:
    """Pull the most recent `_PRIOR_NOTES_PER_TEAM` notes for each of the
    two teams in the target match. Dedupe, sort by match number.
    """
    target_num = target["match_number"]
    teams = {target["team1"], target["team2"]}

    picked: dict[int, dict] = {}
    for team in teams:
        team_matches = sorted(
            (
                m for m in completed
                if m["match_number"] != target_num
                and team in (m["team1"], m["team2"])
                and m["match_number"] in notes
            ),
            key=lambda m: m["match_number"],
            reverse=True,
        )
        for m in team_matches[:_PRIOR_NOTES_PER_TEAM]:
            picked[m["match_number"]] = m

    if not picked:
        return "(no prior notes available — this is an early match of the season)"

    ordered = sorted(picked.values(), key=lambda m: m["match_number"])
    return "\n".join(
        f"M{m['match_number']} ({m['team1'].upper()} vs {m['team2'].upper()}): "
        f"{notes[m['match_number']]}"
        for m in ordered
    )


def _build_standings_context(standings: list[dict] | None) -> str:
    if not standings:
        return "(standings unavailable)"
    return "\n".join(
        f"{s.get('short_name', s['franchise_id'].upper())}:"
        f" #{s['position']} {s['wins']}W-{s['losses']}L"
        f" NRR={s['nrr']}"
        for s in standings
    )


async def _generate_one_note(
    provider,
    target: dict,
    completed: list[dict],
    notes: dict[int, str],
    standings_context: str,
    cap_context: str,
) -> str | None:
    """Single focused LLM call producing one editorial sentence."""
    prompt = _USER_PROMPT.format(
        standings_context=standings_context,
        cap_context=cap_context,
        prior_notes_context=_prior_notes_block(target, completed, notes),
        match_detail=_format_match_detail(target),
    )
    result = await provider.generate(
        prompt,
        system=_SYSTEM_PROMPT,
        temperature=0.7,
        response_schema=MatchNoteResponse,
        sub_key=f"M{target['match_number']}",
    )
    parsed = result.get("parsed") or {}
    note = (parsed.get("note") or "").strip()
    return note or None


async def generate_match_notes(season: str) -> dict[int, str] | None:
    """Generate editorial notes for any completed match without one.

    Returns the full `{match_number: note}` dict — including pre-existing
    notes unchanged. Returns None only when schedule is missing.
    """
    from pipeline.intel.live_context import (
        build_live_context,
        format_cap_race_block,
    )

    schedule = _load_json("schedule.json")
    if not schedule:
        return None

    completed = [m for m in schedule if m.get("status") == "completed"]
    if not completed:
        return None

    notes = _load_existing_notes()
    missing = [m for m in completed if m["match_number"] not in notes]

    if not missing:
        console.print(
            f"  [dim]Match notes: all {len(notes)} notes current — skipping LLM[/dim]"
        )
        return notes

    console.print(
        f"  [dim]Match notes: generating {len(missing)} note(s)"
        f" (existing: {len(notes)})[/dim]"
    )

    # Shared grounding — computed once, reused for every missing match.
    live_ctx = build_live_context(None, season)
    standings = _load_json("standings.json") or []
    standings_context = _build_standings_context(standings)
    cap_context = format_cap_race_block(live_ctx, per_cap=5) or "(no cap race data)"

    from pipeline.llm.gemini import GeminiProvider
    provider = GeminiProvider(model=GEMINI_MODEL_PRO, panel="match_notes")

    # Generate in match_number order so later matches see earlier notes
    # we just produced in their prior_notes context.
    missing.sort(key=lambda m: m["match_number"])
    produced = 0
    for m in missing:
        try:
            note = await _generate_one_note(
                provider, m, completed, notes,
                standings_context, cap_context,
            )
            if note:
                notes[m["match_number"]] = note
                produced += 1
            else:
                console.print(
                    f"  [yellow]Match notes M{m['match_number']}: empty response[/yellow]"
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Never let one bad match kill the batch — already-produced
            # notes will persist via the return value. Surface the
            # failure so it's visible in logs.
            console.print(
                f"  [yellow]Match notes M{m['match_number']}: {e}[/yellow]"
            )

    console.print(
        f"  [green]Match notes: {produced} new, {len(notes)} total[/green]"
    )
    return notes
