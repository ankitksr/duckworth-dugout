Produce 1-3 News Desk dispatches for the IPL AI Wire.

{base_context}

---

{focused_context}

---

## TOOLS

- **search_articles(query)** — search for more articles on a topic if you need to verify or find related reports
- **get_squad_detail(team)** — check if a reported player is actually in the squad, their price, overseas status

## ALREADY ON THE WIRE — do NOT repeat:
{previous_entries}

## INSTRUCTIONS

- Produce **1-3 dispatches** ONLY. Less is more — only react to genuinely significant news.
- If there are no articles worth interpreting, produce an empty array: []
- Every dispatch must state the NEWS briefly, then the IMPLICATION at length.
- Do NOT summarize articles. Interpret them: what changes because of this?
- If multiple articles point to the same story, synthesize into one dispatch.
- Use tools to verify: is the player in the squad? What's their price? Who's the backup?
- Be skeptical: skip generic previews, opinion columns, and recycled stats.

Valid franchise IDs: {franchise_ids}

Return ONLY a JSON array (or empty array [] if nothing warrants a dispatch).