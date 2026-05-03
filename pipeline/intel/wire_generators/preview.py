"""Matchday Preview — tactical previews for the upcoming fixture window.

Trigger: any sync that sees a scheduled/live fixture inside the window
(today + next two days). Voice: tactical prediction — takes a side,
specific matchups. Model: Pro @ 0.4 — tool use for H2H/matchup
verification, low temp to keep the model anchored to the fixtures it
was given.

Each emitted dispatch is tagged with `_match_day` = the target match's
date so daily-reset only retires it once that match has been played,
not the night it was filed.
"""

import hashlib
import re

from rich.console import Console

from pipeline.intel.prompts import load_prompt
from pipeline.intel.wire_generators import (
    HASH_VERSION,
    GeneratorContext,
    WireGenerator,
    _apply_grounding_filter,
)
from pipeline.ipl.franchise_metadata import IPL_FRANCHISES

console = Console()

_SHORT = {fid: d["short_name"] for fid, d in IPL_FRANCHISES.items() if not d.get("defunct")}

_PREVIEW_GROUNDING_TYPES = {"matchup", "venue", "phase_edge", "chase_math"}
_PREVIEW_COP_OUTS = (
    "should be a good game",
    "anyone's game",
    "could go either way",
    "mouth-watering",
    "recipe for a thriller",
)


def _preview_specificity_check(item: dict) -> str | None:
    """Preview detail must name >=2 capitalized tokens (players/teams/venues).

    Cheap specificity proxy — kills "the middle overs decide it" style
    vague cards without requiring a full roster join.
    """
    g = item.get("grounding") or {}
    detail = g.get("detail") or ""
    caps = re.findall(r"\b[A-Z][A-Za-z'.-]{2,}\b", detail)
    if len(caps) < 2:
        return "grounding.detail needs >=2 capitalized tokens (players/teams/venue)"
    return None


class MatchdayPreviewGenerator(WireGenerator):
    SOURCE = "preview"
    TOOLS = [
        "get_recent_h2h", "get_batter_vs_bowler",
        "get_phase_stats", "get_venue_stats", "get_squad_detail",
    ]
    MODEL = "pro"
    TEMPERATURE = 0.4

    def context_hash(self, ctx: GeneratorContext) -> str:
        parts = [HASH_VERSION, self.SOURCE]
        # Hash anchors on the upcoming window — same fixture set yields
        # the same hash, so a re-sync inside the same day hits already_ran
        # and skips. The window naturally rolls forward each midnight,
        # invalidating the hash and triggering a fresh run.
        for m in ctx.upcoming_matches:
            parts.append(f"match:{m.date}:{m.team1}v{m.team2}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def should_run(self, ctx: GeneratorContext) -> bool:
        return bool(ctx.upcoming_matches)

    def build_context(self, ctx: GeneratorContext) -> str:
        if not ctx.upcoming_matches:
            return "(No upcoming matches)"

        parts: list[str] = []
        for m in ctx.upcoming_matches:
            t1 = _SHORT.get(m.team1, m.team1.upper())
            t2 = _SHORT.get(m.team2, m.team2.upper())
            line = f"M{m.match_number} [{m.date}]: {t1} vs {t2} at {m.venue}"
            if m.city:
                line += f" ({m.city})"
            line += f", {m.time}"
            parts.append(line)

        return "UPCOMING FIXTURES:\n" + "\n".join(parts)

    def filter_items(
        self, ctx: GeneratorContext, items: list[dict]
    ) -> list[dict]:
        """Two-stage filter: fixture anchoring (hard drop always), then
        grounding contract (warn-or-drop per _STRICT_GROUNDING).

        The Pro model occasionally hallucinates previews for matches that
        already happened or for arbitrary fixtures. Fixture anchoring is a
        hallucination guard — always hard-drops regardless of the strict
        flag. Grounding contract stacks on top.

        Surviving items are tagged with `_match_day` = the target match's
        date so the wire row outlives the day it was filed; the daily
        reset will retire it the morning after that match has played.
        """
        pair_to_date: dict[frozenset[str], str] = {
            frozenset((m.team1, m.team2)): m.date
            for m in ctx.upcoming_matches
        }
        if not pair_to_date:
            if items:
                console.print(
                    f"  [yellow]Wire/{self.SOURCE}: dropped {len(items)} "
                    f"dispatch(es) — no upcoming fixtures[/yellow]"
                )
            return []

        fixture_kept: list[dict] = []
        dropped = 0
        for item in items:
            teams = item.get("teams") or []
            key = frozenset(teams) if len(teams) == 2 else None
            if key is None or key not in pair_to_date:
                dropped += 1
                continue
            item["_match_day"] = pair_to_date[key]
            fixture_kept.append(item)
        if dropped:
            console.print(
                f"  [yellow]Wire/{self.SOURCE}: dropped {dropped} "
                f"dispatch(es) not matching the upcoming window[/yellow]"
            )

        return _apply_grounding_filter(
            self.SOURCE, fixture_kept,
            type_enum=_PREVIEW_GROUNDING_TYPES,
            cop_outs=_PREVIEW_COP_OUTS,
            extra_checks=[_preview_specificity_check],
        )

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
