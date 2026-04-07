Generate a pre-match intel brief for this IPL 2026 fixture:

MATCH: {team1} vs {team2}
DATE: {date}, {time}
VENUE: {venue}, {city}

VENUE DATA (from Cricsheet, all-time):
{venue_context}

HEAD TO HEAD (from Cricsheet, all-time):
{h2h_context}

CURRENT SQUADS (from match data this season):
{squad_context}

CURRENT FORM (IPL 2026):
{form_context}

NEWS COVERAGE (recent RSS articles):
{articles_context}

ESPNCRICINFO ARTICLES (title + link):
{espn_context}

Generate a JSON object with these fields:

- "match": "{team1_short} vs {team2_short}"

- "venue_note": 1-2 sentences — editorial insight about what the venue numbers mean for tonight (pitch behavior, dew factor, recent trends, what par score to target). Do NOT repeat the raw numbers, they will be shown separately.

- "h2h": object with "total", "{team1_short}_wins", "{team2_short}_wins", "note" (1 sentence — psychological/narrative angle, not just numbers)

- "form": object with "{team1_short}" and "{team2_short}" sub-objects each having "trend" only (1-2 sentences on current momentum/issues). Do NOT include wins/losses/NRR — those are injected from source data.

- "squad_news": array of 2-4 strings — injuries, playing XI changes, tactical notes from RSS articles. Be specific and cite sources.

- "key_matchups": array of 2-3 objects with structured fields:
  {{
    "player1": "batter name",
    "player1_team": "{team1_short}" or "{team2_short}",
    "player1_role": "opener" | "middle-order" | "finisher" | "allrounder",
    "player2": "bowler/fielder name",
    "player2_team": "{team1_short}" or "{team2_short}",
    "player2_role": "pace" | "spin" | "allrounder",
    "insight": "1-2 sentences — why this duel matters tonight"
  }}
  IMPORTANT: ONLY use players listed in the CURRENT SQUADS section above. These are confirmed from match data. Do NOT use players from memory who may have been traded in the mega auction.
  Pick the most consequential batter-vs-bowler duels.

- "tactical_edge": 1-2 sentences — concise summary of who has the advantage and the single biggest reason why.

- "favoured": "{team1_short}" or "{team2_short}" or "even" — which team has the tactical edge heading into this match.

- "preview_links": array of objects — {{"title": "article title", "url": "https://..."}} — select the 1-3 most relevant PREVIEW or ANALYSIS articles from the ESPNcricinfo list above. Only include articles that are genuinely about this upcoming match or the teams' current form. Exclude post-match reports of older matches.

Return ONLY valid JSON.
