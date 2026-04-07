Analyze the IPL 2026 playoff picture based on this data:

STANDINGS (after {matches_played} league matches):
{standings_text}

REMAINING SCHEDULE (next 10 fixtures):
{upcoming_text}

TODAY'S DATE: {today}

Generate a JSON object with EXACTLY these fields:

"matches_played": integer — total completed matches.

"situation_brief": string — exactly 1-2 sentences, max 40 words total. Structure: sentence 1 = the key fact with specific numbers. Sentence 2 (optional) = the sharpest implication. No filler words ("currently", "as of", "it is worth noting"). Example style: "RR's +4.17 NRR gives them a phantom points buffer that neutralises any 14-point deadlock. CSK and KKR, at 0-2 below -1.9, are effectively three games behind the pace."

"elimination_watch": array of objects, one per team that is either under pressure OR notably safe. Each object must have:
  - "team": short team name (e.g. "KKR", "CSK", "PBKS")
  - "risk": exactly one of "danger" | "watch" | "safe"
      danger = mathematically distressed, cannot afford more losses without a rescue run
      watch  = under pressure but still in control of their own destiny
      safe   = already secured a strong position or have a major buffer
  - "key_metric": short callout string (max 20 chars) — the single most important number or fact, e.g. "need 8W from 12" or "+4.17 NRR buffer" or "magic no. = 6W"
  - "insight": 1-2 sentences explaining the situation. Be specific — include NRR, games remaining, win-rate needed. No fluff.

"qualification_math": array of 3-5 objects, each a single non-redundant mathematical fact. Each object must have:
  - "tag": one of "SAFETY LINE" | "WIN RATE" | "NRR" | "MAGIC NO" | "POINTS"
  - "fact": one tight sentence with specific numbers. No repetition across entries — if 8W appears in one entry, don't repeat it. Cover different angles: threshold, win-rate for struggling teams, NRR leverage, magic numbers.

"if_tonight": array of objects for today's match(es) only:
  {{"match": "TEAM vs TEAM", "scenarios": [{{"result": "TEAM win", "impact": "what changes for standings/NRR"}}]}}

Return ONLY valid JSON, no markdown.
