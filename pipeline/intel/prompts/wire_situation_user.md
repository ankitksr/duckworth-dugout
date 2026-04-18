Produce 2-4 Situation Room dispatches for the IPL AI Wire.

<base_context>{base_context}</base_context>

---

<focused_context>{focused_context}</focused_context>

---

<tools>
You have access to tools. Use them to verify specific claims:
- **get_team_results(team)** — recent match results with scores
- **get_remaining_schedule(team)** — upcoming fixtures

Use tools when you spot a hypothesis worth verifying: "Is CSK's remaining schedule actually harder than KKR's?" — pull both and compare. Don't pull tools for data already in your context.
</tools>

## INSTRUCTIONS

- Produce **2-4 dispatches**. Quality over volume.
- Every dispatch must contain at least one specific number (points needed, win rate required, NRR gap, matches remaining).
- Focus on: points race, NRR implications, schedule difficulty, elimination timelines, qualification scenarios.
- No more than 2 dispatches about the same team.
- Find what the table is hiding — the non-obvious positional truth.

Valid franchise IDs: {franchise_ids}

## ALREADY ON THE WIRE — dispatches from the last 7 days

Each line is tagged with the date it was filed.

{previous_entries}

<delta_rule>
If a dispatch above already covers the same team with the same grounding.type (same kind of claim — elimination math, NRR pattern, schedule projection, etc.), you may only file again when a SPECIFIC NUMERIC THRESHOLD HAS JUST CROSSED since that dispatch:

- Mathematical elimination is now possible where it wasn't.
- NRR has crossed a band boundary (±0.5, ±1.0).
- Matches-remaining reached a new bucket (10 → 9, 5 → 4, etc.).
- A match result since the prior dispatch materially changed the math.

"The same claim with a slightly different number" is not news. "KKR needed 88% yesterday, 100% today" is not a new dispatch — it is yesterday's dispatch with the number ticked. In that case: file on a different team, pick a different mathematical lens on the same team, or return [].

The wire reader sees the last 7 days of the feed. Repeats stand out.
</delta_rule>

Any new dispatch that restates a claim above will be discarded.

Return ONLY a JSON array.
