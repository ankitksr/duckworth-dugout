"""Scout Report — player performances, form trends, cap races, matchup data.

Trigger: match completion (new stats become available).
Voice: scouting report — specific, phase-split aware, comparative.
Model: Pro @ 0.7 — analytical, connects dots across performances.
"""

import hashlib

from pipeline.intel.prompts import load_prompt
from pipeline.intel.wire_generators import (
    HASH_VERSION,
    GeneratorContext,
    WireGenerator,
    _load_json,
    hash_time_bucket,
)
from pipeline.ipl.franchise_metadata import IPL_FRANCHISES

_SHORT = {fid: d["short_name"] for fid, d in IPL_FRANCHISES.items() if not d.get("defunct")}


class ScoutReportGenerator(WireGenerator):
    SOURCE = "scout"
    TOOLS = [
        "get_phase_stats", "get_batter_vs_bowler",
        "get_player_career_stats", "get_player_season_stats",
        "get_cap_leaders", "get_squad_detail",
    ]
    MODEL = "pro"
    TEMPERATURE = 0.7

    def context_hash(self, ctx: GeneratorContext) -> str:
        parts = [HASH_VERSION, self.SOURCE, hash_time_bucket()]
        # Sensitive to match completions and cap race changes
        if ctx.schedule:
            completed = sum(1 for m in ctx.schedule if m.get("status") == "completed")
            parts.append(f"completed:{completed}")
        if ctx.caps:
            oc = ctx.caps.get("orange_cap", [])
            pc = ctx.caps.get("purple_cap", [])
            if oc:
                parts.append(f"oc:{oc[0].get('player', '')}:{oc[0].get('stat', '')}")
            if pc:
                parts.append(f"pc:{pc[0].get('player', '')}:{pc[0].get('stat', '')}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def should_run(self, ctx: GeneratorContext) -> bool:
        return bool(ctx.schedule)

    def build_context(self, ctx: GeneratorContext) -> str:
        parts: list[str] = []

        # Cap race leaders — all categories
        if ctx.caps:
            for key, label in [
                ("orange_cap", "ORANGE CAP"), ("purple_cap", "PURPLE CAP"),
                ("best_sr", "BEST STRIKE RATE"), ("best_econ", "BEST ECONOMY"),
            ]:
                entries = ctx.caps.get(key, [])[:5]
                if entries:
                    lines = [
                        f"  {e['rank']}. {e['player']} ({e['team_short']}) {e['stat']}"
                        for e in entries
                    ]
                    parts.append(f"{label}:\n" + "\n".join(lines))

        # Last 3 completed match scorecards
        if ctx.schedule:
            completed = [m for m in ctx.schedule if m.get("status") == "completed"]
            recent = completed[-3:]
            if recent:
                result_lines: list[str] = []
                for m in recent:
                    t1 = _SHORT.get(m.get("team1", ""), m.get("team1", ""))
                    t2 = _SHORT.get(m.get("team2", ""), m.get("team2", ""))
                    toss = m.get("toss") or ""
                    toss_tag = f" | Toss: {toss}" if toss else ""
                    line = (
                        f"  M{m['match_number']}: {t1} {m.get('score1', '?')}"
                        f" vs {t2} {m.get('score2', '?')}"
                        f" — {m.get('result', '?')}{toss_tag}"
                    )
                    result_lines.append(line)
                    # Top performers
                    perfs: list[str] = []
                    for key in ("top_batter1", "top_batter2"):
                        tb = m.get(key)
                        if tb and tb.get("name"):
                            no = "*" if tb.get("not_out") else ""
                            perfs.append(f"{tb['name']} {tb['runs']}({tb['balls']}){no}")
                    for key in ("top_bowler1", "top_bowler2"):
                        bw = m.get(key)
                        if bw and bw.get("name"):
                            perfs.append(f"{bw['name']} {bw['wickets']}/{bw['runs']}")
                    if m.get("hero_name"):
                        perfs.append(f"POTM: {m['hero_name']} {m.get('hero_stat', '')}")
                    if perfs:
                        result_lines.append("    " + " | ".join(perfs))
                parts.append("RECENT MATCH SCORECARDS:\n" + "\n".join(result_lines))

        # Records / milestones approaching
        records = _load_json("records.json")
        if records:
            imminent = records.get("imminent", [])[:3]
            if imminent:
                lines = [
                    f"  {e['player']}: {e.get('current', '')} → {e.get('target', '')} — {e['note']}"
                    for e in imminent
                ]
                parts.append("MILESTONE WATCH:\n" + "\n".join(lines))

        return "\n\n".join(parts)

    def system_prompt(self) -> str:
        return load_prompt("wire_scout_system.md")

    def user_prompt(self, ctx: GeneratorContext, focused_context: str, previous: str) -> str:
        template = load_prompt("wire_scout_user.md")
        return template.format(
            base_context=ctx.base_context,
            focused_context=focused_context,
            previous_entries=previous,
            franchise_ids="rcb, mi, csk, dc, pbks, srh, kkr, rr, lsg, gt",
        )
