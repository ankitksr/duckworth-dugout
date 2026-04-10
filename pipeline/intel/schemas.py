"""Pydantic response schemas for War Room intel modules.

Each class maps to the structured JSON output expected from a specific
intel module's LLM call. Import from here to wire into provider.generate()
via response_schema=.
"""

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# match_notes.py
# ---------------------------------------------------------------------------

class MatchNote(BaseModel):
    match_number: int
    note: str


# ---------------------------------------------------------------------------
# extract.py
# ---------------------------------------------------------------------------

class MatchExtractResponse(BaseModel):
    team1_name: str
    team1_score: str
    team1_overs: str
    team2_name: str
    team2_score: str
    team2_overs: str
    winner_name: str
    margin: str
    player_of_match: str
    hero_name: str
    hero_stat: str


# ---------------------------------------------------------------------------
# ticker.py
# ---------------------------------------------------------------------------

class TickerItemResponse(BaseModel):
    category: str
    text: str


# ---------------------------------------------------------------------------
# scenarios.py
# ---------------------------------------------------------------------------

class EliminationEntry(BaseModel):
    team: str
    risk: str
    key_metric: str
    insight: str


class QualificationFact(BaseModel):
    tag: str
    fact: str


class IfTonightScenario(BaseModel):
    result: str
    impact: str


class IfTonight(BaseModel):
    match: str
    scenarios: list[IfTonightScenario]


class ScenariosResponse(BaseModel):
    matches_played: int
    situation_brief: str
    elimination_watch: list[EliminationEntry]
    qualification_math: list[QualificationFact]
    if_tonight: list[IfTonight]


# ---------------------------------------------------------------------------
# narrative.py
# ---------------------------------------------------------------------------

class NextTest(BaseModel):
    opponent: str
    match_number: int
    context: str
    playoff_path: str


class NarrativeEntry(BaseModel):
    franchise_id: str
    title: str
    mood: str
    mood_symbol: str
    narrative: str
    key_question: str
    buffer: str
    buffer_tag: str
    arc_bullets: list[str]
    next_test: NextTest


# ---------------------------------------------------------------------------
# dossier.py
# ---------------------------------------------------------------------------

class DossierResponse(BaseModel):
    opponent: str
    batting_threat: int
    bowling_threat: int
    weaknesses: list[str]
    how_to_win: list[str]


# ---------------------------------------------------------------------------
# briefing.py
# ---------------------------------------------------------------------------

class KeyMatchup(BaseModel):
    player1: str
    player1_team: str
    player1_role: str
    player2: str
    player2_team: str
    player2_role: str
    insight: str


class PreviewLink(BaseModel):
    title: str
    url: str


class H2H(BaseModel):
    total: int
    note: str


class FormEntry(BaseModel):
    trend: str


class BriefingResponse(BaseModel):
    match: str
    venue_note: str
    h2h: H2H
    form: dict[str, FormEntry]
    squad_news: list[str]
    key_matchups: list[KeyMatchup]
    tactical_edge: str
    favoured: str
    preview_links: list[PreviewLink]


# ---------------------------------------------------------------------------
# records.py
# ---------------------------------------------------------------------------

class RecordEntry(BaseModel):
    player: str
    team: str
    current: str
    target: str
    note: str


class SeasonBest(BaseModel):
    stat: str
    holder: str
    value: str
    record: str
    record_holder: str


class RecordsResponse(BaseModel):
    imminent: list[RecordEntry]
    on_track: list[RecordEntry]
    season_bests: list[SeasonBest]


# ---------------------------------------------------------------------------
# wire.py
# ---------------------------------------------------------------------------

class WireDispatch(BaseModel):
    headline: str
    text: str
    emoji: str
    category: str
    severity: str
    teams: list[str]


# ---------------------------------------------------------------------------
# article_extraction.py
# ---------------------------------------------------------------------------

class AvailabilityEvent(BaseModel):
    player_name: str         # as it appears in article
    franchise_hint: str      # short name or "" — disambiguation hint
    status: str              # 'out' | 'doubtful' | 'available'
    reason: str              # "" if not stated
    expected_return: str     # "season" | "next match" | "2 weeks" | ""
    confidence: str          # 'high' | 'medium' | 'low'
    quote: str               # supporting snippet, <=200 chars


class KeyQuote(BaseModel):
    speaker: str             # e.g. "Rohit Sharma" or "Hardik Pandya (captain)"
    text: str                # verbatim quote, <=300 chars
    context: str             # brief framing, <=100 chars


class MatchResultClaim(BaseModel):
    """Partial scorecard claim from one article. Aggregator combines across articles."""
    team1: str               # team name as in article
    team1_score: str         # "184/5" or ""
    team2: str
    team2_score: str
    winner: str              # team name or ""
    margin: str              # "5 wickets" or ""
    player_of_match: str     # name or ""
    hero_stat: str           # "70(54)" or ""


class ArticleExtraction(BaseModel):
    """Master extraction schema — one per article LLM call.

    All fields are always present to keep Gemini's structured output happy
    (Optional/nullable support is spotty). Use empty string / empty list /
    empty MatchResultClaim as the "absent" sentinel and detect via truthiness.

    story_type allowed values:
        match_preview, match_report, injury_update, team_news,
        transfer_auction, interview, opinion, controversy, other.
    """
    is_relevant: bool                    # false → noise, drop downstream
    story_type: str
    summary: str                          # 2-3 factual sentences
    headline_takeaway: str                # one-line "so what"
    mentioned_players: list[str]          # raw names from article
    availability_events: list[AvailabilityEvent]
    match_result_claim: MatchResultClaim  # all-empty fields when not a match report
    key_quotes: list[KeyQuote]
