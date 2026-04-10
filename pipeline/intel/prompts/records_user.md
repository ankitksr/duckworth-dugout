Based on this IPL data, identify records and milestones to watch:

{mcp_context}

{season_context}

{availability_block}

Generate a JSON object with:
- "imminent": array of objects — records that could be broken THIS WEEK (within 1-2 matches). Each: {{"player": "...", "team": "...", "current": "...", "target": "...", "note": "..."}}. **Do NOT list any player who appears in the CURRENTLY UNAVAILABLE block above** — they are not playing in the relevant window, so their milestone is not imminent.
- "on_track": array — records on pace to be broken this season if form continues. Same fields. Unavailable players may appear here only if their expected_return still leaves them time to hit the mark — otherwise omit.
- "season_bests": array — current season's best individual performances that are approaching all-time IPL records. Fields: {{"stat": "...", "holder": "...", "value": "...", "record": "...", "record_holder": "..."}}

**HARD RULE:** Never invent an injury or absence for a player not in the CURRENTLY UNAVAILABLE block. If a player isn't listed as unavailable, assume they are playing every match.

Return ONLY valid JSON.
