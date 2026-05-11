"""Wikipedia-backed IPL standings, fixtures, and caps fallbacks."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from rich.console import Console

from pipeline.cache.manager import CacheManager
from pipeline.ipl.franchise_metadata import IPL_FRANCHISES
from pipeline.models import ScheduleMatch
from pipeline.sources.caps import CapEntry, CapsData
from pipeline.sources.standings import _standings_from_table_rows
from pipeline.sources.wikipedia_fetch import fetch_personnel_wikitext, fetch_season_wikitext
from pipeline.sources.wikipedia_parser import (
    _is_transient_result,
    parse_ipl_fixtures,
    parse_ipl_match_summary,
    parse_ipl_points_table,
    parse_ipl_squads,
    parse_ipl_statistics,
)

console = Console()
_TTL = timedelta(minutes=5)


def _cache_path(cache: CacheManager, season: str) -> Path:
    safe_key = cache._safe_filename(f"live_season_{season}")
    return cache.base_dir / "wikipedia" / "ipl" / f"{safe_key}.json"


def _is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return datetime.now(timezone.utc) - modified < _TTL


def _get_wikitext(season: str, *, force: bool = False) -> str | None:
    cache = CacheManager()
    path = _cache_path(cache, season)
    return fetch_season_wikitext(int(season), force=force or not _is_fresh(path), cache=cache)


def fetch_wikipedia_standings(season: str) -> list | None:
    wikitext = _get_wikitext(season)
    if not wikitext:
        return None
    rows = parse_ipl_points_table(wikitext)
    if not rows:
        return None
    parsed = _standings_from_table_rows(rows)
    if parsed:
        console.print(f"  [green]Standings: parsed {len(parsed)} teams from Wikipedia[/green]")
    return parsed


def fetch_wikipedia_caps(season: str, top_n: int = 10) -> CapsData | None:
    wikitext = _get_wikitext(season)
    if not wikitext:
        return None
    stats = parse_ipl_statistics(wikitext)
    orange = [
        CapEntry(
            rank=index,
            player=entry["player"],
            team=entry.get("team") or "",
            team_short=(entry.get("team") or "").upper(),
            stat=f'{int(entry["value"])} runs',
        )
        for index, entry in enumerate(stats.get("most_runs", []), 1)
    ]
    purple = [
        CapEntry(
            rank=index,
            player=entry["player"],
            team=entry.get("team") or "",
            team_short=(entry.get("team") or "").upper(),
            stat=f'{int(entry["value"])} wkts',
        )
        for index, entry in enumerate(stats.get("most_wickets", []), 1)
    ]
    mvp = [
        CapEntry(
            rank=index,
            player=entry["player"],
            team=entry.get("team") or "",
            team_short=(entry.get("team") or "").upper(),
            stat=f'{entry["value"]} pts',
        )
        for index, entry in enumerate(stats.get("mvp", []), 1)
    ]
    if not orange and not purple:
        return None
    console.print(
        f"  [green]Caps: {len(orange)} Orange, {len(purple)} Purple,"
        f" {len(mvp)} MVP from Wikipedia[/green]"
    )
    return CapsData(orange_cap=orange[:top_n], purple_cap=purple[:top_n], mvp=mvp[:top_n])


def _winner_from_result(fixture: dict) -> str | None:
    result = (fixture.get("result") or "").lower()
    for team_key in ("team1", "team2"):
        fid = fixture.get(team_key)
        if not fid:
            continue
        franchise = IPL_FRANCHISES.get(fid, {})
        names = [
            franchise.get("name", ""),
            franchise.get("short_name", ""),
            *franchise.get("cricsheet_names", []),
        ]
        if any(name and name.lower() in result for name in names):
            return fid
    return None


def _result_from_summary(summary: dict) -> tuple[str | None, str | None]:
    code = (summary.get("result") or "").upper()
    margin = (summary.get("margin") or "").strip()
    if code == "N":
        return None, "No result"

    winner = None
    if code == "H":
        winner = summary.get("home")
    elif code == "A":
        winner = summary.get("away")
    if not winner:
        return None, None

    franchise = IPL_FRANCHISES.get(winner, {})
    winner_name = franchise.get("name") or franchise.get("short_name") or winner.upper()
    suffix = ""
    if margin:
        margin_upper = margin.upper()
        if margin_upper.endswith("W"):
            suffix = f" by {margin_upper[:-1]} wickets"
        elif margin_upper.endswith("R"):
            suffix = f" by {margin_upper[:-1]} runs"
        else:
            suffix = f" by {margin}"
    if summary.get("dls"):
        suffix = f"{suffix} (DLS)" if suffix else " (DLS)"
    return winner, f"{winner_name} won{suffix}"


def overlay_wikipedia_fixtures(matches: list[ScheduleMatch], season: str) -> list[ScheduleMatch]:
    wikitext = _get_wikitext(season)
    if not wikitext:
        return matches

    by_number = {match.match_number: match for match in matches}
    summaries = {
        row["match_number"]: row
        for row in parse_ipl_match_summary(wikitext)
    }
    count = 0
    for fixture in parse_ipl_fixtures(wikitext):
        match = by_number.get(fixture["match_number"])
        if not match:
            continue
        # Wikipedia's team1/team2 order in a fixture block doesn't
        # always agree with our fixtures.json ordering (Wikipedia often
        # lists the away/touring side first; we follow Cricsheet's
        # ordering). Align by franchise id so score1/overs1/top_batter1
        # map to *match.team1* — not to Wikipedia's positional team1.
        swap = (
            fixture.get("team1") == match.team2
            and fixture.get("team2") == match.team1
        )
        if swap:
            fixture = {
                **fixture,
                "team1": match.team1,
                "team2": match.team2,
                "score1": fixture.get("score2"),
                "score2": fixture.get("score1"),
                "overs1": fixture.get("overs2"),
                "overs2": fixture.get("overs1"),
                "top_batter1": fixture.get("top_batter2"),
                "top_batter2": fixture.get("top_batter1"),
                "top_bowler1": fixture.get("top_bowler2"),
                "top_bowler2": fixture.get("top_bowler1"),
            }
        summary = summaries.get(fixture["match_number"])
        summary_winner, summary_result = _result_from_summary(summary or {})
        completed = fixture["status"] == "completed" or summary_result is not None
        if not completed:
            # Wikipedia says match isn't completed. If our prior state has
            # it stuck as completed without scores (e.g. from a previous
            # run that ingested a placeholder [URL Scorecard] result),
            # reset so the UI doesn't show a phantom result for an
            # unplayed match.
            if (match.status == "completed"
                    and not match.score1 and not match.score2
                    and not match.winner):
                match.status = "scheduled"
                match.result = None
                count += 1
            continue

        # Don't trust transient Wikipedia results (e.g. "Innings break")
        # as completion signals — the match is still in progress
        wiki_result = fixture.get("result")
        transient = _is_transient_result(wiki_result) and not summary_result
        updated = False
        if match.status == "scheduled" and not transient:
            match.status = "completed"
            updated = True
        # Wikipedia is the post-match scoreboard — overwrite scores
        # and overs for completed fixtures so we replace any stale
        # mid-chase snapshot from live_crawl/RSS with the final figures.
        # Skip overwriting when the fixture is still transient (in
        # progress) so we don't blank a richer live state.
        if not transient:
            if fixture.get("score1"):
                if match.score1 != fixture["score1"]:
                    match.score1 = fixture["score1"]
                    updated = True
            if fixture.get("score2"):
                if match.score2 != fixture["score2"]:
                    match.score2 = fixture["score2"]
                    updated = True
            if fixture.get("overs1"):
                new_overs1 = f'{fixture["overs1"]} ov'
                if match.overs1 != new_overs1:
                    match.overs1 = new_overs1
                    updated = True
            if fixture.get("overs2"):
                new_overs2 = f'{fixture["overs2"]} ov'
                if match.overs2 != new_overs2:
                    match.overs2 = new_overs2
                    updated = True
        if not match.hero_name and fixture.get("motm"):
            match.hero_name = fixture["motm"]
            updated = True
        if not match.match_url and fixture.get("match_url"):
            match.match_url = fixture["match_url"]
            updated = True
        if not match.wiki_notes and fixture.get("notes"):
            match.wiki_notes = fixture["notes"]
            updated = True
        if not match.result:
            result_text = fixture.get("result") or summary_result
            if result_text and not _is_transient_result(result_text):
                match.result = result_text
                updated = True
        if not match.winner:
            winner = _winner_from_result(fixture) or summary_winner
            if winner:
                match.winner = winner
                updated = True
        if summary and summary.get("dls") and not match.wiki_notes:
            match.wiki_notes = "DLS method"
            updated = True

        # Per-innings highlights (always overwrite — Wikipedia is the
        # only source for these fields, and they don't exist elsewhere)
        if fixture.get("toss"):
            match.toss = fixture["toss"]
        if fixture.get("home_team"):
            match.home_team = fixture["home_team"]
        if fixture.get("top_batter1"):
            match.top_batter1 = fixture["top_batter1"]
        if fixture.get("top_bowler1"):
            match.top_bowler1 = fixture["top_bowler1"]
        if fixture.get("top_batter2"):
            match.top_batter2 = fixture["top_batter2"]
        if fixture.get("top_bowler2"):
            match.top_bowler2 = fixture["top_bowler2"]
        # Populate hero_stat from top batter/bowler when MOTM matches.
        # Cricsheet uses abbreviated names ("SN Thakur"), Wikipedia uses
        # full names ("Shardul Thakur") — match by surname (last token).
        if match.hero_name and not match.hero_stat:
            hero_surname = match.hero_name.split()[-1].lower()
            for tb in (fixture.get("top_batter1"), fixture.get("top_batter2")):
                if tb and tb.get("name"):
                    wiki_surname = tb["name"].split()[-1].lower()
                    if hero_surname == wiki_surname:
                        no = "*" if tb.get("not_out") else ""
                        match.hero_stat = f'{tb["runs"]}{no}({tb["balls"]})'
                        break
            else:
                for tw in (fixture.get("top_bowler1"), fixture.get("top_bowler2")):
                    if tw and tw.get("name"):
                        wiki_surname = tw["name"].split()[-1].lower()
                        if hero_surname == wiki_surname:
                            match.hero_stat = f'{tw["wickets"]}/{tw["runs"]}'
                            break

        if updated:
            count += 1

    if count:
        console.print(
            f"  [green]Schedule: {count} match(es) enriched from Wikipedia[/green]"
        )
    return matches


def sync_squads(season: str, conn, *, force: bool = False) -> int:
    """Fetch IPL squads from Wikipedia and seed ipl_season_squad table.

    Skips if data already exists for the season (squads don't change).
    Use force=True to re-fetch.

    Returns number of players inserted.
    """
    # Check if already seeded
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM ipl_season_squad WHERE season = ?",
            [season],
        ).fetchone()[0]
        if count > 0 and not force:
            return count
    except Exception:
        pass  # table doesn't exist yet

    wikitext = fetch_personnel_wikitext(int(season))
    if not wikitext:
        return 0

    squads = parse_ipl_squads(wikitext, int(season))
    if not squads:
        console.print("  [dim]Squads: no squad data found on Wikipedia[/dim]")
        return 0

    # Create table if needed
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ipl_season_squad (
            franchise_id VARCHAR NOT NULL,
            season VARCHAR NOT NULL,
            player_name VARCHAR NOT NULL,
            role VARCHAR,
            is_captain BOOLEAN DEFAULT FALSE,
            is_overseas BOOLEAN DEFAULT FALSE,
            acquisition_type VARCHAR,
            price_inr BIGINT,
            is_retained BOOLEAN DEFAULT FALSE,
            is_rtm BOOLEAN DEFAULT FALSE,
            PRIMARY KEY (franchise_id, season, player_name)
        )
    """)

    # Replace current season data
    conn.execute(
        "DELETE FROM ipl_season_squad WHERE season = ?",
        [season],
    )

    for p in squads:
        conn.execute(
            """INSERT INTO ipl_season_squad
               (franchise_id, season, player_name, role, is_captain,
                is_overseas, acquisition_type, price_inr, is_retained, is_rtm)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                p["franchise_id"], str(p["season"]), p["player_name"],
                p.get("role"), p.get("is_captain", False),
                p.get("is_overseas", False), p.get("acquisition_type"),
                p.get("price_inr"), p.get("is_retained", False),
                p.get("is_rtm", False),
            ],
        )

    console.print(
        f"  [green]Squads: {len(squads)} players across"
        f" {len({p['franchise_id'] for p in squads})} teams[/green]"
    )
    return len(squads)
