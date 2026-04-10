Produce 2-4 Matchday Preview dispatches for the IPL AI Wire.

{base_context}

---

{focused_context}

---

## INSTRUCTIONS

- **ONLY write previews for the matches under TODAY'S FIXTURES above.** No other fixtures exist for the purposes of this task. If TODAY'S FIXTURES is empty or says "(No matches today)", return `[]` immediately — do not invent matches.
- Produce **2-4 dispatches per match listed in TODAY'S FIXTURES** (and zero for any match not listed).
- The `teams` field on every dispatch MUST be exactly the two franchise IDs from one of TODAY'S FIXTURES. Any other pairing will be discarded.
- START by calling get_recent_h2h and get_venue_stats for each fixture. Then drill into 1-2 player matchups using get_batter_vs_bowler.
- Each dispatch should focus on a different angle: venue dynamics, key player matchup, phase-specific battle, or overall prediction.
- At least one dispatch per match must make a clear prediction (who wins and why).
- Use specific numbers from tool results — not memory, not approximation.
- If there's a standings context that makes this match high-stakes (e.g. loser drops to elimination zone), lead with that.

Valid franchise IDs: {franchise_ids}

## ALREADY ON THE WIRE — these are previews you have already filed today

{previous_entries}

Any new dispatch that restates an angle above — even with different wording, a different lead stat, or a different player matchup pointing to the same conclusion — will be discarded. Pick a different matchup, a different phase, a different venue factor, or a different prediction lens.

Return ONLY a JSON array.