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

## ALREADY ON THE WIRE — these are dispatches you have already filed today

{previous_entries}

Any new dispatch that restates a claim above — even with different wording, different framing, or a different supporting number — will be discarded. Find a different angle, a different team, a different mathematical lens, or advance an existing thread by showing what changed since you last filed.

Return ONLY a JSON array.
