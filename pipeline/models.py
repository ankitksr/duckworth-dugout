"""Data models for War Room panel outputs."""

from dataclasses import dataclass, field


@dataclass
class IntelLogItem:
    """A single item in the Intel Log feed."""

    id: str
    title: str
    snippet: str | None
    source: str           # feed key: "espncricinfo", "crictracker", etc.
    source_name: str      # display name: "ESPNcricinfo", "CricTracker"
    url: str
    published: str        # ISO 8601
    teams: list[str] = field(default_factory=list)
    image_url: str | None = None
    author: str | None = None
    categories: list[str] = field(default_factory=list)


@dataclass
class StandingsRow:
    """A row in the points table."""

    franchise_id: str
    short_name: str
    primary_color: str
    played: int
    wins: int
    losses: int
    no_results: int
    points: int
    nrr: str              # "+4.171" or "-"
    position: int
    qualified: bool


@dataclass
class CapEntry:
    """A single entry in the cap race leaderboard."""

    rank: int
    player: str
    team: str             # franchise ID
    team_short: str       # "CSK"
    stat: str             # "287 runs" or "14 wkts"
    innings: int | None = None


@dataclass
class CapsData:
    """Cap race leaderboards — Orange, Purple, Best SR, Best Economy, MVP."""

    orange_cap: list[CapEntry] = field(default_factory=list)
    purple_cap: list[CapEntry] = field(default_factory=list)
    best_sr: list[CapEntry] = field(default_factory=list)
    best_econ: list[CapEntry] = field(default_factory=list)
    mvp: list[CapEntry] = field(default_factory=list)
    updated: str | None = None  # ISO 8601


@dataclass
class ScheduleMatch:
    """A match in the schedule panel."""

    match_number: int
    date: str             # "2026-03-29"
    time: str             # "19:30 IST"
    venue: str
    team1: str            # franchise ID
    team2: str            # franchise ID
    city: str = ""        # short display name: "Lucknow", "Mumbai"
    status: str = "scheduled"  # "scheduled" | "live" | "completed"
    score1: str | None = None
    score2: str | None = None
    batting: str | None = None
    match_url: str | None = None
    # Completed match fields
    winner: str | None = None         # franchise ID of winner
    result: str | None = None         # "RCB won by 6 wickets"
    hero_name: str | None = None      # "V Kohli"
    hero_stat: str | None = None      # "69*(38)"
    note: str | None = None           # editorial one-liner (LLM-generated)
    wiki_notes: str | None = None     # factoid trivia from Wikipedia (milestones, debuts, DLS)
    # Per-innings highlights (from Wikipedia fixtures)
    toss: str | None = None           # "RCB won the toss and elected to field"
    home_team: str | None = None      # franchise ID of home team
    top_batter1: dict | None = None   # {"name": "X", "runs": 80, "balls": 38, "not_out": False}
    top_bowler1: dict | None = None   # {"name": "X", "wickets": 3, "runs": 22, "overs": "4"}
    top_batter2: dict | None = None
    top_bowler2: dict | None = None
    # Live match fields
    overs1: str | None = None         # "18.2 ov"
    overs2: str | None = None         # "20 ov"
    status_text: str | None = None    # "MI need 14 from 10 balls"
    current_rr: float | None = None   # current run rate
    required_rr: float | None = None  # required run rate
    live_forecast: str | None = None  # "RR 135"


@dataclass
class TickerItem:
    """A scrolling ticker item."""

    category: str         # "H2H" | "VENUE" | "FORM" | "MATCHUP" | "IMPACT"
    text: str


@dataclass
class WireEntry:
    """An AI Wire intelligence card."""

    headline: str         # punchy 8-12 word lead
    text: str             # full analytical paragraph
    emoji: str            # single LLM-chosen contextual emoji
    category: str         # LLM-decided tag, underscore_cased
    severity: str         # "signal" | "alert" | "alarm"
    teams: list[str]      # franchise IDs referenced: ["srh", "kkr"]
    generated_at: str     # ISO 8601
    match_day: str        # "2026-04-03"
    source: str = "wire"  # generator: "situation" | "scout" | "newsdesk" | "preview" | "take"
