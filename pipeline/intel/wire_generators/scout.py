"""Scout Report — player performances, form trends, cap races, matchup data.

Trigger: match completion (new stats become available).
Voice: scouting report — specific, phase-split aware, comparative.
Model: Pro @ 0.7 — analytical, connects dots across performances.
"""

import hashlib

from pipeline.intel.prompts import load_prompt
from pipeline.intel.roster_context import _query_squad
from pipeline.intel.wire_generators import (
    HASH_VERSION,
    GeneratorContext,
    WireGenerator,
    _load_json,
)
from pipeline.ipl.franchise_metadata import IPL_FRANCHISES

_SHORT = {fid: d["short_name"] for fid, d in IPL_FRANCHISES.items() if not d.get("defunct")}


def _squad_team_map(ctx: GeneratorContext) -> dict[str, str]:
    """Build a {lowercased player name → team short} lookup from the season squad.

    Used to stamp authoritative team tags onto every performer in the recent-match
    scorecard block so the LLM never has to infer player→team from narrative context
    (which has produced cross-team hallucinations — see de Kock/PBKS, 2026-04-17).
    """
    out: dict[str, str] = {}
    for fid, name, *_ in _query_squad(ctx.conn, ctx.season):
        short = _SHORT.get(fid)
        if short and name:
            out[name.lower()] = short
    return out


def _resolve_team(
    name: str,
    squad_map: dict[str, str],
    fallback: str | None,
) -> str | None:
    """Prefer the squad map; fall back to the positional convention only if the
    name isn't in any squad. Never guess — return None if both fail."""
    if not name:
        return None
    hit = squad_map.get(name.lower())
    if hit:
        return hit
    # Try surname-only match (covers "de Kock" vs "Quinton de Kock" etc.)
    last = name.split()[-1].lower() if name.split() else ""
    if last:
        matches = [v for k, v in squad_map.items() if k.split()[-1:] == [last]]
        if len(matches) == 1:
            return matches[0]
    return fallback


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
        parts = [HASH_VERSION, self.SOURCE]
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

        # Last 3 completed match scorecards — every performer gets an explicit
        # team tag from the season squad table so the LLM can never invert
        # attribution from the winner narrative (regression guard for the
        # de Kock → PBKS hallucination).
        if ctx.schedule:
            completed = [m for m in ctx.schedule if m.get("status") == "completed"]
            recent = completed[-3:]
            if recent:
                squad_map = _squad_team_map(ctx)
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

                    # Positional convention (used only as a fallback):
                    # top_batter1 → team1, top_batter2 → team2,
                    # top_bowler1 → bowled vs team1 → team2,
                    # top_bowler2 → bowled vs team2 → team1.
                    pos: dict[str, str | None] = {
                        "top_batter1": t1, "top_batter2": t2,
                        "top_bowler1": t2, "top_bowler2": t1,
                    }

                    # Resolve each performer once and remember the team so
                    # POTM can inherit it (handles mid-season signings missing
                    # from ipl_season_squad — e.g. de Kock → MI as of 2026-04).
                    local_teams: dict[str, str] = {}

                    def _tag(name: str, fallback: str | None) -> str:
                        team = _resolve_team(name, squad_map, fallback)
                        if team:
                            local_teams[name.lower()] = team
                            return f" ({team})"
                        return ""

                    perfs: list[str] = []
                    for key in ("top_batter1", "top_batter2"):
                        tb = m.get(key)
                        if tb and tb.get("name"):
                            no = "*" if tb.get("not_out") else ""
                            tag = _tag(tb["name"], pos[key])
                            perfs.append(
                                f"{tb['name']}{tag} {tb['runs']}({tb['balls']}){no}"
                            )
                    for key in ("top_bowler1", "top_bowler2"):
                        bw = m.get(key)
                        if bw and bw.get("name"):
                            tag = _tag(bw["name"], pos[key])
                            perfs.append(
                                f"{bw['name']}{tag} {bw['wickets']}/{bw['runs']}"
                            )
                    if m.get("hero_name"):
                        hero = m["hero_name"]
                        team = (
                            _resolve_team(hero, squad_map, None)
                            or local_teams.get(hero.lower())
                        )
                        tag = f" ({team})" if team else ""
                        perfs.append(
                            f"POTM: {hero}{tag} {m.get('hero_stat', '')}"
                        )
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
