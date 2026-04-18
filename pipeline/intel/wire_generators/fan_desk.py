"""Fan Desk — plain-English voice for the casual cricket fan.

Trigger: structural (mirrors archive.py). Fires only when a real fan-worthy
moment lands — a decisive result, a match-day morning, a player milestone,
or a season inflection.

Voice: clear, warm, no jargon without gloss. One feeling per dispatch.

Model: Flash @ 0.8 — plain English is harder than jargon, so slightly
hotter than the analytical desks to keep prose alive.

Runs last (phase 3) in wire.py, after The Take, so it sees every other
desk's dispatches via `set_other_outputs` and can avoid overlap.
"""

import hashlib
import re
from datetime import datetime

from pipeline.clock import IST
from pipeline.intel.prompts import load_prompt
from pipeline.intel.wire_generators import (
    HASH_VERSION,
    GeneratorContext,
    WireGenerator,
    _apply_grounding_filter,
)
from pipeline.ipl.franchise_metadata import IPL_FRANCHISES

_SHORT = {fid: d["short_name"] for fid, d in IPL_FRANCHISES.items() if not d.get("defunct")}

_FAN_GROUNDING_TYPES = {
    "fan_joy", "fan_worry", "fan_watch", "fan_remember", "fan_alert",
}

# Jargon that must be glossed in-sentence. Each key maps to regex fragments
# that count as a valid in-sentence gloss.
_JARGON_GLOSS: dict[str, tuple[str, ...]] = {
    "NRR": ("run rate", "average margin", "net score", "scoring rate", "net run"),
    "net run rate": ("run rate", "average margin", "net score", "scoring rate"),
    "SR": ("runs per ball", "strike rate", "scoring rate", "balls per"),
    "strike rate": ("runs per ball", "scoring rate", "balls per"),
    "Econ": ("runs per over", "economy", "how many runs"),
    "economy rate": ("runs per over", "how many runs"),
    "cap race": (
        "top scorer", "top wicket", "leading run",
        "leading wicket", "most runs", "most wickets",
    ),
    "playoff math": ("to reach", "to qualify", "to stay alive", "top four"),
    "mathematical elimination": ("out of the race", "out of the tournament", "can no longer"),
    "overseas slot": ("foreign player", "international player"),
    "phase-split": ("in each phase", "by overs", "by segment"),
    "DLS": ("rain-adjusted", "rain rule"),
}

# Words that are OK without gloss (widely understood by casual fans).
_JARGON_OK_WITHOUT_GLOSS = {"powerplay", "death overs", "boundaries", "sixes", "wickets"}


def _sentence_of(text: str, span: tuple[int, int]) -> str:
    """Return the sentence (split on .!?) that contains the given char span."""
    start, end = span
    # Walk back to the preceding sentence delimiter
    left = max(
        text.rfind(".", 0, start), text.rfind("!", 0, start),
        text.rfind("?", 0, start), -1,
    )
    # Walk forward to the next delimiter
    right = min(
        (i for i in (text.find(".", end), text.find("!", end), text.find("?", end))
         if i != -1),
        default=len(text),
    )
    return text[left + 1: right].strip()


def _jargon_check(item: dict) -> str | None:
    """Reject dispatches that use cricket jargon without an in-sentence gloss.

    For each jargon token that appears, confirm the enclosing sentence also
    contains at least one of its gloss fragments. A match is case-insensitive;
    the first failure is reported. Allowlist tokens (powerplay, death overs)
    never trip this check.
    """
    prose = f"{item.get('headline', '')}. {item.get('text', '')}"
    for token, glosses in _JARGON_GLOSS.items():
        for m in re.finditer(rf"\b{re.escape(token)}\b", prose, re.IGNORECASE):
            sentence = _sentence_of(prose, m.span()).lower()
            if not any(g.lower() in sentence for g in glosses):
                return f"jargon {token!r} without in-sentence gloss"
    return None


def _single_team_check(item: dict) -> str | None:
    teams = item.get("teams") or []
    if len(teams) != 1:
        return f"fan_desk dispatches must target exactly 1 team (got {len(teams)})"
    return None


def _convergence_check_factory(other_outputs: list[dict]):
    """Build a closure that rejects fan_alert cards on already-covered teams.

    The other four fan categories (joy/worry/watch/remember) are always
    permitted even on covered teams — those are emotional angles the
    analysts don't write. Only fan_alert, which is the "here's a fact"
    register closest to analysis, is gated.
    """
    covered_teams: set[str] = set()
    for out in other_outputs:
        for t in out.get("teams", []) or []:
            covered_teams.add(t)

    def _check(item: dict) -> str | None:
        if (item.get("category") or "").strip().lower() != "fan_alert":
            return None
        teams = item.get("teams") or []
        if any(t in covered_teams for t in teams):
            return f"fan_alert on already-covered team (teams={teams})"
        return None

    return _check


class FanDeskGenerator(WireGenerator):
    SOURCE = "fan_desk"
    TOOLS = [
        "get_team_results", "get_player_career_stats",
        "get_player_season_stats",
    ]
    MODEL = "flash"
    TEMPERATURE = 0.8

    def __init__(self) -> None:
        self._other_outputs: list[dict] = []

    def set_other_outputs(self, outputs: list[dict]) -> None:
        """Called by the orchestrator with every dispatch filed earlier this
        cycle (phase-1 desks + The Take). Used both for the convergence guard
        at filter time and as context in the user prompt.
        """
        self._other_outputs = outputs or []

    # ── Triggers (structural; mirrors archive.py pattern) ─────────

    def _ist_hour(self) -> int:
        return datetime.now(IST).hour

    def _is_match_day_morning(self, ctx: GeneratorContext) -> bool:
        return self._ist_hour() < 12 and bool(ctx.today_matches)

    def _decisive_results(self, ctx: GeneratorContext) -> list[str]:
        """Find recently completed matches with a fan-worthy result margin.

        Uses the result string since it's the ground truth carried on each
        scheduled match. "by 7 wickets" / "by 50 runs" or bigger = decisive.
        """
        out: list[str] = []
        for m in (ctx.schedule or [])[-6:]:  # last 6 scheduled entries
            if m.get("status") != "completed":
                continue
            result = (m.get("result") or "").lower()
            # "won by N wickets" — 7, 8, 9, 10 wickets = decisive
            wkts = re.search(r"by (\d+)\s*wicket", result)
            runs = re.search(r"by (\d+)\s*run", result)
            if wkts and int(wkts.group(1)) >= 7:
                out.append(f"decisive_win_wkts:M{m.get('match_number')}:{result}")
            elif runs and int(runs.group(1)) >= 50:
                out.append(f"decisive_win_runs:M{m.get('match_number')}:{result}")
        return out

    def _season_inflections(self, ctx: GeneratorContext) -> list[str]:
        """Teams that just clinched or were just eliminated.

        Uses the scenarios.json file written by the scenarios panel — if
        available — for the elimination_watch block. Coarse signal; the LLM
        decides whether to write `fan_alert` for it.
        """
        from pipeline.intel.wire_generators import _load_json
        scenarios = _load_json("scenarios.json")
        if not scenarios:
            return []
        out: list[str] = []
        for e in (scenarios.get("elimination_watch") or []):
            risk = (e.get("risk") or "").lower()
            if risk in ("terminal", "near_terminal", "critical"):
                out.append(f"inflection_eliminated:{e.get('team', '?')}")
        return out

    def _triggers(self, ctx: GeneratorContext) -> list[str]:
        triggers: list[str] = []
        if self._is_match_day_morning(ctx):
            for m in ctx.today_matches:
                t1 = _SHORT.get(m.team1, m.team1)
                t2 = _SHORT.get(m.team2, m.team2)
                triggers.append(f"match_day_morning:{t1}_vs_{t2}@{m.venue}")
        triggers.extend(self._decisive_results(ctx))
        triggers.extend(self._season_inflections(ctx))
        return triggers

    def should_run(self, ctx: GeneratorContext) -> bool:
        return bool(self._triggers(ctx))

    def context_hash(self, ctx: GeneratorContext) -> str:
        parts = [HASH_VERSION, self.SOURCE]
        parts.extend(sorted(self._triggers(ctx)))
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    # ── Context ──────────────────────────────────────────────────

    def build_context(self, ctx: GeneratorContext) -> str:
        parts: list[str] = []

        if ctx.today_matches:
            today_lines = []
            for m in ctx.today_matches:
                t1 = _SHORT.get(m.team1, m.team1)
                t2 = _SHORT.get(m.team2, m.team2)
                today_lines.append(f"  {t1} vs {t2} at {m.venue}, {m.time}")
            parts.append("TONIGHT:\n" + "\n".join(today_lines))

        # Last 3 completed matches — compact, result-focused
        if ctx.schedule:
            completed = [m for m in ctx.schedule if m.get("status") == "completed"]
            recent = completed[-3:]
            if recent:
                lines = []
                for m in recent:
                    t1 = _SHORT.get(m.get("team1", ""), m.get("team1", ""))
                    t2 = _SHORT.get(m.get("team2", ""), m.get("team2", ""))
                    hero = m.get("hero_name") or ""
                    hero_bit = f" (POTM: {hero})" if hero else ""
                    lines.append(
                        f"  M{m.get('match_number')}: {t1} vs {t2} — "
                        f"{m.get('result', '?')}{hero_bit}"
                    )
                parts.append("RECENT RESULTS:\n" + "\n".join(lines))

        return "\n\n".join(parts) if parts else "(no fan-worthy context yet)"

    def system_prompt(self) -> str:
        return load_prompt("wire_fan_desk_system.md")

    def user_prompt(
        self, ctx: GeneratorContext, focused_context: str, previous: str
    ) -> str:
        template = load_prompt("wire_fan_desk_user.md")
        active_triggers = self._triggers(ctx)
        triggers_block = (
            "\n".join(f"  - {t}" for t in active_triggers)
            if active_triggers else "(no triggers active)"
        )
        other_text = "(No dispatches from other desks yet)"
        if self._other_outputs:
            other_text = "\n".join(
                f"- [{item.get('source', '?')}:{item.get('category', '?')}] "
                f"{item.get('headline', '')}: {item.get('text', '')}"
                for item in self._other_outputs
            )
        return template.format(
            base_context=ctx.base_context,
            focused_context=focused_context,
            active_triggers=triggers_block,
            other_wire_output=other_text,
            previous_entries=previous,
            franchise_ids="rcb, mi, csk, dc, pbks, srh, kkr, rr, lsg, gt",
        )

    def filter_items(
        self, ctx: GeneratorContext, items: list[dict]
    ) -> list[dict]:
        convergence_check = _convergence_check_factory(self._other_outputs)
        return _apply_grounding_filter(
            self.SOURCE, items,
            type_enum=_FAN_GROUNDING_TYPES,
            detail_min_chars=10,
            cop_outs=(),  # Fan Desk uses jargon-gloss rule instead of phrase ban
            extra_checks=[_single_team_check, _jargon_check, convergence_check],
        )
