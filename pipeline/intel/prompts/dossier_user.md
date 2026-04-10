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

{availability_context}

PLAYOFF CONTEXT (how the broader season shapes this matchup):
{scenarios_context}

{wire_context}

Generate a JSON object with:
- "opponent": "{opponent_short}"
- "batting_threat": integer 1-10 (overall unit assessment). **Discount heavily for any {opponent} player in the INJURY/AVAILABILITY block with status `out`.** If {opponent}'s top order is missing a key batter, the batting threat is not what the career numbers say it is — lower the rating and explain why in the weaknesses section.
- "bowling_threat": integer 1-10 (overall unit assessment). Same rule — discount for unavailable bowlers.
- "weaknesses": array of 3-4 strings — specific, structural gaps in this team's setup. Not generic ("death bowling is weak") but pointed ("without X, the death overs leak 12+ RPO"). Reference actual players or phases of play. If a key player is in the availability block as `out`, that player's absence IS a weakness — lead with it.
- "how_to_win": array of 3 strings — tactical recommendations framed as strategic imperatives, not coaching tips. Think editorial: what would a Wisden analyst write about the path to beating this side? **Do NOT recommend exploiting a player who is listed as `out` in the availability block** — that player is not playing, so the advice is wasted.

**HARD RULE:** any reference to a player being injured, doubtful, sidelined, missing, ill, or unavailable must be backed by their exact name appearing in the INJURY/AVAILABILITY block above. Training data is stale — treat every unlisted player as FIT.

Do NOT include per-player batting_analysis or bowling_analysis arrays. Focus on team-level structural assessment only.

Return ONLY valid JSON.
