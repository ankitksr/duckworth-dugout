Produce 3-5 Scout Report dispatches for the IPL AI Wire.

<base_context>{base_context}</base_context>

---

<focused_context>{focused_context}</focused_context>

---

## INSTRUCTIONS

- Produce **3-5 dispatches**. Each must be about a specific player or player comparison.
- Every dispatch must reference at least one verifiable stat. Use your tools to get phase splits, season stats, or matchup data before writing.
- Cover different player stories: breakout, decline, cap race, role mismatch, auction value, phase dominance.
- Connect individual performances to team outcomes.
- No more than 2 dispatches about players from the same team.
- If the cap race is tight, one dispatch should cover it.
- If a previous wire entry flagged a player trend, advance the thread: did it continue? Reverse? Get worse?

Valid franchise IDs: {franchise_ids}

## ALREADY ON THE WIRE — dispatches from the last 7 days

Each line is tagged with the date it was filed.

{previous_entries}

<delta_rule>
If a dispatch above already covers the same player with the same grounding.type (same kind of claim — phase dominance, role fit, cap race position, breakout, diagnosis), you may only file again when the underlying stat has materially moved:

- Phase-split number crossed a threshold (e.g. death-overs SR went from 140 to 170).
- Cap-race position changed by ≥2 spots.
- Role breakpoint (first 5-fer, first century of season, first POTM).
- A recent match result created a new angle (e.g. player saved a game that was already heading the other way).

"Same player, same story, next sync" is not a scouting report — it is a reminder. In that case: pick a different player or return [].
</delta_rule>

Any new dispatch that restates a claim above will be discarded.

Return ONLY a JSON array.
