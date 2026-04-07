"""Schedule panel — static fixtures + completed results + live score overlay.

Data sources:
- Static fixtures JSON (pre-season, all 70 league matches)
- Cricsheet match results (completed matches, via cricsheet.py)
- ESPNcricinfo live scores RSS (live overlay)
"""

import json
import re

from rich.console import Console

from pipeline.config import DATA_DIR, ROOT_DIR
from pipeline.ipl.franchise_metadata import IPL_FRANCHISES
from pipeline.models import ScheduleMatch
from pipeline.sources.feeds import FEEDS
from pipeline.sources.rss import RSSFetcher

console = Console()

FIXTURES_DIR = DATA_DIR / "fixtures"

# Team name → franchise ID (lowercased, includes historical names)
_TEAM_LOOKUP: dict[str, str] = {}
for _fid, _fdata in IPL_FRANCHISES.items():
    if _fdata.get("defunct"):
        continue
    for _name in _fdata["cricsheet_names"]:
        _TEAM_LOOKUP[_name.lower()] = _fid
    _TEAM_LOOKUP[_fdata["short_name"].lower()] = _fid

_SCORE_RE = re.compile(r"(\d{1,3}(?:/\d{1,2})?)")
_OVERS_RE = re.compile(r"\((\d[\d./]*)\s*ov(?:ers?)?\)")
_VS_RE = re.compile(r"^(.+?)\s+v\s+(.+?)$", re.IGNORECASE)


def _resolve_team(name: str) -> str | None:
    key = name.strip().lower()
    if key in _TEAM_LOOKUP:
        return _TEAM_LOOKUP[key]
    for known, fid in _TEAM_LOOKUP.items():
        if len(known) > 3 and known in key:
            return fid
    return None


def _parse_live_segment(segment: str) -> tuple[str | None, str | None, str | None, bool]:
    """Parse a live score segment like 'MI 186/4* (18.2 ov)'.

    Returns (team_fid, score, overs, is_batting).
    """
    segment = segment.strip()
    is_batting = "*" in segment
    segment = segment.replace("*", "").strip()
    # Extract overs before stripping
    overs_match = _OVERS_RE.search(segment)
    overs = f"{overs_match.group(1)} ov" if overs_match else None
    segment = _OVERS_RE.sub("", segment).strip()
    scores = _SCORE_RE.findall(segment)
    score = scores[-1] if scores else None
    # Normalize bare runs (e.g. "15") to "15/0" for batting team
    if score and "/" not in score and is_batting:
        score = f"{score}/0"
    # Reject impossible scores (wickets > 10 or runs > 500)
    if score and "/" in score:
        try:
            r, w = score.split("/")
            if int(w) > 10 or int(r) > 500:
                score = None
        except ValueError:
            score = None
    first_match = _SCORE_RE.search(segment)
    team_str = segment[:first_match.start()].strip() if first_match else segment
    return _resolve_team(team_str), score, overs, is_batting


def _short(fid: str) -> str:
    return IPL_FRANCHISES.get(fid, {}).get("short_name", fid.upper())


def _build_venue_city_map() -> dict[str, str]:
    """Query Cricsheet venues table for venue_name → city mapping."""
    import duckdb

    from pipeline.config import CRICKET_DB_PATH

    try:
        conn = duckdb.connect(str(CRICKET_DB_PATH), read_only=True)
        rows = conn.execute(
            "SELECT DISTINCT name, city FROM venues WHERE city IS NOT NULL"
        ).fetchall()
        conn.close()
    except Exception:
        return {}

    mapping: dict[str, str] = {}
    for name, city in rows:
        mapping[name.lower()] = city
    return mapping


def _resolve_venue_city(venue: str, venue_city_map: dict[str, str]) -> str:
    """Resolve a venue name to its city via Cricsheet lookup.

    Uses substring matching since fixture venue names may not exactly
    match Cricsheet venue names.
    """
    key = venue.lower()
    # Exact match
    if key in venue_city_map:
        return venue_city_map[key]
    # Substring: find the longest matching venue name
    best = ""
    best_city = ""
    for vname, city in venue_city_map.items():
        if vname in key or key in vname:
            if len(vname) > len(best):
                best = vname
                best_city = city
    return best_city or venue


def load_fixtures(season: str) -> list[ScheduleMatch]:
    path = FIXTURES_DIR / f"fixtures-{season}.json"
    if not path.exists():
        console.print(f"  [yellow]Schedule: fixtures file not found: {path}[/yellow]")
        return []

    venue_city_map = _build_venue_city_map()
    data = json.loads(path.read_text(encoding="utf-8"))
    return [ScheduleMatch(
        match_number=m["match_number"], date=m["date"], time=m["time"],
        venue=m["venue"],
        city=_resolve_venue_city(m["venue"], venue_city_map),
        team1=m["team1"], team2=m["team2"],
    ) for m in data]


def overlay_completed(matches: list[ScheduleMatch], season: str) -> list[ScheduleMatch]:
    """Mark completed matches using Cricsheet data directly."""
    from pipeline.sources.cricsheet import query_completed_matches

    completed = query_completed_matches(season)
    if not completed:
        return matches

    count = 0
    for match in matches:
        if match.status != "scheduled":
            continue
        key = (match.date, *sorted([match.team1, match.team2]))
        if key not in completed:
            continue

        cm = completed[key]
        match.status = "completed"
        match.score1 = cm["score_f1"] if cm["f1"] == match.team1 else cm["score_f2"]
        match.score2 = cm["score_f2"] if cm["f2"] == match.team2 else cm["score_f1"]
        match.winner = cm["winner"]
        match.result = cm["result_text"]
        match.hero_name = cm["potm"]
        count += 1

    if count:
        console.print(f"  [green]Schedule: {count} completed match(es) from Cricsheet[/green]")
    return matches


def overlay_live_scores(matches: list[ScheduleMatch]) -> list[ScheduleMatch]:
    """Overlay live scores from ESPNcricinfo RSS."""
    items = RSSFetcher(FEEDS["livescores"]["url"]).fetch()

    live_count = 0
    for item in items:
        title_parts = (item.title or "").split("-", 1)
        vs_match = _VS_RE.match(title_parts[0].strip())
        if not vs_match:
            continue
        t1, s1, ov1, b1 = _parse_live_segment(vs_match.group(1))
        t2, s2, ov2, b2 = _parse_live_segment(vs_match.group(2))
        if not t1 or not t2:
            continue

        # Status text from after the dash: "MI need 14 from 10 balls"
        status_text = title_parts[1].strip() if len(title_parts) > 1 else None

        # Detect if the match is actually completed:
        # - Neither team is batting (no * indicator), OR
        # - The chasing team is all out (/10), OR
        # - The chasing team has surpassed the target (successful chase)
        both_batted = bool(s1 and s2)
        nobody_batting = not b1 and not b2
        chaser_all_out = (
            (b1 and s1 and "/10" in s1 and bool(s2))  # t1 chasing, all out
            or (b2 and s2 and "/10" in s2 and bool(s1))  # t2 chasing, all out
        )

        # Chaser surpassed target — successful chase
        def _runs(score: str | None) -> int:
            if not score or "/" not in score:
                return 0
            try:
                return int(score.split("/")[0])
            except ValueError:
                return 0

        chaser_surpassed = (
            (b1 and both_batted and _runs(s1) > _runs(s2))  # t1 chasing, beat t2's score
            or (b2 and both_batted and _runs(s2) > _runs(s1))  # t2 chasing, beat t1's score
        )
        is_completed = both_batted and (nobody_batting or chaser_all_out or chaser_surpassed)

        # Determine winner for successful chase
        chase_winner: str | None = None
        if chaser_surpassed:
            chase_winner = t1 if (b1 and _runs(s1) > _runs(s2)) else t2

        for match in matches:
            if {t1, t2} == {match.team1, match.team2}:
                # Don't downgrade a match already marked completed
                # (e.g. by standings overlay for no-result / washout)
                if match.status != "completed":
                    match.status = "completed" if is_completed else "live"
                # Only update scores when data is available (pre-toss/rain
                # delay entries have no scores — don't blank existing data)
                if s1 or s2:
                    match.score1 = s1 if t1 == match.team1 else s2
                    match.score2 = s2 if t2 == match.team2 else s1
                    match.overs1 = ov1 if t1 == match.team1 else ov2
                    match.overs2 = ov2 if t2 == match.team2 else ov1
                    match.batting = t1 if b1 else t2 if b2 else None
                match.status_text = status_text
                match.match_url = item.link
                if is_completed and chase_winner and not match.winner:
                    match.winner = chase_winner
                    wkts = 10 - int((s1 if chase_winner == t1 else s2 or "0/0").split("/")[1])
                    match.result = f"by {wkts} wickets"
                if match.status == "live":
                    live_count += 1
                break

    if live_count:
        console.print(f"  [green]Schedule: {live_count} live match(es)[/green]")
    else:
        console.print("  [dim]Schedule: no live IPL matches[/dim]")
    return matches


def overlay_from_standings(
    matches: list[ScheduleMatch],
    standings: list[dict],
) -> list[ScheduleMatch]:
    """Mark matches as completed using standings data.

    For scheduled matches where standings shows both teams as having
    played (but Cricsheet hasn't caught up), infer the result from
    W/L counts. This downstream patch ensures schedule stays current
    even when Cricsheet lags by a day or two.

    Standings is the source of truth for W/L; scores fill in later
    when Cricsheet data arrives.
    """
    if not standings:
        return matches

    # Build lookup: fid → {played, wins, losses, ...}
    std_by_fid: dict[str, dict] = {
        r["franchise_id"]: r for r in standings
    }

    # Count how many completed matches each team already has
    completed_per_team: dict[str, int] = {}
    for m in matches:
        if m.status == "completed":
            completed_per_team[m.team1] = (
                completed_per_team.get(m.team1, 0) + 1
            )
            completed_per_team[m.team2] = (
                completed_per_team.get(m.team2, 0) + 1
            )

    # Count completed wins and losses per team
    wins_per_team: dict[str, int] = {}
    losses_per_team: dict[str, int] = {}
    for m in matches:
        if m.status != "completed":
            continue
        if m.winner:
            wins_per_team[m.winner] = (
                wins_per_team.get(m.winner, 0) + 1
            )
            loser = m.team2 if m.winner == m.team1 else m.team1
            losses_per_team[loser] = (
                losses_per_team.get(loser, 0) + 1
            )

    count = 0
    for match in matches:
        if match.status != "scheduled":
            continue

        s1 = std_by_fid.get(match.team1)
        s2 = std_by_fid.get(match.team2)
        if not s1 or not s2:
            continue

        # Both teams must have more played matches in standings
        # than currently completed in schedule
        sch_played1 = completed_per_team.get(match.team1, 0)
        sch_played2 = completed_per_team.get(match.team2, 0)
        if s1["played"] <= sch_played1 or s2["played"] <= sch_played2:
            continue

        # Determine winner using both wins AND losses for
        # robustness across multi-match gaps
        new_w1 = s1["wins"] - wins_per_team.get(match.team1, 0)
        new_w2 = s2["wins"] - wins_per_team.get(match.team2, 0)
        new_l1 = s1["losses"] - losses_per_team.get(match.team1, 0)
        new_l2 = s2["losses"] - losses_per_team.get(match.team2, 0)

        match.status = "completed"
        if new_w1 > 0 and new_l1 == 0:
            match.winner = match.team1
            match.result = f"{_short(match.team1)} won"
        elif new_w2 > 0 and new_l2 == 0:
            match.winner = match.team2
            match.result = f"{_short(match.team2)} won"
        elif new_l1 > 0 and new_w1 == 0:
            match.winner = match.team2
            match.result = f"{_short(match.team2)} won"
        elif new_l2 > 0 and new_w2 == 0:
            match.winner = match.team1
            match.result = f"{_short(match.team1)} won"
        else:
            match.result = "No result"

        # Update counters so multi-match gaps resolve correctly
        completed_per_team[match.team1] = sch_played1 + 1
        completed_per_team[match.team2] = sch_played2 + 1
        if match.winner:
            wins_per_team[match.winner] = (
                wins_per_team.get(match.winner, 0) + 1
            )
            loser = (
                match.team2 if match.winner == match.team1
                else match.team1
            )
            losses_per_team[loser] = (
                losses_per_team.get(loser, 0) + 1
            )
        count += 1

    if count:
        console.print(
            f"  [green]Schedule: {count} match(es)"
            " patched from standings[/green]"
        )
    return matches


def _carry_forward_urls(matches: list[ScheduleMatch]) -> None:
    """Preserve match_url from previous schedule.json.

    ESPNcricinfo match URLs are permanent but only captured during
    live RSS overlay. Once a match drops off the feed, the URL would
    be lost. This carries forward URLs from the last saved schedule.
    """
    prev_path = ROOT_DIR / "frontend" / "public" / "api" / "ipl" / "war-room" / "schedule.json"
    if not prev_path.exists():
        return
    prev = json.loads(prev_path.read_text(encoding="utf-8"))
    url_by_num = {
        m["match_number"]: m["match_url"]
        for m in prev if m.get("match_url")
    }
    for match in matches:
        if not match.match_url and match.match_number in url_by_num:
            match.match_url = url_by_num[match.match_number]


def sync_schedule(
    season: str,
    standings: list[dict] | None = None,
) -> list[ScheduleMatch]:
    """Sync schedule: fixtures → Cricsheet → Wikipedia → standings → live RSS."""
    matches = load_fixtures(season)
    if matches:
        matches = overlay_completed(matches, season)
        from pipeline.sources.wikipedia import overlay_wikipedia_fixtures

        matches = overlay_wikipedia_fixtures(matches, season)
        if standings:
            matches = overlay_from_standings(matches, standings)
        matches = overlay_live_scores(matches)
        _carry_forward_urls(matches)
        console.print(
            f"  [green]Schedule: {len(matches)} fixtures loaded[/green]"
        )
    return matches
