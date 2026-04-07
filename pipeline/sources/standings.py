"""Standings panel — parse IPL points table from Wisden RSS feed.

Primary: Wisden HTML table. Fallback handled by cricsheet.py (called from sync.py).
"""

from html.parser import HTMLParser

from rich.console import Console

from pipeline.ipl.franchise_metadata import IPL_FRANCHISES
from pipeline.models import StandingsRow
from pipeline.sources.rss import FeedItem

console = Console()

# Reverse lookup: lowercased team name/short_name → (franchise_id, short_name, color)
_NAME_TO_FRANCHISE: dict[str, tuple[str, str, str]] = {}
for _fid, _fdata in IPL_FRANCHISES.items():
    if _fdata.get("defunct"):
        continue
    _info = (_fid, _fdata["short_name"], _fdata.get("war_room_color", _fdata["primary_color"]))
    for _name in _fdata["cricsheet_names"]:
        _NAME_TO_FRANCHISE[_name.lower()] = _info
    # Also register the short name (e.g. "CSK" → csk)
    _NAME_TO_FRANCHISE[_fdata["short_name"].lower()] = _info


class _TableParser(HTMLParser):
    """Extract rows from HTML <table> elements.

    Tracks table boundaries so callers can distinguish multiple tables
    in the same HTML (e.g. CricketAddictor's combined standings + caps article).

    Attributes:
        rows: Flat list of all rows across all tables (backwards-compatible).
        tables: List of tables, each a list of rows — use when the HTML
                contains multiple tables (standings, orange cap, purple cap).
    """

    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.rows: list[list[str]] = []
        self.tables: list[list[list[str]]] = []
        self._current_row: list[str] = []
        self._current_cell = ""
        self._current_table: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.in_table = True
            self._current_table = []
        elif tag == "tr" and self.in_table:
            self.in_row = True
            self._current_row = []
        elif tag in ("td", "th") and self.in_row:
            self.in_cell = True
            self._current_cell = ""

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self.in_cell:
            self.in_cell = False
            self._current_row.append(self._current_cell.strip())
        elif tag == "tr" and self.in_row:
            self.in_row = False
            if self._current_row:
                self.rows.append(self._current_row)
                self._current_table.append(self._current_row)
        elif tag == "table":
            self.in_table = False
            if self._current_table:
                self.tables.append(self._current_table)
            self._current_table = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self._current_cell += data


def _parse_int(val: str) -> int:
    """Parse an integer, treating '-' or empty as 0."""
    val = val.strip()
    if not val or val == "-":
        return 0
    try:
        return int(val)
    except ValueError:
        return 0


def _resolve_team(name: str) -> tuple[str, str, str] | None:
    """Resolve a team name to (franchise_id, short_name, primary_color)."""
    key = name.strip().lower()
    if key in _NAME_TO_FRANCHISE:
        return _NAME_TO_FRANCHISE[key]
    # Fuzzy: check if any known name is a substring
    for known, info in _NAME_TO_FRANCHISE.items():
        if known in key or key in known:
            return info
    return None


def _standings_from_table_rows(table_rows: list[list[str]]) -> list[StandingsRow] | None:
    """Parse a standings table given header + data rows.

    Accepts rows from a single HTML table (first row = header).
    Returns None if parsing fails.
    """
    if len(table_rows) < 2:
        return None

    header = [h.lower().strip() for h in table_rows[0]]

    col_map: dict[str, int] = {}
    for i, h in enumerate(header):
        for key in ("rank", "no.", "#", "pos"):
            if key in h:
                col_map["rank"] = i
                break
        if "team" in h:
            col_map["team"] = i
        if h in ("matches", "mat", "m", "p", "pld", "played"):
            col_map["played"] = i
        if h in ("won", "w"):
            col_map["won"] = i
        if h in ("lost", "l"):
            col_map["lost"] = i
        if h in ("tied", "t"):
            col_map["tied"] = i
        if h in ("n/r", "nr", "no result"):
            col_map["nr"] = i
        if h in ("points", "pts"):
            col_map["points"] = i
        if h in ("nrr", "net run rate"):
            col_map["nrr"] = i

    if "team" not in col_map:
        return None

    rows: list[StandingsRow] = []
    for i, row in enumerate(table_rows[1:], 1):
        if len(row) <= col_map["team"]:
            continue

        team_name = row[col_map["team"]]
        resolved = _resolve_team(team_name)
        if resolved is None:
            continue

        fid, short, color = resolved
        nrr_col = col_map.get("nrr", 99)
        nrr_val = row[nrr_col].strip() if nrr_col < len(row) else "-"

        def _col_val(key: str) -> str:
            idx = col_map.get(key, 99)
            return row[idx] if idx < len(row) else "0"

        rows.append(StandingsRow(
            franchise_id=fid,
            short_name=short,
            primary_color=color,
            played=_parse_int(_col_val("played")),
            wins=_parse_int(_col_val("won")),
            losses=_parse_int(_col_val("lost")),
            no_results=_parse_int(_col_val("nr")),
            points=_parse_int(_col_val("points")),
            nrr=nrr_val,
            position=i,
            qualified=i <= 4,
        ))

    return rows or None


def parse_standings(wisden_items: list[FeedItem]) -> list[StandingsRow] | None:
    """Find the points table article in Wisden items and parse it.

    Returns None if the article is not found or parsing fails.
    """
    article = None
    for item in wisden_items:
        title = item.title.lower()
        if "points table" in title and "ipl" in title:
            article = item
            break

    if article is None:
        console.print(
            "  [yellow]Standings: IPL points table article"
            " not found in Wisden feed[/yellow]"
        )
        return None

    encoded = article.raw.get("encoded", "")
    if not encoded:
        console.print("  [yellow]Standings: no content:encoded in article[/yellow]")
        return None

    parser = _TableParser()
    parser.feed(encoded)

    # Use the first table (Wisden articles have one standings table)
    table_rows = parser.tables[0] if parser.tables else parser.rows
    rows = _standings_from_table_rows(table_rows)

    if rows and len(rows) >= 8:
        console.print(
            f"  [green]Standings: parsed {len(rows)} teams"
            " from Wisden[/green]"
        )
        return rows

    console.print(
        "  [yellow]Standings: no team rows parsed"
        " from Wisden[/yellow]"
    )
    return None


def parse_standings_from_feed(
    items: list[FeedItem],
    source_name: str = "feed",
) -> list[StandingsRow] | None:
    """Parse standings from any RSS feed with a points-table article.

    Works with CricketAddictor and similar WordPress feeds that embed
    HTML tables in content:encoded. The standings table is identified
    as the one whose header contains a "team" column and whose data
    rows resolve to known IPL franchises.

    Returns None if no suitable article or table is found.
    """
    # Find articles mentioning "points table" or "standings"
    for item in items:
        title_lower = item.title.lower()
        if "points table" not in title_lower and "standings" not in title_lower:
            continue

        encoded = item.raw.get("encoded", "")
        if not encoded:
            continue

        parser = _TableParser()
        parser.feed(encoded)

        # Try each table — the standings table has a "team" column and
        # its data rows resolve to IPL franchises
        for table_rows in parser.tables:
            rows = _standings_from_table_rows(table_rows)
            if rows and len(rows) >= 8:  # IPL has 10 teams; require at least 8
                console.print(
                    f"  [green]Standings: parsed {len(rows)} teams"
                    f" from {source_name}[/green]"
                )
                return rows

    console.print(f"  [yellow]Standings: no points table found in {source_name} feed[/yellow]")
    return None
