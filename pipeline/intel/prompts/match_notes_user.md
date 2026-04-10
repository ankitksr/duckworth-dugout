Write one-liner editorial notes for these completed IPL 2026 matches.

STANDINGS CONTEXT:
{standings_context}

{cap_context}

COMPLETED MATCHES:
{matches_context}

For each match, generate:
- "match_number": integer
- "note": single sentence (max 25 words), editorial tone. When a POTM performance moves a player's position in the Orange Cap or Purple Cap race, reference that — e.g. "Jaiswal's 92 took him past Kohli into second in the Orange Cap race." When the result flips standings (top-table swap, entering the playoff spots, dropping to bottom), reference that. Be specific to what makes this match significant *beyond* the scoreline.

Return a JSON array of objects. One per match.
