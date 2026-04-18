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
    _apply_grounding_filter,
)

_SITUATION_GROUNDING_TYPES = {"inflection", "threshold", "pattern", "projection"}
_SITUATION_COP_OUTS = (
    "at the end of the day",
    "uphill battle",
    "mountain to climb",
    "things are looking tough",
)


class SituationRoomGenerator(WireGenerator):
    SOURCE = "situation"
    TOOLS = ["get_team_results", "get_remaining_schedule"]
    MODEL = "flash"
    TEMPERATURE = 0.4

    def context_hash(self, ctx: GeneratorContext) -> str:
        # NRR is intentionally excluded — it ticks on every match and would
        # cause a full LLM regeneration mid-day even when no result has
        # actually changed. Wins/losses + completed count are the right
        # signal: situation only re-runs when a match result lands.
        parts = [HASH_VERSION, self.SOURCE]
        if ctx.standings:
            parts.append(json.dumps(
                [(s["short_name"], s["played"], s["wins"])
                 for s in ctx.standings],
                sort_keys=True,
            ))
        if ctx.schedule:
            completed = sum(1 for m in ctx.schedule if m.get("status") == "completed")
            parts.append(f"completed:{completed}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def should_run(self, ctx: GeneratorContext) -> bool:
        return bool(ctx.standings)

    def get_previous_entries(self, ctx: GeneratorContext, limit: int = 40) -> str:
        """Situation sees its own prior entries AND what other desks have
        already filed on the same mathematical fact.

        Windowed to PREVIOUS_ENTRIES_DAYS regardless of expired flag so
        yesterday's KKR-extinction dispatch is still visible even after
        midnight expiry. Situation and take both tend to write about the
        same elimination / qualification story from different angles.
        """
        own = ctx.conn.execute(
            f"""
            SELECT category, headline, text, CAST(generated_at AS DATE) AS d
            FROM war_room_wire
            WHERE season = ? AND source = 'situation'
              AND generated_at >= (current_timestamp - INTERVAL '{self.PREVIOUS_ENTRIES_DAYS} days')
            ORDER BY generated_at DESC
            LIMIT ?
            """,
            [ctx.season, limit],
        ).fetchall()
        cross = ctx.conn.execute(
            f"""
            SELECT source, category, headline, text, CAST(generated_at AS DATE) AS d
            FROM war_room_wire
            WHERE season = ? AND source != 'situation'
              AND generated_at >= (current_timestamp - INTERVAL '{self.PREVIOUS_ENTRIES_DAYS} days')
            ORDER BY generated_at DESC
            LIMIT 50
            """,
            [ctx.season],
        ).fetchall()
        own_text = (
            "\n".join(f"- [{r[3]}] [{r[0]}] {r[1]}: {r[2]}" for r in own)
            or "(none yet)"
        )
        cross_text = (
            "\n".join(f"- [{r[4]}] [{r[0]}:{r[1]}] {r[2]}: {r[3]}" for r in cross)
            or "(none yet)"
        )
        return (
            "YOUR PRIOR SITUATION ROOM DISPATCHES — last "
            f"{self.PREVIOUS_ENTRIES_DAYS} days "
            "(do not restate any of these; if the same team/claim shape "
            "is already here, file on a different team or advance the "
            "thread with what has just changed):\n"
            + own_text
            + "\n\nWHAT OTHER DESKS HAVE ALREADY FILED ON RELATED MATH "
            f"— last {self.PREVIOUS_ENTRIES_DAYS} days "
            "(do not duplicate a claim already on the wire from another "
            "desk):\n"
            + cross_text
        )

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

    def filter_items(
        self, ctx: GeneratorContext, items: list[dict]
    ) -> list[dict]:
        return _apply_grounding_filter(
            self.SOURCE, items,
            type_enum=_SITUATION_GROUNDING_TYPES,
            cop_outs=_SITUATION_COP_OUTS,
        )

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
