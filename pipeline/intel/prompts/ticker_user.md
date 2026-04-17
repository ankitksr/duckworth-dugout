Generate 6-8 ticker items for the IPL 2026 War Room based on this data:

<career_stats source="cricsheet_all_time" authority="authoritative for career totals; may lag 1–2 days">{mcp_context}</career_stats>

<season_data source="live_json_and_current_rosters" authority="authoritative for 2026 standings, cap races, and active squad membership">{season_context}</season_data>

<grounding_rule>
- Career totals, gaps-to-milestone, and all-time comparisons must come from `<career_stats>`.
- Current-season standings, cap races, W/L/NRR, and recent results must come from `<season_data>`.
- The CURRENT ROSTERS block inside `<season_data>` is the only source of truth for which players are active; do not reference any player whose name is not in that block, even if you remember them from prior seasons.
- For any career milestone gap ≤ 3 units (e.g. "1 wicket short"), append "(approx.)" to the ticker text — Cricsheet may not yet reflect the most recent match.
- Current-season cap leaders may be tied; when two players share a rank, either name both or write "tied for the lead with N".
- Never blend career and season figures in the same sentence unless explicitly labelling each.
</grounding_rule>

Each item must be a JSON object with:
- "category": one of MILESTONE, RECORD, QUIRK, FORM, SCENARIO, H2H, EMERGING
- "text": concise ticker text (max 80 chars). Must be self-explanatory — a glance should convey the insight without needing to decode references.

GOOD examples:
- "Bhuvneshwar Kumar needs 1 wicket for 200 career IPL wickets"
- "Every away captain has lost the toss in IPL 2026 so far (5/5)"
- "DC recovered from 26/4 to win — biggest 5th-wicket chase in IPL 2026"

BAD examples (don't do these):
- "Rohit extends lead to 357 for #2" (what lead? #2 in what?)
- "Narine 3 away from 200 IPL wickets" (comparison to retired players or vague milestones)

Return a JSON array of items.
