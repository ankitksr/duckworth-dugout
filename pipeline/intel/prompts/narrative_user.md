Generate season narrative arcs for these IPL 2026 franchises based on their results, standings, and news coverage.

STANDINGS & RESULTS:
{standings_context}

NEWS COVERAGE (from RSS feeds):
{articles_context}

UPCOMING FIXTURES (next match per team):
{upcoming_context}

QUALIFICATION PICTURE:
{qualification_context}

For each team, generate a JSON object with:
- "franchise_id": team ID (e.g. "csk")
- "title": evocative 2-4 word title (e.g. "The Rebuilders", "Fortress Chennai")
- "mood": one of "rising", "falling", "steady", "volatile", "dominant"
- "mood_symbol": matching symbol — "▲" (rising), "▼" (falling), "▸" (steady), "◆" (volatile), "★" (dominant)
- "narrative": 2-3 sentence story of their season so far (present tense)
- "key_question": one sentence — the big question for this team going forward
- "buffer": 1-2 sentence strategic position callout. For teams in a strong position, highlight the structural advantage (NRR cushion, win-rate margin, etc.). For teams in trouble, highlight the mathematical urgency. Write as editorial insight, not raw stats. Example: "RCB's +2.415 NRR acts as a virtual point in any deadlock — they only need a 50% win rate to likely qualify."
- "buffer_tag": a short uppercase label for the buffer. Use "BEST BUFFER" for teams with NRR/points advantage, "MUST-WIN ZONE" for danger teams, "WATCH ZONE" for teams on the edge, "COMFORT ZONE" for safe teams, "BUILDING" for steady mid-table teams.
- "arc_bullets": array of exactly 3 short sentences (each ≤30 words):
  1. What the results so far have built or damaged structurally
  2. A player breakout, tactical shift, or key trend worth watching
  3. What remains unproven — the stress test or challenge ahead
- "next_test": object with:
  - "opponent": franchise_id of next opponent (e.g. "mi")
  - "match_number": integer
  - "context": 1-2 sentence editorial on why this specific match matters for this team's trajectory. Reference the opponent's form or the head-to-head dynamic. Not generic — specific to the matchup.
  - "playoff_path": 1 sentence on where the team stands in the qualification race and what pace they need. Use actual numbers.

Return a JSON array of objects, one per team. Only include teams that have played at least one match.
