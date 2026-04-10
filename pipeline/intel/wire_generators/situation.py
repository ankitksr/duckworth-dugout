"""Situation Room — tournament state, playoff math, NRR scenarios.

Trigger: standings or match completion changes.
Voice: cold, mathematical, Bloomberg-terminal energy.
Model: Flash @ 0.4 — precise, structured.
"""

import hashlib
import json

from pipeline.intel.prompts import load_prompt
from pipeline.intel.wire_generators import (
    HASH_VERSION,
    GeneratorContext,
    WireGenerator,
)


class SituationRoomGenerator(WireGenerator):
    SOURCE = "situation"
    TOOLS = ["get_team_results", "get_remaining_schedule"]
    MODEL = "flash"
    TEMPERATURE = 0.4

    def context_hash(self, ctx: GeneratorContext) -> str:
        parts = [HASH_VERSION, self.SOURCE]
        if ctx.standings:
            parts.append(json.dumps(
                [(s["short_name"], s["played"], s["wins"], s["nrr"])
                 for s in ctx.standings],
                sort_keys=True,
            ))
        if ctx.schedule:
            completed = sum(1 for m in ctx.schedule if m.get("status") == "completed")
            parts.append(f"completed:{completed}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def should_run(self, ctx: GeneratorContext) -> bool:
        return bool(ctx.standings)

    def build_context(self, ctx: GeneratorContext) -> str:
        parts: list[str] = []

        # Full standings with detail
        if ctx.standings:
            lines = [
                f"  {s['position']}. {s['short_name']}"
                f" P={s['played']} W={s['wins']} L={s['losses']}"
                f" NRR={s['nrr']} Pts={s['points']}"
                for s in ctx.standings
            ]
            parts.append("FULL STANDINGS:\n" + "\n".join(lines))

        # Scenarios / playoff picture if available
        from pipeline.intel.wire_generators import _load_json
        scenarios = _load_json("scenarios.json")
        if scenarios:
            brief = scenarios.get("situation_brief", "")
            if brief:
                parts.append(f"PLAYOFF PICTURE: {brief}")
            elim = scenarios.get("elimination_watch", [])
            if elim:
                elim_lines = [
                    f"  {e['team']} ({e['risk']}): {e['insight']}"
                    for e in elim[:6]
                ]
                parts.append("ELIMINATION WATCH:\n" + "\n".join(elim_lines))
            qual = scenarios.get("qualification_math", [])
            if qual:
                qual_lines = [f"  {q['tag']}: {q['fact']}" for q in qual[:5]]
                parts.append("QUALIFICATION MATH:\n" + "\n".join(qual_lines))

        return "\n\n".join(parts)

    def system_prompt(self) -> str:
        return load_prompt("wire_situation_system.md")

    def user_prompt(self, ctx: GeneratorContext, focused_context: str, previous: str) -> str:
        template = load_prompt("wire_situation_user.md")
        return template.format(
            base_context=ctx.base_context,
            focused_context=focused_context,
            previous_entries=previous,
            franchise_ids="rcb, mi, csk, dc, pbks, srh, kkr, rr, lsg, gt",
        )
