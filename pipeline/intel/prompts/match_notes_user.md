Write a single editorial one-liner for the TARGET MATCH below.

STANDINGS CONTEXT (current table, for stakes / movement):
<standings>{standings_context}</standings>

CAP RACE CONTEXT (Orange / Purple leaders — reference when a performance moves the race):
<cap_context>{cap_context}</cap_context>

PRIOR NOTES FOR THE TWO TEAMS IN THIS MATCH (for voice continuity and callback opportunities):
<prior_notes>{prior_notes_context}</prior_notes>

TARGET MATCH:
<match>{match_detail}</match>

Write exactly one sentence (max 25 words) in the same Wisden-style editorial voice used in the prior notes. Pack meaning: a specific performance, tactical detail, or standings/cap-race consequence — never a generic restatement of the scoreline.

Do not repeat exact phrasings or opening constructions from the prior notes (avoid two consecutive "X's Y powered …" sentences).

Return a JSON object with one field:
- "note": the sentence.
