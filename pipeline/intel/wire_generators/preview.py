"""Matchday Preview — tactical previews for today's fixtures.

Trigger: morning time-window on match days.
Voice: tactical prediction — takes a side, specific matchups.
Model: Pro @ 0.4 — tool use for H2H/matchup verification, low temp to
keep the model anchored to the fixtures it was given.
"""

import hashlib
from datetime import datetime, timezone

from rich.console import Console

from pipeline.intel.prompts import load_prompt
from pipeline.intel.wire_generators import (
    HASH_VERSION,
    GeneratorContext,
    WireGenerator,
    hash_time_bucket,
)
from pipeline.ipl.franchise_metadata import IPL_FRANCHISES

console = Console()

_SHORT = {fid: d["short_name"] for fid, d in IPL_FRANCHISES.items() if not d.get("defunct")}


def _is_morning() -> bool:
    utc_minutes = datetime.now(timezone.utc).hour * 60 + datetime.now(timezone.utc).minute
    ist_minutes = utc_minutes + 330  # IST = UTC + 5:30
    ist_hour = (ist_minutes // 60) % 24
    return ist_hour < 15  # morning + early afternoon — preview window


class MatchdayPreviewGenerator(WireGenerator):
    SOURCE = "preview"
    TOOLS = [
        "get_recent_h2h", "get_batter_vs_bowler",
        "get_phase_stats", "get_venue_stats", "get_squad_detail",
    ]
    MODEL = "pro"
    TEMPERATURE = 0.4

    def context_hash(self, ctx: GeneratorContext) -> str:
        parts = [HASH_VERSION, self.SOURCE, hash_time_bucket()]
        for m in ctx.today_matches:
            parts.append(f"match:{m.team1}v{m.team2}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def should_run(self, ctx: GeneratorContext) -> bool:
        return bool(ctx.today_matches) and _is_morning()

    def build_context(self, ctx: GeneratorContext) -> str:
        if not ctx.today_matches:
            return "(No matches today)"

        parts: list[str] = []
        for m in ctx.today_matches:
            t1 = _SHORT.get(m.team1, m.team1.upper())
            t2 = _SHORT.get(m.team2, m.team2.upper())
            line = f"M{m.match_number}: {t1} vs {t2} at {m.venue}"
            if m.city:
                line += f" ({m.city})"
            line += f", {m.time}"
            parts.append(line)

        return "TODAY'S FIXTURES:\n" + "\n".join(parts)

    def filter_items(
        self, ctx: GeneratorContext, items: list[dict]
    ) -> list[dict]:
        """Drop dispatches whose team-pair doesn't match a fixture today.

        The Pro model occasionally hallucinates previews for matches that
        already happened or for arbitrary fixtures. We anchor every dispatch
        to a real today's-fixture pair.
        """
        valid_pairs = {frozenset((m.team1, m.team2)) for m in ctx.today_matches}
        if not valid_pairs:
            if items:
                console.print(
                    f"  [yellow]Wire/{self.SOURCE}: dropped {len(items)} "
                    f"dispatch(es) — no fixtures today[/yellow]"
                )
            return []

        kept: list[dict] = []
        dropped = 0
        for item in items:
            teams = item.get("teams") or []
            if len(teams) != 2 or frozenset(teams) not in valid_pairs:
                dropped += 1
                continue
            kept.append(item)
        if dropped:
            console.print(
                f"  [yellow]Wire/{self.SOURCE}: dropped {dropped} "
                f"dispatch(es) not matching today's fixtures[/yellow]"
            )
        return kept

    def system_prompt(self) -> str:
        return load_prompt("wire_preview_system.md")

    def user_prompt(self, ctx: GeneratorContext, focused_context: str, previous: str) -> str:
        template = load_prompt("wire_preview_user.md")
        return template.format(
            base_context=ctx.base_context,
            focused_context=focused_context,
            previous_entries=previous,
            franchise_ids="rcb, mi, csk, dc, pbks, srh, kkr, rr, lsg, gt",
        )
