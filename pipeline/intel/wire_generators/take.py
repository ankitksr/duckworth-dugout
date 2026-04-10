"""The Take — cross-desk synthesis, season-arc threading, bigger picture.

Trigger: time-window rotation (runs after other generators).
Voice: the big-picture columnist — extends and ties together what other
desks have filed, never refutes them.
Model: Pro @ 0.95 — maximum creativity, high grounding via tool use.
"""

import hashlib
import json
from datetime import datetime, timezone

from pipeline.intel.prompts import load_prompt
from pipeline.intel.wire_generators import (
    HASH_VERSION,
    GeneratorContext,
    WireGenerator,
    hash_time_bucket,
)


def _time_window() -> str:
    utc_minutes = datetime.now(timezone.utc).hour * 60 + datetime.now(timezone.utc).minute
    ist_minutes = utc_minutes + 330  # IST = UTC + 5:30
    hour = (ist_minutes // 60) % 24
    if hour < 12:
        return "morning"
    if hour < 15:
        return "afternoon"
    if hour < 20:
        return "evening"
    return "night"


class TheTakeGenerator(WireGenerator):
    SOURCE = "take"
    TOOLS = [
        "get_team_results", "get_remaining_schedule",
        "get_cap_leaders", "get_player_season_stats",
    ]
    MODEL = "pro"
    TEMPERATURE = 0.95

    def context_hash(self, ctx: GeneratorContext) -> str:
        parts = [HASH_VERSION, self.SOURCE, hash_time_bucket()]
        parts.append(f"window:{_time_window()}")
        if ctx.standings:
            parts.append(json.dumps(
                [(s["short_name"], s["played"], s["wins"]) for s in ctx.standings],
                sort_keys=True,
            ))
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def should_run(self, ctx: GeneratorContext) -> bool:
        return bool(ctx.standings)

    def build_context(self, ctx: GeneratorContext) -> str:
        """Full season context — sees everything including other generators' output."""
        parts: list[str] = []

        # Season overview
        if ctx.standings:
            lines = [
                f"  {s['position']}. {s['short_name']}"
                f" P={s['played']} W={s['wins']} L={s['losses']}"
                f" NRR={s['nrr']}"
                for s in ctx.standings
            ]
            parts.append("STANDINGS:\n" + "\n".join(lines))

        # Cap race leaders (brief)
        if ctx.caps:
            for key, label in [("orange_cap", "ORANGE CAP"), ("purple_cap", "PURPLE CAP")]:
                entries = ctx.caps.get(key, [])[:3]
                if entries:
                    parts.append(f"{label}: " + ", ".join(
                        f"{e['player']} ({e['team_short']}) {e['stat']}" for e in entries
                    ))

        # Today's matches
        if ctx.today_matches:
            from pipeline.ipl.franchise_metadata import IPL_FRANCHISES
            _s = {f: d["short_name"] for f, d in IPL_FRANCHISES.items() if not d.get("defunct")}
            lines = [
                f"  {_s.get(m.team1, m.team1)} vs {_s.get(m.team2, m.team2)} at {m.venue}"
                for m in ctx.today_matches
            ]
            parts.append("TODAY:\n" + "\n".join(lines))

        parts.append(f"TIME WINDOW: {_time_window()}")

        return "\n\n".join(parts)

    def set_other_outputs(self, outputs: list[dict]) -> None:
        """Called by orchestrator with dispatches from other generators."""
        self._other_outputs = outputs

    def system_prompt(self) -> str:
        return load_prompt("wire_take_system.md")

    def user_prompt(self, ctx: GeneratorContext, focused_context: str, previous: str) -> str:
        template = load_prompt("wire_take_user.md")

        # Format other generators' outputs for context
        other_text = "(No dispatches from other generators yet)"
        if hasattr(self, "_other_outputs") and self._other_outputs:
            lines = []
            for item in self._other_outputs:
                lines.append(
                    f"- [{item.get('source', '?')}:{item.get('category', '?')}] "
                    f"{item['headline']}: {item['text']}"
                )
            other_text = "\n".join(lines)

        return template.format(
            base_context=ctx.base_context,
            focused_context=focused_context,
            other_wire_output=other_text,
            previous_entries=previous,
            franchise_ids="rcb, mi, csk, dc, pbks, srh, kkr, rr, lsg, gt",
            time_window=_time_window(),
        )
