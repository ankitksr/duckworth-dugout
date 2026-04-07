Generate a tactical dossier on {opponent} for {perspective}'s match preparation.

HISTORICAL DATA (career IPL from Cricsheet):
{batting_profile}

{bowling_profile}

CURRENT SQUAD ({opponent} — IPL {season}, from match data):
{squad_context}

CURRENT FORM (IPL {season}):
{form_context}

NEWS (recent RSS articles):
{articles_context}

Generate a JSON object with:
- "opponent": "{opponent_short}"
- "batting_threat": integer 1-10 (overall unit assessment)
- "bowling_threat": integer 1-10 (overall unit assessment)
- "weaknesses": array of 3-4 strings — specific, structural gaps in this team's setup. Not generic ("death bowling is weak") but pointed ("without X, the death overs leak 12+ RPO"). Reference actual players or phases of play.
- "how_to_win": array of 3 strings — tactical recommendations framed as strategic imperatives, not coaching tips. Think editorial: what would a Wisden analyst write about the path to beating this side?

Do NOT include per-player batting_analysis or bowling_analysis arrays. Focus on team-level structural assessment only.

Return ONLY valid JSON.
