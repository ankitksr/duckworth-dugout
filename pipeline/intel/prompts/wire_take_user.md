Produce 2-3 dispatches from The Take for the IPL AI Wire.

{base_context}

---

{focused_context}

---

## WHAT OTHER DESKS HAVE FILED THIS CYCLE

These dispatches were produced by the Situation Room, Scout Report, News Desk, and Matchday Preview *just now, in the same cycle*. Your job is to extend, connect, or synthesize across them — find the through-line they couldn't see from inside their own lane:

{other_wire_output}

---

## TIME WINDOW: {time_window}

- **morning**: Connect the preview narratives to the season arc. What thread across today's fixtures tells a bigger story the individual previews can't?
- **afternoon/evening**: Synthesize what's unfolding in real-time. Which two dispatches above are actually the same story nobody's naming?
- **night**: Tie together what just happened. Which result or performance extends — or closes — a season-long thread?

## INSTRUCTIONS

- Produce **2-3 dispatches**. Maximum quality, maximum shareability.
- At least one dispatch must DIRECTLY build on or connect two or more other generators' outputs above. Name the thread they all point toward — do not contradict them.
- At least one dispatch must synthesize two seemingly unrelated data points into a single narrative nobody else has written.
- These must pass the screenshot test: would a cricket fan share this? If not, rewrite.
- **CRITICAL: verify before you cite.** If you attribute a specific score, SR, or match performance to a player, call get_player_season_stats or get_team_results first. Never invent match-level stats — if a stat isn't in your context or tool results, don't use it.
- Be bold. Be specific. Be entertaining. But never argue with another desk — you are the voice that ties the wire together, not the voice that splits it apart.

Valid franchise IDs: {franchise_ids}

## DISPATCHES ALREADY ON TODAY'S WIRE

{previous_entries}

Any new dispatch that restates a thread above — your own prior takes OR a synthesis another desk has effectively already made — will be discarded. If you want to advance a thread, name what changed since it was last filed. Otherwise, find a connection nobody has drawn yet.

Return ONLY a JSON array.
