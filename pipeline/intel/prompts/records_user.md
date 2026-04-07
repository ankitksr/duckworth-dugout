Based on this IPL data, identify records and milestones to watch:

{mcp_context}

{season_context}

Generate a JSON object with:
- "imminent": array of objects — records that could be broken THIS WEEK (within 1-2 matches). Each: {{"player": "...", "team": "...", "current": "...", "target": "...", "note": "..."}}
- "on_track": array — records on pace to be broken this season if form continues. Same fields.
- "season_bests": array — current season's best individual performances that are approaching all-time IPL records. Fields: {{"stat": "...", "holder": "...", "value": "...", "record": "...", "record_holder": "..."}}

Return ONLY valid JSON.
