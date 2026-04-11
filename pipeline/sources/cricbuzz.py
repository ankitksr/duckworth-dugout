"""Cricbuzz standings source — primary live points table.

Cricbuzz renders its series points table with a Next.js RSC payload
that embeds `pointsTableInfo` as an escaped JSON array inline in the
HTML. We fetch via crawl4ai (real-browser TLS fingerprint is more
robust against datacenter-IP blocking than plain curl), slurp the
brace-balanced array, unescape, and parse.

Cricbuzz typically reflects match results within minutes of a match
ending, which is why this sits at the top of the standings cascade.
"""

from __future__ import annotations

import asyncio
import json

from rich.console import Console

from pipeline.ipl.franchise_metadata import IPL_FRANCHISES
from pipeline.models import StandingsRow

console = Console()

# Cricbuzz series IDs are annual. Add next year's entry when the season
# rolls over — the URL pattern is stable.
# TODO(2027): add "2027" mapping.
_SERIES_IDS: dict[str, str] = {
    "2026": "9241",
}

# teamName (uppercase short) → franchise_id
_SHORT_TO_FID: dict[str, str] = {
    (v.get("short_name") or "").upper(): fid
    for fid, v in IPL_FRANCHISES.items()
    if not v.get("defunct")
}


def fetch_cricbuzz_standings(season: str) -> list[StandingsRow]:
    """Fetch the IPL points table from Cricbuzz. Returns [] on failure."""
    series_id = _SERIES_IDS.get(season)
    if not series_id:
        console.print(
            f"  [yellow]Cricbuzz: no series id for season {season}[/yellow]"
        )
        return []

    url = (
        f"https://www.cricbuzz.com/cricket-series/{series_id}"
        f"/indian-premier-league-{season}/points-table"
    )

    try:
        html = asyncio.run(_crawl(url))
    except Exception as e:
        console.print(f"  [yellow]Cricbuzz crawl error: {e}[/yellow]")
        return []

    if not html:
        console.print("  [yellow]Cricbuzz: empty response (IP block?)[/yellow]")
        return []

    payload = _extract_points_table_json(html)
    if payload is None:
        console.print("  [yellow]Cricbuzz: pointsTableInfo not found[/yellow]")
        return []

    rows: list[StandingsRow] = []
    for i, t in enumerate(payload, start=1):
        short = (t.get("teamName") or "").upper()
        fid = _SHORT_TO_FID.get(short)
        if not fid:
            console.print(
                f"  [yellow]Cricbuzz: unknown team {short!r}, skipping[/yellow]"
            )
            continue

        franchise = IPL_FRANCHISES.get(fid, {})
        rows.append(StandingsRow(
            franchise_id=fid,
            short_name=short,
            primary_color=franchise.get("primary_color", "#888888"),
            played=int(t.get("matchesPlayed", 0)),
            wins=int(t.get("matchesWon", 0)),
            losses=int(t.get("matchesLost", 0)),
            no_results=int(t.get("noRes", 0)),
            points=int(t.get("points", 0)),
            nrr=str(t.get("nrr") or "-"),
            position=i,
            qualified=False,
        ))

    if rows:
        console.print(
            f"  [green]Standings: parsed {len(rows)} teams from Cricbuzz[/green]"
        )
    return rows


async def _crawl(url: str) -> str:
    """Render the Cricbuzz points table page via crawl4ai."""
    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url, config=CrawlerRunConfig())
        r = result._results[0] if hasattr(result, "_results") else result
        return r.html if hasattr(r, "html") else ""


def _extract_points_table_json(html: str) -> list[dict] | None:
    """Pull the `pointsTableInfo` array out of Cricbuzz's RSC payload.

    The payload is an escaped JSON string — double-quotes appear as
    `\\"`. We find the marker, walk from the opening `[` to its matching
    `]` with a simple depth counter (which handles nested objects and
    arrays inside each team entry), unescape, and JSON-parse.
    """
    needle = 'pointsTableInfo\\":'
    idx = html.find(needle)
    if idx == -1:
        return None

    start = html.find("[", idx)
    if start == -1:
        return None

    depth = 0
    in_string = False
    i = start
    while i < len(html):
        c = html[i]
        if c == "\\" and not in_string:
            i += 2
            continue
        if c == '"' and (i == 0 or html[i - 1] != "\\"):
            in_string = not in_string
        elif not in_string:
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    break
        i += 1
    else:
        return None

    raw = html[start:i + 1].replace('\\"', '"').replace("\\\\", "\\")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None
