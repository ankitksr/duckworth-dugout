Produce 1–2 dispatches from The Archive for the IPL AI Wire.

<base_context>{base_context}</base_context>

---

<focused_context>{focused_context}</focused_context>

---

## INSTRUCTIONS

- Produce **1–2 dispatches** ONLY. An empty array `[]` is a valid, preferred answer when no historical precedent clears the citation floor.
- Each dispatch must anchor to a specific trigger in the ACTIVE TRIGGERS block of the focused context. Do not freelance — if the trigger isn't there, the dispatch isn't there.
- Call your tools before writing. `get_team_results` to verify historical records, `get_player_career_stats` for milestone-chase timelines, `get_remaining_schedule` when the parallel depends on what's ahead.
- Every dispatch must name: the precedent team, the year, the match number / date, the then-numbers, and the end-of-season numbers.
- One structural claim per dispatch — do not stack "this reminds us of 2017 AND 2019 AND 2022." Pick the single tightest isomorphism.
- If two precedents exist with opposite outcomes, file the cautionary twin (same start → worse finish) rather than the triumphant one — it carries more editorial weight.

Valid franchise IDs: {franchise_ids}

## ALREADY ON THE WIRE — prior Archive dispatches to avoid restating

{previous_entries}

Any new dispatch that restates a parallel above — even with different wording or a slightly different endpoint — will be discarded. If a trigger has already received its single best parallel, move on to a different trigger or file nothing.

Return ONLY a JSON array (or empty array `[]`).
