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
