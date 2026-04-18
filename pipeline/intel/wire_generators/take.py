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
    _apply_grounding_filter,
    _jaccard,
)

_TAKE_GROUNDING_TYPES = {"connect", "extend", "reframe", "contrast"}
# Take's system prompt already bans several cop-outs; extend lightly here
# so the validator has teeth even if the prompt slips.
_TAKE_COP_OUTS = (
    "at the end of the day",
    "make no mistake",
    "mark my words",
    "write this down",
)


def _take_threads_check(item: dict) -> str | None:
    """Take dispatches must thread >=2 distinct signals.

    Threads live on grounding.threads (list[str]). Each thread must be >=20
    chars, and pairwise Jaccard overlap must stay below 0.5 — otherwise the
    "synthesis" is just one thread rephrased.
    """
    g = item.get("grounding") or {}
    threads = g.get("threads")
    if not isinstance(threads, list) or len(threads) < 2:
        return "threads missing or <2 entries"
    if any(not isinstance(t, str) or len(t.strip()) < 20 for t in threads):
        return "threads contain an entry <20 chars"
    for i, a in enumerate(threads):
        for b in threads[i + 1:]:
            if _jaccard(a, b) >= 0.5:
                return "threads overlap too heavily (single-thread disguise)"
    return None


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
        parts = [HASH_VERSION, self.SOURCE]
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

    def get_previous_entries(self, ctx: GeneratorContext, limit: int = 40) -> str:
        """Take's view of prior dispatches: own takes + cross-desk history.

        Windowed to PREVIOUS_ENTRIES_DAYS regardless of expired flag so
        yesterday's takes and cross-desk history remain visible for
        day-over-day repetition avoidance. Take's job is synthesis, so it
        needs (a) its own prior takes and (b) what other desks have filed.
        """
        own = ctx.conn.execute(
            f"""
            SELECT category, headline, text, CAST(generated_at AS DATE) AS d
            FROM war_room_wire
            WHERE season = ? AND source = 'take'
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
            WHERE season = ? AND source != 'take'
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
            "YOUR PRIOR TAKES — last "
            f"{self.PREVIOUS_ENTRIES_DAYS} days "
            "(do not restate any of these; if today's thread is already "
            "here, find a different angle or return []):\n"
            + own_text
            + "\n\nWHAT OTHER DESKS HAVE FILED — last "
            f"{self.PREVIOUS_ENTRIES_DAYS} days "
            "(synthesize across these; do not just rephrase one):\n"
            + cross_text
        )

    def filter_items(
        self, ctx: GeneratorContext, items: list[dict]
    ) -> list[dict]:
        # Take's grounding uses `threads` (a list) instead of the generic
        # `detail` field — the threads check enforces the specificity
        # contract, so skip the detail-length gate by setting it to 0.
        return _apply_grounding_filter(
            self.SOURCE, items,
            type_enum=_TAKE_GROUNDING_TYPES,
            detail_min_chars=0,
            cop_outs=_TAKE_COP_OUTS,
            extra_checks=[_take_threads_check],
        )

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
