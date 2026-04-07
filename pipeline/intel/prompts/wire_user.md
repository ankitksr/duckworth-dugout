Produce NEW intelligence dispatches for the IPL 2026 AI Wire.

**Time window: {time_window}**

{season_context}

{article_context}

{mcp_context}

{enrichment_context}

---

## TIME-WINDOW FOCUS

Adjust your angle based on the current time of day:

- **morning** — Preview mode. Set up the narratives, frame what's at stake in today's matches, identify the tactical matchups worth watching, flag which team needs what result and why. Forward-looking, hypothesis-setting energy.
- **afternoon / evening** — Live context mode. Tactical observations, in-match patterns, how current scores relate to the season-level story, what today's action is confirming or overturning. Present-tense urgency.
- **night** — Reaction and implications mode. What just changed? Who moved in the standings, who's in crisis, what does tomorrow look like differently now? Settle scores with previous predictions. Set up tomorrow's narrative.

---

## BUILDING ON THE WIRE

Previous dispatches are not just things to avoid repeating — they are threads to pull. If a previous dispatch flagged CSK's death bowling problem, the new batch should TRACK it: did it get worse? Did they fix it? Did it cost them? Dispatches that evolve a prior thread are more valuable than dispatches on entirely new topics. The wire should feel like a living document that gets smarter over time, not a sequence of isolated takes.

When you build on a previous entry, you don't need to repeat its premise — you can assume the reader saw it. Just advance the story.

ALREADY ON THE WIRE — do NOT repeat, rephrase, or echo these. Build on them or move to new angles:
{previous_entries}

---

## VOLUME AND QUALITY

Produce **8–15 dispatches**. Every single one must pass the screenshot test: would a cricket fan share this on social media? If the answer is "probably not," cut it or rewrite it. It is better to produce 8 dispatches that all pass the test than 15 where 5 are filler.

Cover different angles across the batch: tactics, NRR math, player breakouts, matchup vulnerabilities, squad dynamics, milestone chases, historical parallels, schedule crunch, cap races. If your batch has three dispatches about the same team, you're not looking broadly enough.

---

## EXAMPLE DISPATCHES

These show the tone, structure, and data-narrative balance we want:

**Example 1 — ALARM: team in crisis**
```json
{{
  "headline": "MI's death bowling isn't a slump. It's a structural flaw.",
  "text": "Since Match 6, MI have conceded 58+ in the death (overs 17-20) in four consecutive games — economy 13.4. Bumrah bowls overs 18-19. The problem is over 20: three different bowlers, 15+ economy each time. MI don't have a death-over finisher and the auction didn't fix it. Every close game from here is a coin flip they're going to lose.",
  "emoji": "🏗️",
  "category": "death_bowling",
  "severity": "alarm",
  "teams": ["mi"]
}}
```

**Example 2 — SIGNAL: data detective**
```json
{{
  "headline": "RCB's NRR is a mirage. The scorecards tell a different story.",
  "text": "RCB's +0.412 NRR looks healthy — until you filter for wins vs sub-par totals. Four of their six wins came chasing under 155. Against 170+ they're 1-3. The NRR is inflated by blowout wins that the schedule may not keep providing. Three of their next five fixtures are against top-four batting lineups.",
  "emoji": "🧊",
  "category": "nrr_math",
  "severity": "signal",
  "teams": ["rcb"]
}}
```

**Example 3 — ALERT: player breakout arc**
```json
{{
  "headline": "Tilak Varma is quietly doing something no MI batter has done since Pollard.",
  "text": "Six consecutive scores above 28 with SR 158+. Pollard is the last MI batter to sustain that over a full phase of a season (2019). The difference: Tilak is doing it in the middle overs, not the slog — which means he's carrying the innings, not accelerating one that's already set. MI have found their spine.",
  "emoji": "🚀",
  "category": "breakout_anchor",
  "severity": "alert",
  "teams": ["mi"]
}}
```

**Example 4 — SIGNAL: tactical matchup**
```json
{{
  "headline": "KKR vs CSK on Sunday is actually a leg-spin trap for Dhoni.",
  "text": "Varun Chakravarthy has dismissed Dhoni in 3 of their last 5 IPL meetings — all caught in the deep trying to go over mid-wicket. CSK's lower order provides no cover if Dhoni goes early; they're 2-8 in games where Dhoni scores under 20. KKR's tactical read here is obvious. The question is whether Dhoni's read on it has changed.",
  "emoji": "🎯",
  "category": "matchup_vulnerability",
  "severity": "signal",
  "teams": ["kkr", "csk"]
}}
```

---

## JSON SCHEMA

Each dispatch is a JSON object with exactly these fields:

- **"headline"**: punchy 8-14 word opinionated lead. Newsroom wire style, present-tense, quotable. It should make someone want to read the text. GOOD: "SRH's off-field chaos threatens to swallow Klaasen's brilliance" BAD: "SRH update" or "Klaasen is performing well"
- **"text"**: full analytical paragraph (2-4 sentences, max 350 chars). Lead with the narrative, land the data, close with the implication. The body that expands on the headline with specific numbers and a forward-looking conclusion.
- **"emoji"**: single emoji capturing the editorial tone of THIS specific insight. Not generic category icons — contextual editorial judgment. Choose from the guide in your system instructions or use your own judgment when context demands it.
- **"category"**: underscore_cased tag you choose (e.g. nrr_math, chase_pattern, powerplay, death_bowling, captaincy, form_reversal, milestone, squad_dynamics, venue_edge, schedule_crunch, roster_panic, breakout_anchor, matchup_vulnerability, auction_value, playoff_math — or anything that fits). Invent new categories freely when existing ones don't capture the angle.
- **"severity"**: one of "signal", "alert", or "alarm". Most dispatches are "signal" (routine insight). Elevate to "alert" when a developing pattern demands attention — something a team or fan should genuinely be worried or excited about. Reserve "alarm" for season-defining moments — a team's playoff hopes collapsing, a player injury that reshapes the title race, a statistical threshold crossed that changes everything. Use "alarm" at most 1-2 per day total across the entire wire.
- **"teams"**: array of canonical franchise IDs that this insight is ABOUT. Valid IDs: {franchise_ids}. Only include teams that are the SUBJECT of the insight — not teams mentioned as opponents in passing. If CSK's bowling is broken and you mention they conceded 220 to RCB, the team is ["csk"] — RCB is just context. If the insight is genuinely about both teams' strategies or a head-to-head pattern, include both.

Return ONLY a JSON array. No preamble, no commentary outside the JSON.
