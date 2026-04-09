Produce 2-4 Situation Room dispatches for the IPL AI Wire.

{base_context}

---

{focused_context}

---

## TOOLS

You have access to tools. Use them to verify specific claims:
- **get_team_results(team)** — recent match results with scores
- **get_remaining_schedule(team)** — upcoming fixtures

Use tools when you spot a hypothesis worth verifying: "Is CSK's remaining schedule actually harder than KKR's?" — pull both and compare. Don't pull tools for data already in your context.

## ALREADY ON THE WIRE — do NOT repeat these:
{previous_entries}

## INSTRUCTIONS

- Produce **2-4 dispatches**. Quality over volume.
- Every dispatch must contain at least one specific number (points needed, win rate required, NRR gap, matches remaining).
- Focus on: points race, NRR implications, schedule difficulty, elimination timelines, qualification scenarios.
- No more than 2 dispatches about the same team.
- Find what the table is hiding — the non-obvious positional truth.

Valid franchise IDs: {franchise_ids}

Return ONLY a JSON array.