"""Cap Race panel — Orange/Purple Cap leaderboards.

Primary: Wisden RSS (HTML table parse).
Fallback: Cricsheet batting/bowling scorecards (via cricsheet.py).
ESPNcricinfo: crawl4ai-powered scrape for SR, Economy, MVP (top 3).
"""

import asyncio
import re

from rich.console import Console

from pipeline.ipl.franchise_metadata import IPL_FRANCHISES
from pipeline.models import CapEntry, CapsData
from pipeline.sources.rss import FeedItem
from pipeline.sources.standings import _TableParser

console = Console()

# Historical / evergreen article markers — articles that mention "purple cap"
# or "orange cap" but list all-time winners (e.g. Bravo, Malinga) rather than
# the current season's leaderboard. Wisden recycles these pieces through its
# RSS feed, so the title is our only cheap signal to skip them.
_HISTORICAL_TITLE_RE = re.compile(
    r"\b("
    r"all[\s-]?time|history|ever|greatest|most[\s-]+(?:ever|in\s+ipl\s+history)"
    r"|winners?[\s-]+list|list\s+of\s+all|complete\s+list"
    r"|season[\s-]by[\s-]season|year[\s-]by[\s-]year|by[\s-]season"
    r"|every\s+season|hall\s+of\s+fame|retired|legends?|throwback"
    r")\b",
    re.IGNORECASE,
)


def _is_historical_title(title: str) -> bool:
    """True if the title looks like a historical/all-time recap, not current season."""
    return bool(_HISTORICAL_TITLE_RE.search(title))


# Reverse lookups for team resolution
_SHORT_TO_FRANCHISE: dict[str, tuple[str, str]] = {}
_NAME_TO_FRANCHISE: dict[str, tuple[str, str]] = {}
for _fid, _fdata in IPL_FRANCHISES.items():
    if _fdata.get("defunct"):
        continue
    _SHORT_TO_FRANCHISE[_fdata["short_name"].lower()] = (_fid, _fdata["short_name"])
    for _name in _fdata["cricsheet_names"]:
        _NAME_TO_FRANCHISE[_name.lower()] = (_fid, _fdata["short_name"])


def _resolve_team_short(name: str) -> tuple[str, str]:
    key = name.strip().lower()
    if key in _SHORT_TO_FRANCHISE:
        return _SHORT_TO_FRANCHISE[key]
    if key in _NAME_TO_FRANCHISE:
        return _NAME_TO_FRANCHISE[key]
    for known, info in _NAME_TO_FRANCHISE.items():
        if known in key or key in known:
            return info
    return ("", name.strip())


def _entries_from_table_rows(
    table_rows: list[list[str]],
    stat_label: str,
) -> list[CapEntry]:
    """Parse a cap leaderboard from a single table's rows (header + data)."""
    if len(table_rows) < 2:
        return []

    header = [h.lower().strip() for h in table_rows[0]]
    col_player = col_team = col_stat = None
    for i, h in enumerate(header):
        if "player" in h or "batter" in h or "bowler" in h:
            col_player = i
        elif "team" in h:
            col_team = i
        elif stat_label == "runs" and ("runs" in h or "run" in h):
            col_stat = i
        elif stat_label == "wkts" and ("wicket" in h or "wkt" in h):
            col_stat = i

    if col_player is None:
        return []

    entries = []
    for rank, row in enumerate(table_rows[1:], 1):
        if col_player >= len(row):
            continue
        player = row[col_player].strip()
        if not player:
            continue
        team_str = row[col_team].strip() if col_team is not None and col_team < len(row) else ""
        fid, short = _resolve_team_short(team_str)
        if col_stat is not None and col_stat < len(row):
            stat_val = f"{row[col_stat].strip()} {stat_label}"
        else:
            stat_val = ""
        entries.append(CapEntry(
            rank=rank, player=player, team=fid,
            team_short=short, stat=stat_val,
        ))
    return entries


def _parse_cap_table(encoded: str, stat_label: str) -> list[CapEntry]:
    """Parse a cap leaderboard from article HTML (first table only).

    Kept for Wisden articles which have one cap table per article.
    """
    parser = _TableParser()
    parser.feed(encoded)
    table_rows = parser.tables[0] if parser.tables else parser.rows
    return _entries_from_table_rows(table_rows, stat_label)


def parse_caps(
    wisden_items: list[FeedItem],
    top_n: int = 10,
    season: str | None = None,
) -> CapsData:
    """Parse Orange/Purple Cap articles from Wisden feed.

    Prefers articles whose title references ``season`` (current season) and
    skips anything that looks like a historical/all-time recap — otherwise
    evergreen Wisden pieces ("IPL Purple Cap winners list", "Most Purple
    Caps of all time") pollute the leaderboard with retired players.
    """
    orange: list[CapEntry] = []
    purple: list[CapEntry] = []
    updated: str | None = None

    # Two-pass: prefer articles matching the current season, fall back to
    # any non-historical cap article if no season-tagged article is found.
    ordered = list(wisden_items)
    if season:
        ordered.sort(key=lambda it: 0 if season in (it.title or "") else 1)

    for item in ordered:
        title = item.title.lower()
        encoded = item.raw.get("encoded", "")
        if not encoded:
            continue

        if _is_historical_title(title):
            continue

        if "orange cap" in title and not orange:
            parsed = _parse_cap_table(encoded, "runs")
            if parsed:
                orange = parsed
                if item.published:
                    pub = item.published
                    updated = (
                        pub.isoformat()
                        if hasattr(pub, "isoformat") else str(pub)
                    )
                console.print(
                    f"  [green]Orange Cap: parsed"
                    f" {len(orange)} entries[/green]"
                )
        elif "purple cap" in title and not purple:
            parsed = _parse_cap_table(encoded, "wkts")
            if parsed:
                purple = parsed
                if item.published and not updated:
                    pub = item.published
                    updated = (
                        pub.isoformat()
                        if hasattr(pub, "isoformat") else str(pub)
                    )
                console.print(
                    f"  [green]Purple Cap: parsed"
                    f" {len(purple)} entries[/green]"
                )

    if not orange and not purple:
        console.print("  [yellow]Caps: no cap articles found in Wisden feed[/yellow]")

    return CapsData(orange_cap=orange[:top_n], purple_cap=purple[:top_n], updated=updated)


def parse_caps_from_feed(
    items: list[FeedItem],
    source_name: str = "feed",
    top_n: int = 10,
    season: str | None = None,
) -> CapsData:
    """Parse Orange/Purple Cap from any RSS feed.

    Handles two patterns:
    1. Separate articles per cap (like Wisden) — title contains "orange cap" or "purple cap"
    2. Combined article (like CricketAddictor) — title contains both; tables appear
       after the standings table, identified by header keywords (runs/wickets + player).

    Historical/all-time articles are skipped; season-tagged articles are tried first.
    """
    orange: list[CapEntry] = []
    purple: list[CapEntry] = []
    updated: str | None = None

    ordered = list(items)
    if season:
        ordered.sort(key=lambda it: 0 if season in (it.title or "") else 1)

    for item in ordered:
        title = item.title.lower()
        encoded = item.raw.get("encoded", "")
        if not encoded:
            continue

        has_orange = "orange cap" in title
        has_purple = "purple cap" in title
        if not has_orange and not has_purple:
            continue

        if _is_historical_title(title):
            continue

        if item.published:
            pub = item.published
            updated = pub.isoformat() if hasattr(pub, "isoformat") else str(pub)

        parser = _TableParser()
        parser.feed(encoded)

        if has_orange and has_purple and len(parser.tables) >= 2:
            # Combined article: identify cap tables by header content.
            # The standings table has "team" + "pts"/"points" headers.
            # Cap tables have "player"/"batter"/"bowler" + "runs"/"wickets" headers.
            for table_rows in parser.tables:
                if len(table_rows) < 2:
                    continue
                header_str = " ".join(h.lower() for h in table_rows[0])
                if not orange and ("run" in header_str or "batter" in header_str):
                    # Heuristic: if header mentions runs/batter, it's orange cap
                    if "team" not in header_str or "pts" not in header_str:
                        orange = _entries_from_table_rows(table_rows, "runs")
                elif not purple and (
                    "wicket" in header_str or "wkt" in header_str
                    or "bowler" in header_str
                ):
                    purple = _entries_from_table_rows(table_rows, "wkts")
        else:
            # Separate articles (Wisden-style)
            table_rows = parser.tables[0] if parser.tables else parser.rows
            if has_orange and not orange:
                orange = _entries_from_table_rows(table_rows, "runs")
            elif has_purple and not purple:
                purple = _entries_from_table_rows(table_rows, "wkts")

    if orange or purple:
        console.print(
            f"  [green]Caps: {len(orange)} Orange, {len(purple)} Purple from {source_name}[/green]"
        )
    else:
        console.print(f"  [yellow]Caps: no cap tables found in {source_name} feed[/yellow]")

    return CapsData(orange_cap=orange[:top_n], purple_cap=purple[:top_n], updated=updated)


def caps_from_cricsheet(season: str, top_n: int = 10) -> CapsData:
    """Fallback: query Cricsheet batting/bowling scorecards directly."""
    from pipeline.sources.cricsheet import query_caps
    return query_caps(season, top_n)


# ── ESPNcricinfo stats crawl (crawl4ai) ───────────────────────────────

_STATS_URL = (
    "https://www.espncricinfo.com/series/ipl-{season}-{series_id}/stats"
)

# Section headers in the crawled markdown
_SECTION_HEADERS = {
    "top run scorers": "orange",
    "top wicket takers": "purple",
    "best batting strike rates": "sr",
    "best bowling economy": "econ",
}


def _parse_player_card(lines: list[str], start: int) -> tuple[str, str, str, int | None, int]:
    """Parse a single player card from the crawled markdown.

    A card looks like:
        [![Sameer Rizvi](img)](profile_url)
        [Sameer Rizvi](profile_url)
        DC, Rhb
        160
        Innings: 2Average: 160.00

    Or in the Smart Stats section:
        [![Sameer Rizvi](img)](profile_url)
        [ Sameer Rizvi](profile_url "Sameer Rizvi")
        DC, Rhb
        190.66
        Impact pts

    Returns (player_name, team_short, stat_value, innings, lines_consumed).
    """
    player = ""
    team_short = ""
    stat_val = ""
    innings: int | None = None
    i = start

    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith("[!["):
            # Skip empty lines and image-link tags (player photo)
            i += 1
            continue

        # Player name: [Name](url) or [ Name](url "Title")
        m = re.match(r"\[([^\]]+)\]\(.*cricketers.*\)", line)
        if m and not player:
            player = m.group(1).strip()
            i += 1
            continue

        # Team + style line: "DC, Rhb" or "RCB, Rfm"
        if player and not team_short and re.match(r"^[A-Z]{2,5},\s", line):
            team_short = line.split(",")[0].strip()
            i += 1
            continue

        # Stat value: standalone number (runs, wickets, SR, economy, impact pts)
        if player and team_short and not stat_val:
            if re.match(r"^[\d.]+$", line):
                stat_val = line
                i += 1
                # Extract innings from trailing metadata: "Innings: 2Average: 160.00"
                while i < len(lines):
                    nxt = lines[i].strip()
                    if nxt.startswith("Innings:"):
                        inn_m = re.match(r"Innings:\s*(\d+)", nxt)
                        if inn_m:
                            innings = int(inn_m.group(1))
                        i += 1
                    elif nxt.startswith(("Impact pts", "Runs:", "Actual")):
                        i += 1
                    else:
                        break
                return player, team_short, stat_val, innings, i

        # If we hit a section header or "View full list", card is done
        if line.startswith("###") or "View full list" in line:
            break

        i += 1

    return player, team_short, stat_val, innings, i


def _parse_espncricinfo_markdown(markdown: str) -> CapsData:
    """Parse the crawled ESPNcricinfo stats page markdown into CapsData."""
    lines = markdown.split("\n")
    result: dict[str, list[CapEntry]] = {
        "orange": [], "purple": [], "sr": [], "econ": [], "mvp": [],
    }

    i = 0
    current_section: str | None = None

    while i < len(lines):
        line = lines[i].strip()

        # Detect MVP: "Total Impact" appears as plain text (no ### header)
        if line.lower() == "total impact" and current_section != "mvp":
            current_section = "mvp"
            i += 1
            # Parse MVP cards (same loop below will handle it)
            rank = 1
            while rank <= 3 and i < len(lines):
                stripped = lines[i].strip()
                if stripped.startswith("###") or "View full list" in stripped:
                    break
                if stripped.startswith("[![") or (
                    stripped.startswith("[") and "cricketers" in stripped
                ):
                    player, team_short, stat_val, _inn, i = _parse_player_card(lines, i)
                    if player and team_short and stat_val:
                        fid, short = _resolve_team_short(team_short)
                        result["mvp"].append(CapEntry(
                            rank=rank, player=player, team=fid,
                            team_short=short, stat=f"{stat_val} pts",
                        ))
                        rank += 1
                    continue
                i += 1
            current_section = None
            continue

        # Detect section headers: "### Top Run Scorers"
        if line.startswith("###"):
            header_text = line.lstrip("#").strip().lower()

            current_section = None
            for key, section in _SECTION_HEADERS.items():
                if key in header_text:
                    current_section = section
                    break

            i += 1
            if current_section is None:
                continue

            # Parse up to 3 player cards for this section
            rank = 1
            while rank <= 3 and i < len(lines):
                stripped = lines[i].strip()
                # Stop at next section or "View full list"
                if stripped.startswith("###") or "View full list" in stripped:
                    break
                # Look for the start of a player card (image or link)
                if stripped.startswith("[![") or (
                    stripped.startswith("[") and "cricketers" in stripped
                ):
                    player, team_short, stat_val, innings, i = _parse_player_card(lines, i)
                    if player and team_short and stat_val:
                        fid, short = _resolve_team_short(team_short)
                        # Format stat label per category
                        if current_section == "orange":
                            stat = f"{stat_val} runs"
                        elif current_section == "purple":
                            stat = f"{stat_val} wkts"
                        elif current_section == "sr":
                            stat = stat_val
                        elif current_section == "econ":
                            stat = stat_val
                        elif current_section == "mvp":
                            stat = f"{stat_val} pts"
                        else:
                            stat = stat_val

                        # Only attach innings for SR and Economy
                        entry_innings = innings if current_section in ("sr", "econ") else None
                        result[current_section].append(CapEntry(
                            rank=rank, player=player, team=fid,
                            team_short=short, stat=stat,
                            innings=entry_innings,
                        ))
                        rank += 1
                    continue
                i += 1
            continue

        i += 1

    has_data = any(result[k] for k in result)
    if has_data:
        console.print(
            f"  [green]ESPNcricinfo:"
            f" {len(result['orange'])} Orange,"
            f" {len(result['purple'])} Purple,"
            f" {len(result['sr'])} SR,"
            f" {len(result['econ'])} Econ,"
            f" {len(result['mvp'])} MVP[/green]"
        )
    else:
        console.print("  [yellow]ESPNcricinfo: no stats parsed[/yellow]")

    return CapsData(
        orange_cap=result["orange"],
        purple_cap=result["purple"],
        best_sr=result["sr"],
        best_econ=result["econ"],
        mvp=result["mvp"],
    )


async def _crawl_espncricinfo_stats(url: str) -> str | None:
    """Crawl the ESPNcricinfo stats page via crawl4ai."""
    try:
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=CrawlerRunConfig())
            r = result._results[0] if hasattr(result, "_results") else result
            md = r.markdown_v2.raw_markdown if hasattr(r, "markdown_v2") else r.markdown
            return md or None
    except Exception as e:
        console.print(f"  [yellow]ESPNcricinfo crawl error: {e}[/yellow]")
        return None


def caps_from_espncricinfo(
    season: str,
    series_id: str = "1510719",
) -> CapsData | None:
    """Crawl ESPNcricinfo stats page for cap race data (top 3 per category).

    Returns CapsData with best_sr, best_econ, mvp (primary use), plus
    orange_cap and purple_cap (fallback use — top 3 only).
    """
    url = _STATS_URL.format(season=season, series_id=series_id)
    console.print(f"  Crawling ESPNcricinfo stats: {url}")

    md = asyncio.run(_crawl_espncricinfo_stats(url))
    if not md:
        return None

    return _parse_espncricinfo_markdown(md)
