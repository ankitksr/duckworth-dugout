"""Pydantic response schemas for War Room intel modules.

Each class maps to the structured JSON output expected from a specific
intel module's LLM call. Import from here to wire into provider.generate()
via response_schema=.

Where the schema enforces an enum (via Literal types), Gemini's structured
output respects it server-side. Format normalization (e.g. "182 for 7" →
"182/7") is done client-side via @field_validator(mode="before") which
runs when the parsed JSON is fed through Model.model_validate(...).
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

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
    phase_context: str = Field(
        default="",
        description=(
            "One-sentence phase or role framing that makes the milestone "
            "editorial — e.g. 'death-overs wicket concentration', 'powerplay "
            "strike-rate leader', 'middle-order anchor'. Empty string if the "
            "LLM cannot cite a specific phase-level pattern."
        ),
    )
    tonight_relevance: str = Field(
        default="",
        description=(
            "One-sentence reason the milestone matters in the near-term match "
            "window (venue fit, matchup edge, recent form inflection). Empty "
            "string when not applicable."
        ),
    )


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

AvailabilityStatus = Literal["out", "doubtful", "available"]
Confidence = Literal["high", "medium", "low"]
StoryType = Literal[
    "match_preview", "match_report", "injury_update", "team_news",
    "transfer_auction", "interview", "opinion", "controversy", "other",
]


class AvailabilityEvent(BaseModel):
    player_name: str
    franchise_hint: str           # short name or "" — disambiguation hint
    status: AvailabilityStatus    # enforced by Gemini via Literal
    reason: str                   # "" if not stated
    expected_return: str          # "season" | "next match" | "2 weeks" | ""
    confidence: Confidence        # enforced by Gemini via Literal
    quote: str                    # supporting snippet, <=200 chars


class KeyQuote(BaseModel):
    speaker: str                  # e.g. "Rohit Sharma" or "Hardik Pandya (captain)"
    text: str                     # verbatim quote, <=300 chars
    context: str                  # brief framing, <=100 chars


class MatchResultClaim(BaseModel):
    """Partial scorecard claim from one article. Aggregator combines across articles.

    Score and margin fields are normalized client-side via @field_validator
    so that messy LLM output ('182 for 7', 'last-ball win') becomes either
    canonical form ('182/7') or empty string (which the aggregator then
    backfills from another article's claim).
    """
    team1: str
    team1_score: str = Field(
        default="",
        description="First innings score in exact format 'R/W' e.g. '184/5'. Empty if not stated.",
    )
    team2: str
    team2_score: str = Field(
        default="",
        description="Second innings score in exact format 'R/W' e.g. '180/9'. Empty if not stated.",
    )
    winner: str = Field(default="", description="Winning team full name. Empty if not stated.")
    margin: str = Field(
        default="",
        description="Victory margin in exact format 'N runs' or 'N wickets'. Empty if not stated.",
    )
    player_of_match: str = Field(default="", description="POTM name. Empty if not stated.")
    hero_stat: str = Field(
        default="",
        description=(
            "Best performer stat line: 'NN(BB)' for batting (e.g. '70(54)') "
            "or 'N/M' for bowling (e.g. '4/27'). Empty if not stated."
        ),
    )

    @field_validator("team1_score", "team2_score", mode="before")
    @classmethod
    def _normalize_score(cls, v):
        if not v:
            return ""
        s = str(v).strip()
        # "182 for 7" / "182-7" / "182 - 7" → "182/7"
        s = re.sub(r"\s*for\s*", "/", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*-\s*", "/", s)
        s = re.sub(r"\s+", "", s)
        return s

    @field_validator("margin", mode="before")
    @classmethod
    def _normalize_margin(cls, v):
        if not v:
            return ""
        s = str(v).strip()
        # Canonicalize "5 Wickets" / "27 RUNS" → lowercase. For non-canonical
        # phrases (e.g. "last-ball win", "DLS method"), preserve as-is —
        # imperfect format is still better than dropping context.
        if re.match(r"^\d+\s+(wickets?|runs?)$", s, re.IGNORECASE):
            return s.lower()
        return s


class ArticleExtraction(BaseModel):
    """Master extraction schema — one per article LLM call.

    All fields are always present to keep Gemini's structured output happy
    (Optional/nullable support is spotty). Use empty string / empty list /
    empty MatchResultClaim as the "absent" sentinel and detect via truthiness.
    """
    is_relevant: bool                       # false → noise, drop downstream
    story_type: StoryType                    # enforced by Gemini via Literal
    summary: str                             # 2-3 factual sentences
    headline_takeaway: str                   # one-line "so what"
    mentioned_players: list[str]             # raw names from article
    availability_events: list[AvailabilityEvent]
    match_result_claim: MatchResultClaim     # all-empty fields when not a match report
    key_quotes: list[KeyQuote]
