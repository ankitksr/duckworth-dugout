Produce 2-4 Matchday Preview dispatches for the IPL AI Wire.

{base_context}

---

{focused_context}

---

## ALREADY ON THE WIRE — do NOT repeat:
{previous_entries}

## INSTRUCTIONS

- Produce **2-4 dispatches per match**.
- START by calling get_recent_h2h and get_venue_stats for each fixture. Then drill into 1-2 player matchups using get_batter_vs_bowler.
- Each dispatch should focus on a different angle: venue dynamics, key player matchup, phase-specific battle, or overall prediction.
- At least one dispatch per match must make a clear prediction (who wins and why).
- Use specific numbers from tool results — not memory, not approximation.
- If there's a standings context that makes this match high-stakes (e.g. loser drops to elimination zone), lead with that.

Valid franchise IDs: {franchise_ids}

Return ONLY a JSON array.