"""ESPNcricinfo standings source — secondary live points table.

Reads the series points-table page and pulls standings out of the
Next.js `__NEXT_DATA__` blob. Used as a fallback behind Cricbuzz.

Akamai blocks plain curl with 403, so fetch must go through crawl4ai
(real-browser TLS fingerprint).
"""

from __future__ import annotations

import asyncio
import json
import re

from rich.console import Console

from pipeline.ipl.franchise_metadata import IPL_FRANCHISES
from pipeline.models import StandingsRow

console = Console()

_NEXT_DATA_RE = re.compile(
    r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)

# ESPNcricinfo series IDs are annual. Add next year's entry when the
# season rolls over — the URL pattern is stable.
# TODO(2027): add "2027" mapping.
_SERIES_IDS: dict[str, str] = {
    "2026": "1510719",
}

_SHORT_TO_FID: dict[str, str] = {
    (v.get("short_name") or "").upper(): fid
    for fid, v in IPL_FRANCHISES.items()
    if not v.get("defunct")
}


def fetch_espn_standings(season: str) -> list[StandingsRow]:
    """Fetch the IPL points table from ESPNcricinfo. Returns [] on failure."""
    series_id = _SERIES_IDS.get(season)
    if not series_id:
        console.print(
            f"  [yellow]ESPN: no series id for season {season}[/yellow]"
        )
        return []

    url = (
        f"https://www.espncricinfo.com/series/ipl-{season}-{series_id}"
        f"/points-table-standings"
    )

    try:
        html = asyncio.run(_crawl(url))
    except Exception as e:
        console.print(f"  [yellow]ESPN crawl error: {e}[/yellow]")
        return []

    if not html:
        console.print("  [yellow]ESPN: empty response (WAF block?)[/yellow]")
        return []

    m = _NEXT_DATA_RE.search(html)
    if not m:
        console.print("  [yellow]ESPN: __NEXT_DATA__ not found[/yellow]")
        return []

    try:
        raw = json.loads(m.group(1))
        team_stats = (
            raw["props"]["appPageProps"]["data"]["data"]["content"]
            ["standings"]["groups"][0]["teamStats"]
        )
    except (KeyError, IndexError, json.JSONDecodeError, AttributeError):
        console.print("  [yellow]ESPN: standings path missing[/yellow]")
        return []

    rows: list[StandingsRow] = []
    for t in team_stats:
        info = t.get("teamInfo") or {}
        short = (info.get("abbreviation") or "").upper()
        fid = _SHORT_TO_FID.get(short)
        if not fid:
            console.print(
                f"  [yellow]ESPN: unknown team {short!r}, skipping[/yellow]"
            )
            continue

        franchise = IPL_FRANCHISES.get(fid, {})
        nrr_raw = t.get("nrr")
        try:
            nrr = f"{float(nrr_raw):+.3f}" if nrr_raw is not None else "-"
        except (TypeError, ValueError):
            nrr = "-"

        rows.append(StandingsRow(
            franchise_id=fid,
            short_name=short,
            primary_color=franchise.get("primary_color", "#888888"),
            war_room_color=franchise.get(
                "war_room_color", franchise.get("primary_color", "#888888")
            ),
            played=int(t.get("matchesPlayed") or 0),
            wins=int(t.get("matchesWon") or 0),
            losses=int(t.get("matchesLost") or 0),
            no_results=int(t.get("matchesNoResult") or 0),
            points=int(t.get("points") or 0),
            nrr=nrr,
            position=int(t.get("rank") or (len(rows) + 1)),
            qualified=False,
        ))

    if rows:
        console.print(
            f"  [green]Standings: parsed {len(rows)} teams from ESPNcricinfo[/green]"
        )
    return rows


async def _crawl(url: str) -> str:
    """Render the ESPN points-table page via crawl4ai."""
    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url, config=CrawlerRunConfig())
        r = result._results[0] if hasattr(result, "_results") else result
        return r.html if hasattr(r, "html") else ""
