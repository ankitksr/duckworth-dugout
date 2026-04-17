"""The Archive — cricket historian desk.

Trigger: a structural storyline with a numeric handle (unbeaten start,
winless collapse, player approaching an all-time milestone, captain
crossing a threshold). The desk stays silent when no trigger fires.

Voice: forensic comparison, not nostalgia. Every dispatch names the
precedent team, year, match number, then-numbers, and end-of-season
numbers. Anti-pattern block in the system prompt forbids "class of",
"echoes of", "storied", etc.

Model: Pro @ 0.3 — voice compression matters on the historian desk. Every
dispatch is a comparative one-liner with a specific year + team + numbers;
Flash tends to blur the comparison into nostalgia.
"""

import hashlib

from pipeline.intel.prompts import load_prompt
from pipeline.intel.wire_generators import (
    HASH_VERSION,
    GeneratorContext,
    WireGenerator,
)
from pipeline.ipl.franchise_metadata import IPL_FRANCHISES

_SHORT = {fid: d["short_name"] for fid, d in IPL_FRANCHISES.items() if not d.get("defunct")}


def _nrr_to_float(value) -> float:
    """Coerce NRR ('+1.067' / '-0.804' / 1.07) to float. Returns 0.0 on fail."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lstrip("+")
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


class TheArchiveGenerator(WireGenerator):
    SOURCE = "archive"
    TOOLS = [
        "get_team_results",
        "get_player_career_stats",
        "get_remaining_schedule",
    ]
    MODEL = "pro"
    TEMPERATURE = 0.3

    def _triggers(self, ctx: GeneratorContext) -> list[str]:
        """Return active structural triggers. Empty list → no run.

        Each trigger is a stable string so the hash is deterministic
        across syncs with the same underlying state. NRR is rounded to
        one decimal to prevent the band from thrashing mid-match.
        """
        triggers: list[str] = []

        for s in ctx.standings or []:
            played = s.get("played", 0) or 0
            wins = s.get("wins", 0) or 0
            losses = s.get("losses", 0) or 0
            nrr = _nrr_to_float(s.get("nrr"))
            short = s.get("short_name", "?")

            # Unbeaten start — no losses after ≥3 played
            if losses == 0 and played >= 3:
                triggers.append(f"unbeaten:{short}:p{played}")

            # Winless collapse — no wins, ≥4 played, NRR ≤ -0.8
            if wins == 0 and played >= 4 and nrr <= -0.8:
                triggers.append(f"winless:{short}:p{played}:nrr{round(nrr, 1)}")

        # Cap-leader milestone chases (orange / purple). Include team in the
        # trigger so precedent dispatches can't invert player→team under the
        # scout-class failure mode.
        if ctx.caps:
            for key in ("orange_cap", "purple_cap"):
                entries = ctx.caps.get(key, []) or []
                if entries:
                    top = entries[0]
                    triggers.append(
                        f"{key}:{top.get('player', '?')}"
                        f" ({top.get('team_short', '?')}):{top.get('stat', '')}"
                    )

        return triggers

    def should_run(self, ctx: GeneratorContext) -> bool:
        return len(self._triggers(ctx)) > 0

    def context_hash(self, ctx: GeneratorContext) -> str:
        parts = [HASH_VERSION, self.SOURCE]
        parts.extend(sorted(self._triggers(ctx)))
        if ctx.schedule:
            completed = sum(
                1 for m in ctx.schedule if m.get("status") == "completed"
            )
            parts.append(f"completed:{completed}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def build_context(self, ctx: GeneratorContext) -> str:
        parts: list[str] = []

        if ctx.standings:
            lines = [
                f"  {s['position']}. {s['short_name']}"
                f" P={s['played']} W={s['wins']} L={s['losses']}"
                f" NRR={s['nrr']} Pts={s['points']}"
                for s in ctx.standings
            ]
            parts.append("CURRENT STANDINGS:\n" + "\n".join(lines))

        if ctx.caps:
            for key, label in [
                ("orange_cap", "ORANGE CAP"),
                ("purple_cap", "PURPLE CAP"),
            ]:
                entries = ctx.caps.get(key, [])[:3] if ctx.caps else []
                if entries:
                    parts.append(
                        f"{label}: "
                        + ", ".join(
                            f"{e['player']} ({e['team_short']}) {e['stat']}"
                            for e in entries
                        )
                    )

        triggers = self._triggers(ctx)
        if triggers:
            parts.append(
                "ACTIVE TRIGGERS (each must anchor at most one dispatch):\n"
                + "\n".join(f"  - {t}" for t in triggers)
            )

        return "\n\n".join(parts)

    def system_prompt(self) -> str:
        return load_prompt("wire_archive_system.md")

    def user_prompt(
        self, ctx: GeneratorContext, focused_context: str, previous: str
    ) -> str:
        template = load_prompt("wire_archive_user.md")
        return template.format(
            base_context=ctx.base_context,
            focused_context=focused_context,
            previous_entries=previous,
            franchise_ids="rcb, mi, csk, dc, pbks, srh, kkr, rr, lsg, gt",
        )
