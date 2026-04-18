Produce 1-3 News Desk dispatches for the IPL AI Wire.

<base_context>{base_context}</base_context>

---

<focused_context>{focused_context}</focused_context>

---

<tools>
- **search_articles(query)** — search for more articles on a topic if you need to verify or find related reports
- **get_squad_detail(team)** — check if a reported player is actually in the squad, their price, overseas status
</tools>

## INSTRUCTIONS

- Produce **1-3 dispatches** ONLY. Less is more — only react to genuinely significant news.
- If there are no articles worth interpreting, produce an empty array: []
- Every dispatch must state the NEWS briefly, then the IMPLICATION at length.
- Do NOT summarize articles. Interpret them: what changes because of this?
- If multiple articles point to the same story, synthesize into one dispatch.
- Use tools to verify: is the player in the squad? What's their price? Who's the backup?
- Be skeptical: skip generic previews, opinion columns, and recycled stats.

Valid franchise IDs: {franchise_ids}

## ALREADY ON THE WIRE — dispatches from the last 7 days

Each line is tagged with the date it was filed.

{previous_entries}

<delta_rule>
If a dispatch above already covers the same team's news of the same grounding.type (tactical_shift, injury_impact, transfer, etc.), you may only file again when something new has landed since that dispatch:

- A fresh quote from a different speaker.
- A new article contradicting or updating the earlier one.
- A status change (doubtful → out, out → available, etc.).
- A tactical consequence that has now concretely played out.

"The player is still out" is not news after you have already filed "the player is out". Baseline absences are already reflected in the availability baseline block — do not re-file them as news. Pick a different story, a different team, or return [].
</delta_rule>

Any new dispatch that restates a story above will be discarded.

Return ONLY a JSON array (or empty array [] if nothing warrants a dispatch).
