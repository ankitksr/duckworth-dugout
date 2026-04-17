Based on this IPL data, identify records and milestones to watch.

<career_data source="cricsheet_all_time" authority="authoritative for career totals">
{mcp_context}
</career_data>

<season_data source="caps_json_current_season" authority="authoritative for 2026 runs/wickets">
{season_context}
</season_data>

<availability>
{availability_block}
</availability>

<grounding_rule>
All career totals, gaps-to-milestone, and rankings must come from `<career_data>`. All current-season runs, wickets, and standings come from `<season_data>`. Do not mix them, and do not estimate from training memory — current-season numbers from memory are stale. Career totals themselves reflect Cricsheet which can lag 1–2 days behind the most recent match; for any milestone gap ≤ 3 units, prefix your note with "Pending Cricsheet update —" so readers know the exact remaining figure may already be smaller.
</grounding_rule>

<hard_constraint id="season_bests_grounding">
`season_bests` is for individual 2026 innings scores (e.g. a 112* in a match) that are approaching all-time IPL marks. The current `<season_data>` block contains aggregated cap-race totals and standings — it does not list individual innings scores. Therefore, unless a specific innings score for the current season appears verbatim in `<season_data>` or is explicitly cited there, output `"season_bests": []`. Never populate this array from training memory — the 2026 best innings scores are not in your training data. Inventing a record-holder citation here is a terminal failure.
</hard_constraint>

Generate a JSON object with:
- "imminent": array of objects — records that could be broken THIS WEEK (within 1-2 matches). Each: {{"player": "...", "team": "...", "current": "...", "target": "...", "note": "...", "phase_context": "...", "tonight_relevance": "..."}}. **Do NOT list any player who appears in the CURRENTLY UNAVAILABLE block above** — they are not playing in the relevant window, so their milestone is not imminent. Fill `phase_context` only when the player has a documented phase/role pattern that makes the milestone editorial; fill `tonight_relevance` only when a near-term fixture makes the milestone likely this week. Empty string is the correct value when you cannot anchor a claim — never invent a phase stat.
- "on_track": array — records on pace to be broken this season if form continues. Same fields including `phase_context` and `tonight_relevance` (same rules — empty is acceptable, invention is not). Unavailable players may appear here only if their expected_return still leaves them time to hit the mark — otherwise omit.
- "season_bests": array — current season's best individual performances that are approaching all-time IPL records. Fields: {{"stat": "...", "holder": "...", "value": "...", "record": "...", "record_holder": "..."}}

**HARD RULE:** Never invent an injury or absence for a player not in the CURRENTLY UNAVAILABLE block. If a player isn't listed as unavailable, assume they are playing every match.

Return ONLY valid JSON.
