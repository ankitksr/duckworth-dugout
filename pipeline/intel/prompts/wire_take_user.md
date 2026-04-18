Produce 2-3 dispatches from The Take for the IPL AI Wire.

{base_context}

---

{focused_context}

---

## WHAT OTHER DESKS HAVE FILED THIS CYCLE

<other_desks_output>
These dispatches were produced by the Situation Room, Scout Report, News Desk, and Matchday Preview *just now, in the same cycle*. Your job is to extend, connect, or synthesize across them — find the through-line they couldn't see from inside their own lane.

{other_wire_output}
</other_desks_output>

<grounding_rule>
Every take you file must anchor to at least one specific stat, standings position, NRR figure, or match result that appears verbatim in `<other_desks_output>` above or returns from a tool call you make. If you cannot point to such an anchor for a claim, do not make the claim. If the other desks have filed nothing substantive and your tools yield no new data, return `[]` rather than synthesize from memory.
</grounding_rule>

---

## TIME WINDOW: {time_window}

- **morning**: Connect the preview narratives to the season arc. What thread across today's fixtures tells a bigger story the individual previews can't?
- **afternoon/evening**: Synthesize what's unfolding in real-time. Which two dispatches above are actually the same story nobody's naming?
- **night**: Tie together what just happened. Which result or performance extends — or closes — a season-long thread?

## INSTRUCTIONS

- Produce **2-3 dispatches**. Maximum quality, maximum shareability.
- At least one dispatch must DIRECTLY build on or connect two or more other generators' outputs above. Name the thread they all point toward — do not contradict them.
- At least one dispatch must synthesize two seemingly unrelated data points into a single narrative nobody else has written.
- These must pass the screenshot test: would a cricket fan share this? If not, rewrite.
- **CRITICAL: verify before you cite.** If you attribute a specific score, SR, or match performance to a player, call get_player_season_stats or get_team_results first. Never invent match-level stats — if a stat isn't in your context or tool results, don't use it.
- **Team attribution is non-negotiable.** Every performer returned by tool calls is tagged with a team (`batter_team`, `bowler_team`, `team` on highlight entries, or `(TEAM)` after player names in `top_batters` / `top_bowlers` / `potm` strings). When you name a player, use the team from that tag. Do not infer team from the match winner or your training-data priors — mid-season transfers and replacement picks happen and your memory is stale. Players cited from other desks' `<other_desks_output>` must also carry their team tag when named; if the source dispatch didn't tag them, verify via `get_player_season_stats` or drop the reference.
- Be bold. Be specific. Be entertaining.

## REFRAME CARVE-OUT (max 1 per cycle, optional)

You may file **at most one** dispatch with `category: "reframe"` that refutes or redirects a claim another desk has made — *only* when the desks are forming a monoculture (≥3 aligned dispatches from ≥2 desks about the same team/player with the same severity) and the standings, narratives, or remaining schedule contain evidence that the consensus has outrun the data. This is the only carve-out to the "never contradict another desk" rule.

A `reframe` dispatch must:
  - Quote or paraphrase the specific consensus it is refuting in the body.
  - Anchor to ≥2 structured citations — a standings row (points, NRR, position), a narratives `mood` / `buffer` field, or a schedule fact (remaining opponents, match number).
  - Never refute availability facts (injury, illness, suspension) or results that have already happened. You may refute *interpretations* of those facts, not the facts themselves.

If the citation floor isn't met, do not file the `reframe`. File only the synthesis dispatches.

Valid franchise IDs: {franchise_ids}

## DISPATCHES ALREADY ON THE WIRE — last 7 days

Each line is tagged with the date it was filed.

{previous_entries}

<delta_rule>
If a dispatch above already threads the same pair of signals you are about to connect, you may only file again when one of the threads has materially changed since that dispatch — a new result, a new story, a new numeric breakpoint. "Same synthesis, fresh metaphor" is restatement, not a new take. In that case: find a connection nobody has drawn yet, or return [].
</delta_rule>

Any new dispatch that restates a thread above — your own prior takes OR a synthesis another desk has effectively already made — will be discarded. If you want to advance a thread, name what changed since it was last filed. Otherwise, find a connection nobody has drawn yet.

Return ONLY a JSON array.
