Generate 6-8 ticker items for the IPL 2026 War Room based on this data:

<career_stats>{mcp_context}</career_stats>

<season_data>{season_context}</season_data>

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
