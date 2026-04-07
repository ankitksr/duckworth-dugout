"""Hardcoded IPL franchise reference data.

Seeds the enrichment DB with franchise metadata: team colours, short names,
home venues by era, and auction cycle definitions. This is static/manual data
that doesn't come from Cricsheet.

All current and historical IPL franchises are included.
"""

from pathlib import Path

import duckdb
from rich.console import Console

console = Console()

_IPL_SCHEMA_PATH = Path(__file__).parents[1] / "db" / "ipl_enrichment_schema.sql"

# ── Franchise Reference Data ─────────────────────────────────────────────

# Each franchise entry contains:
#   id: canonical slug (stable across name changes)
#   name: current display name
#   short_name: 2-4 letter abbreviation
#   cricsheet_name: primary Cricsheet team name string
#   cricsheet_names: all Cricsheet team name variants (handles renames)
#   primary_color / secondary_color / accent_color: hex brand colours
#   venues: list of {name, city, season_from, season_to, is_primary} dicts
#   founded_year: year franchise was founded
#   defunct: True if franchise no longer exists
#   successor_id: canonical slug of successor franchise (if applicable)

IPL_FRANCHISES: dict[str, dict] = {
    "csk": {
        "name": "Chennai Super Kings",
        "short_name": "CSK",
        "cricsheet_name": "Chennai Super Kings",
        "cricsheet_names": ["Chennai Super Kings"],
        "primary_color": "#FCCA06",
        "war_room_color": "#fdb913",
        "secondary_color": "#0081E9",
        "accent_color": "#FFFFFF",
        "venues": [
            {
                "name": "MA Chidambaram Stadium",
                "city": "Chennai",
                "season_from": 2008,
                "season_to": None,
                "is_primary": True,
            },
        ],
        "founded_year": 2008,
        "defunct": False,
    },
    "mi": {
        "name": "Mumbai Indians",
        "short_name": "MI",
        "cricsheet_name": "Mumbai Indians",
        "cricsheet_names": ["Mumbai Indians"],
        "primary_color": "#004BA0",
        "war_room_color": "#4a90e8",
        "secondary_color": "#D1AB3E",
        "accent_color": "#FFFFFF",
        "venues": [
            {
                "name": "Wankhede Stadium",
                "city": "Mumbai",
                "season_from": 2008,
                "season_to": None,
                "is_primary": True,
            },
        ],
        "founded_year": 2008,
        "defunct": False,
    },
    "rcb": {
        "name": "Royal Challengers Bengaluru",
        "short_name": "RCB",
        "cricsheet_name": "Royal Challengers Bengaluru",
        "cricsheet_names": ["Royal Challengers Bangalore", "Royal Challengers Bengaluru"],
        "primary_color": "#EC1C24",
        "war_room_color": "#e2231a",
        "secondary_color": "#2B2A29",
        "accent_color": "#D4AF37",
        "venues": [
            {
                "name": "M Chinnaswamy Stadium",
                "city": "Bengaluru",
                "season_from": 2008,
                "season_to": None,
                "is_primary": True,
            },
        ],
        "founded_year": 2008,
        "defunct": False,
    },
    "kkr": {
        "name": "Kolkata Knight Riders",
        "short_name": "KKR",
        "cricsheet_name": "Kolkata Knight Riders",
        "cricsheet_names": ["Kolkata Knight Riders"],
        "primary_color": "#3A225D",
        "war_room_color": "#9b7ed8",
        "secondary_color": "#B3A123",
        "accent_color": None,
        "venues": [
            {
                "name": "Eden Gardens",
                "city": "Kolkata",
                "season_from": 2008,
                "season_to": None,
                "is_primary": True,
            },
        ],
        "founded_year": 2008,
        "defunct": False,
    },
    "dc": {
        "name": "Delhi Capitals",
        "short_name": "DC",
        "cricsheet_name": "Delhi Capitals",
        "cricsheet_names": ["Delhi Daredevils", "Delhi Capitals"],
        "primary_color": "#004C93",
        "war_room_color": "#2bbce0",
        "secondary_color": "#EF1B23",
        "accent_color": None,
        "venues": [
            {
                "name": "Feroz Shah Kotla",
                "city": "Delhi",
                "season_from": 2008,
                "season_to": 2018,
                "is_primary": True,
            },
            {
                "name": "Arun Jaitley Stadium",
                "city": "Delhi",
                "season_from": 2019,
                "season_to": None,
                "is_primary": True,
            },
        ],
        "founded_year": 2008,
        "defunct": False,
    },
    "srh": {
        "name": "Sunrisers Hyderabad",
        "short_name": "SRH",
        "cricsheet_name": "Sunrisers Hyderabad",
        "cricsheet_names": ["Sunrisers Hyderabad"],
        "primary_color": "#FF822A",
        "war_room_color": "#ff822a",
        "secondary_color": "#000000",
        "accent_color": None,
        "venues": [
            {
                "name": "Rajiv Gandhi International Cricket Stadium",
                "city": "Hyderabad",
                "season_from": 2013,
                "season_to": None,
                "is_primary": True,
            },
        ],
        "founded_year": 2013,
        "defunct": False,
    },
    "pbks": {
        "name": "Punjab Kings",
        "short_name": "PBKS",
        "cricsheet_name": "Punjab Kings",
        "cricsheet_names": ["Kings XI Punjab", "Punjab Kings"],
        "primary_color": "#ED1B24",
        "war_room_color": "#ff6b6b",
        "secondary_color": "#A7A9AC",
        "accent_color": None,
        "venues": [
            {
                "name": "PCA Stadium, Mohali",
                "city": "Chandigarh",
                "season_from": 2008,
                "season_to": 2022,
                "is_primary": True,
            },
            {
                "name": "Maharaja Yadavindra Singh International Cricket Stadium",
                "city": "Mullanpur",
                "season_from": 2023,
                "season_to": None,
                "is_primary": True,
            },
        ],
        "founded_year": 2008,
        "defunct": False,
    },
    "rr": {
        "name": "Rajasthan Royals",
        "short_name": "RR",
        "cricsheet_name": "Rajasthan Royals",
        "cricsheet_names": ["Rajasthan Royals"],
        "primary_color": "#EA1A85",
        "war_room_color": "#ea1a85",
        "secondary_color": "#254AA5",
        "accent_color": None,
        "venues": [
            {
                "name": "Sawai Mansingh Stadium",
                "city": "Jaipur",
                "season_from": 2008,
                "season_to": None,
                "is_primary": True,
            },
        ],
        "founded_year": 2008,
        "defunct": False,
    },
    "gt": {
        "name": "Gujarat Titans",
        "short_name": "GT",
        "cricsheet_name": "Gujarat Titans",
        "cricsheet_names": ["Gujarat Titans"],
        "primary_color": "#1C1C1C",
        "war_room_color": "#4dbfa8",
        "secondary_color": "#0B4973",
        "accent_color": None,
        "venues": [
            {
                "name": "Narendra Modi Stadium",
                "city": "Ahmedabad",
                "season_from": 2022,
                "season_to": None,
                "is_primary": True,
            },
        ],
        "founded_year": 2022,
        "defunct": False,
    },
    "lsg": {
        "name": "Lucknow Super Giants",
        "short_name": "LSG",
        "cricsheet_name": "Lucknow Super Giants",
        "cricsheet_names": ["Lucknow Super Giants"],
        "primary_color": "#A72056",
        "war_room_color": "#c44885",
        "secondary_color": "#FFCC00",
        "accent_color": None,
        "venues": [
            {
                "name": "BRSABV Ekana Cricket Stadium",
                "city": "Lucknow",
                "season_from": 2022,
                "season_to": None,
                "is_primary": True,
            },
        ],
        "founded_year": 2022,
        "defunct": False,
    },
    # ── Defunct franchises ────────────────────────────────────────────────
    "deccan_chargers": {
        "name": "Deccan Chargers",
        "short_name": "DCH",
        "cricsheet_name": "Deccan Chargers",
        "cricsheet_names": ["Deccan Chargers"],
        "primary_color": "#2B2B2B",
        "secondary_color": "#E04F16",
        "accent_color": None,
        "venues": [
            {
                "name": "Rajiv Gandhi International Cricket Stadium",
                "city": "Hyderabad",
                "season_from": 2008,
                "season_to": 2012,
                "is_primary": True,
            },
        ],
        "founded_year": 2008,
        "defunct": True,
        "successor_id": "srh",
    },
    "pune_warriors": {
        "name": "Pune Warriors India",
        "short_name": "PWI",
        "cricsheet_name": "Pune Warriors",
        "cricsheet_names": ["Pune Warriors"],
        "primary_color": "#2F9BE3",
        "secondary_color": "#CFDB00",
        "accent_color": None,
        "venues": [
            {
                "name": "Subrata Roy Sahara Stadium",
                "city": "Pune",
                "season_from": 2011,
                "season_to": 2013,
                "is_primary": True,
            },
        ],
        "founded_year": 2011,
        "defunct": True,
    },
    "kochi_tuskers": {
        "name": "Kochi Tuskers Kerala",
        "short_name": "KTK",
        "cricsheet_name": "Kochi Tuskers Kerala",
        "cricsheet_names": ["Kochi Tuskers Kerala"],
        "primary_color": "#6A0DAD",
        "secondary_color": "#FFD700",
        "accent_color": None,
        "venues": [
            {
                "name": "Jawaharlal Nehru Stadium",
                "city": "Kochi",
                "season_from": 2011,
                "season_to": 2011,
                "is_primary": True,
            },
        ],
        "founded_year": 2011,
        "defunct": True,
    },
    "rps": {
        "name": "Rising Pune Supergiant",
        "short_name": "RPS",
        "cricsheet_name": "Rising Pune Supergiant",
        "cricsheet_names": ["Rising Pune Supergiant", "Rising Pune Supergiants"],
        "primary_color": "#6A0DAD",
        "secondary_color": "#D4AF37",
        "accent_color": None,
        "venues": [
            {
                "name": "Maharashtra Cricket Association Stadium",
                "city": "Pune",
                "season_from": 2016,
                "season_to": 2017,
                "is_primary": True,
            },
        ],
        "founded_year": 2016,
        "defunct": True,
    },
    "gl": {
        "name": "Gujarat Lions",
        "short_name": "GL",
        "cricsheet_name": "Gujarat Lions",
        "cricsheet_names": ["Gujarat Lions"],
        "primary_color": "#E04F16",
        "secondary_color": "#003366",
        "accent_color": None,
        "venues": [
            {
                "name": "Saurashtra Cricket Association Stadium",
                "city": "Rajkot",
                "season_from": 2016,
                "season_to": 2017,
                "is_primary": True,
            },
        ],
        "founded_year": 2016,
        "defunct": True,
    },
}

# Reverse lookup: Cricsheet team name -> franchise ID
CRICSHEET_NAME_TO_FRANCHISE: dict[str, str] = {}
for _fid, _fdata in IPL_FRANCHISES.items():
    for _csname in _fdata["cricsheet_names"]:
        CRICSHEET_NAME_TO_FRANCHISE[_csname] = _fid

# ── Auction Cycle Definitions ────────────────────────────────────────────

AUCTION_CYCLES: list[dict] = [
    {
        "id": "cycle-2008",
        "cycle_name": "Foundation Era",
        "start_season": 2008,
        "end_season": 2010,
        "description": "Inaugural mega auction and the first three IPL seasons",
    },
    {
        "id": "cycle-2011",
        "cycle_name": "First Reset",
        "start_season": 2011,
        "end_season": 2013,
        "description": "Second mega auction; Kochi Tuskers & Pune Warriors enter and exit",
    },
    {
        "id": "cycle-2014",
        "cycle_name": "Golden Age",
        "start_season": 2014,
        "end_season": 2017,
        "description": "Third mega auction; CSK/RR suspended 2016-17, RPS & GL fill in",
    },
    {
        "id": "cycle-2018",
        "cycle_name": "Return Era",
        "start_season": 2018,
        "end_season": 2021,
        "description": "Fourth mega auction; CSK return, COVID bubble seasons",
    },
    {
        "id": "cycle-2022",
        "cycle_name": "Expansion Era",
        "start_season": 2022,
        "end_season": 2024,
        "description": "Fifth mega auction; GT & LSG join, 10-team format",
    },
    {
        "id": "cycle-2025",
        "cycle_name": "New Cycle",
        "start_season": 2025,
        "end_season": 2027,
        "description": "Sixth mega auction cycle",
    },
]


# ── Schema & Seeding ────────────────────────────────────────────────────


def create_ipl_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create IPL enrichment tables from ipl_enrichment_schema.sql. Idempotent."""
    schema_sql = _IPL_SCHEMA_PATH.read_text()
    for statement in schema_sql.split(";"):
        lines = [ln for ln in statement.splitlines() if not ln.strip().startswith("--")]
        cleaned = "\n".join(lines).strip()
        if cleaned:
            conn.execute(cleaned)

    console.print("[green]IPL schema created (from ipl_enrichment_schema.sql).[/]")


def seed_franchises(conn: duckdb.DuckDBPyConnection) -> None:
    """Insert all IPL franchise records + venues. Idempotent (INSERT OR REPLACE)."""
    for fid, f in IPL_FRANCHISES.items():
        conn.execute(
            """
            INSERT OR REPLACE INTO ipl_franchise
            (id, name, short_name, cricsheet_name, primary_color, secondary_color,
             accent_color, logo_url, founded_year, defunct, successor_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                fid,
                f["name"],
                f["short_name"],
                f["cricsheet_name"],
                f["primary_color"],
                f.get("secondary_color"),
                f.get("accent_color"),
                None,  # logo_url — to be added later
                f["founded_year"],
                f.get("defunct", False),
                f.get("successor_id"),
            ],
        )

        # Seed venues into ipl_franchise_venue
        for v in f.get("venues", []):
            conn.execute(
                """
                INSERT OR REPLACE INTO ipl_franchise_venue
                (franchise_id, venue_name, city, season_from, season_to, is_primary)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    fid,
                    v["name"],
                    v["city"],
                    v["season_from"],
                    v.get("season_to"),
                    v.get("is_primary", True),
                ],
            )

    console.print(f"  Seeded [cyan]{len(IPL_FRANCHISES)}[/] IPL franchises + venues")


def seed_auction_cycles(conn: duckdb.DuckDBPyConnection) -> None:
    """Insert auction cycle definitions. Idempotent (INSERT OR REPLACE)."""
    for ac in AUCTION_CYCLES:
        conn.execute(
            """
            INSERT OR REPLACE INTO ipl_auction_cycle
            (id, cycle_name, start_season, end_season, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            [ac["id"], ac["cycle_name"], ac["start_season"], ac["end_season"], ac["description"]],
        )

    console.print(f"  Seeded [cyan]{len(AUCTION_CYCLES)}[/] auction cycles")
