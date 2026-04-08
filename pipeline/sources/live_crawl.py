"""Live match crawler — enriches live matches via ESPNcricinfo page scraping.

Crawls the match URL for live IPL matches and extracts structured data from
the __NEXT_DATA__ JSON embedded by Next.js. This replaces fragile regex
parsing on markdown with direct JSON extraction — structured, typed, and
stable across ESPNcricinfo UI redesigns.

Data is stored in a JSON sidecar file (live-match.json) and also patched
back into schedule.json so the frontend can display overs/CRR/etc.

Usage:
    # One-shot: crawl any currently live matches
    uv run python -m pipeline.sources.live_crawl

    # Watch mode: poll every 90s while a match is live
    uv run python -m pipeline.sources.live_crawl --watch
"""

import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from pipeline.ipl.franchise_metadata import IPL_FRANCHISES

console = Console()

ROOT_DIR = Path(__file__).resolve().parents[2]
PUBLIC_API_DIR = ROOT_DIR / "frontend" / "public" / "api" / "ipl" / "war-room"
DATA_DIR = ROOT_DIR / "data" / "war-room"

# ── Parsed live match data ──────────────────────────────────────────


@dataclass
class LiveBatter:
    name: str
    runs: int
    balls: int
    fours: int = 0
    sixes: int = 0


@dataclass
class LiveBowler:
    name: str
    overs: str  # "2.4"
    runs: int
    wickets: int
    econ: float | None = None


@dataclass
class LiveMatchData:
    """Rich live match snapshot from crawled ESPNcricinfo page."""

    match_number: int
    team1: str
    team2: str
    status: str  # "live" | "completed"

    # Scores
    score1: str | None = None  # "186/4"
    score2: str | None = None
    overs1: str | None = None  # "18.2"
    overs2: str | None = None
    batting: str | None = None  # franchise ID of batting team

    # Live insights
    current_rr: float | None = None
    required_rr: float | None = None
    win_prob_team1: float | None = None
    win_prob_team2: float | None = None
    live_forecast: str | None = None  # deprecated — win prob is better
    status_text: str | None = None  # "Match delayed by rain"

    # Toss
    toss: str | None = None  # "KKR chose to bat"

    # Current batters & bowler on strike
    batters: list[LiveBatter] = field(default_factory=list)
    bowlers: list[LiveBowler] = field(default_factory=list)

    # Raw crawled markdown (for future use / LLM processing)
    raw_markdown: str | None = None

    crawled_at: str = ""  # ISO 8601


# ── __NEXT_DATA__ extraction ──────────────────────────────────────

# ESPN abbreviation (uppercase) → franchise_id
_ABBREV_TO_FID: dict[str, str] = {
    v["short_name"].upper(): k
    for k, v in IPL_FRANCHISES.items()
    if not v.get("defunct")
}

_NEXT_DATA_RE = re.compile(
    r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)


def _extract_next_data(html: str) -> dict | None:
    """Extract and parse the __NEXT_DATA__ JSON from ESPNcricinfo HTML.

    Returns a dict with 'match' and 'content' keys, or None on failure.
    Handles both live page (data.data.match) and scorecard page (data.match).
    """
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        raw = json.loads(m.group(1))
        data = raw["props"]["appPageProps"]["data"]
        # Live pages nest under data.data; scorecard pages don't
        inner = data.get("data", data)
        match = inner.get("match")
        content = inner.get("content")
        if not match:
            return None
        return {"match": match, "content": content or {}}
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def _resolve_fid(abbreviation: str) -> str:
    """Map ESPN team abbreviation to our franchise_id."""
    return _ABBREV_TO_FID.get(abbreviation.upper(), abbreviation.lower())


def _overs_to_float(val: float | int | str) -> float:
    """Convert cricket overs notation to actual overs as a float.

    ESPNcricinfo uses 19.3 to mean 19 overs + 3 balls = 19.5 actual overs.
    Also handles 2-digit ball encoding: 19.06 = 19 overs + 6 balls.
    """
    val = float(val)
    if val == 0:
        return 0.0
    completed = int(val)
    frac = round((val - completed) * 100)  # e.g. 19.06 → 6, 19.3 → 30
    # If fraction > 6, it's 2-digit encoding (e.g. .06 = 6 balls)
    # If fraction <= 6, it's 1-digit (e.g. .3 = 3 balls)
    if frac > 6:
        balls = frac
    else:
        balls = round((val - completed) * 10)
    return completed + balls / 6


def _parse_from_json(
    data: dict,
    match_number: int,
    team1: str,
    team2: str,
) -> LiveMatchData:
    """Parse __NEXT_DATA__ JSON into LiveMatchData."""
    match = data["match"]
    content = data.get("content", {})

    result = LiveMatchData(
        match_number=match_number,
        team1=team1,
        team2=team2,
        status="live",
        crawled_at=datetime.now(timezone.utc).isoformat(),
    )

    # ── Match status ───────────────────────────────────────────
    stage = match.get("stage", "")
    if stage != "RUNNING":
        result.status = "completed"

    result.status_text = match.get("statusText")

    # ── Build ESPN team ID → franchise_id mapping ──────────────
    espn_teams = match.get("teams", [])
    espn_id_to_fid: dict[int, str] = {}
    abbrev_to_espn_id: dict[str, int] = {}
    for t in espn_teams:
        team_obj = t.get("team", {})
        espn_id = team_obj.get("id")
        abbr = team_obj.get("abbreviation", "")
        fid = _resolve_fid(abbr)
        if espn_id:
            espn_id_to_fid[espn_id] = fid
            abbrev_to_espn_id[abbr.upper()] = espn_id

    # ── Scores from match.teams[] ──────────────────────────────
    for t in espn_teams:
        team_obj = t.get("team", {})
        fid = _resolve_fid(team_obj.get("abbreviation", ""))
        score = t.get("score")
        if score and fid == team1:
            result.score1 = score
        elif score and fid == team2:
            result.score2 = score

    # ── Innings data (overs, batting, batters/bowlers) ─────────
    innings = content.get("innings", [])
    current_inn = None
    for inn in innings:
        inn_team = inn.get("team", {})
        fid = _resolve_fid(inn_team.get("abbreviation", ""))
        overs = inn.get("overs")
        overs_str = str(overs) if overs is not None else None

        if fid == team1 and overs_str:
            result.overs1 = overs_str
        elif fid == team2 and overs_str:
            result.overs2 = overs_str

        if inn.get("isCurrent"):
            result.batting = fid
            current_inn = inn

    # ── Current run rate (calculated) ──────────────────────────
    if current_inn:
        live_overs_raw = match.get("liveOvers")
        inn_runs = current_inn.get("runs", 0)
        if live_overs_raw is not None:
            live_overs = _overs_to_float(live_overs_raw)
            if live_overs > 0:
                result.current_rr = round(inn_runs / live_overs, 2)

    # ── Required run rate (2nd innings only) ───────────────────
    if current_inn and current_inn.get("inningNumber", 0) == 2:
        # Find 1st innings runs for target
        for inn in innings:
            if inn.get("inningNumber") == 1:
                target = inn.get("runs", 0) + 1
                remaining_runs = target - current_inn.get("runs", 0)
                live_overs_raw = match.get("liveOvers")
                if live_overs_raw is not None:
                    current_ov = _overs_to_float(live_overs_raw)
                    total_overs = float(
                        current_inn.get("totalOvers", 20)
                    )
                    remaining_ov = total_overs - current_ov
                    if remaining_ov > 0 and remaining_runs > 0:
                        result.required_rr = round(
                            remaining_runs / remaining_ov, 2,
                        )
                break

    # ── Win probability ────────────────────────────────────────
    ball_comments = (
        content.get("recentBallCommentary", {})
        .get("ballComments", [])
    )
    if ball_comments and result.batting:
        latest = ball_comments[0]
        preds = latest.get("predictions", {})
        win_prob = preds.get("winProbability")
        if win_prob is not None and isinstance(win_prob, (int, float)):
            # winProbability is the batting team's probability
            if result.batting == team1:
                result.win_prob_team1 = round(float(win_prob), 1)
                result.win_prob_team2 = round(100 - float(win_prob), 1)
            else:
                result.win_prob_team2 = round(float(win_prob), 1)
                result.win_prob_team1 = round(100 - float(win_prob), 1)

    # ── Toss ───────────────────────────────────────────────────
    toss_winner_id = match.get("tossWinnerTeamId")
    toss_choice = match.get("tossWinnerChoice")
    if toss_winner_id and toss_choice:
        toss_fid = espn_id_to_fid.get(toss_winner_id)
        if toss_fid:
            choice_str = "bat" if toss_choice == 1 else "field"
            result.toss = f"{toss_fid.upper()} chose to {choice_str}"

    # ── Live batters & bowlers ─────────────────────────────────
    live_perf = content.get("livePerformance", {})
    for b in live_perf.get("batsmen", []):
        player = b.get("player", {})
        name = player.get("longName") or player.get("name", "")
        if name:
            result.batters.append(LiveBatter(
                name=name,
                runs=b.get("runs", 0),
                balls=b.get("balls", 0),
                fours=b.get("fours", 0),
                sixes=b.get("sixes", 0),
            ))

    for b in live_perf.get("bowlers", []):
        player = b.get("player", {})
        name = player.get("longName") or player.get("name", "")
        if name:
            result.bowlers.append(LiveBowler(
                name=name,
                overs=str(b.get("overs", 0)),
                runs=b.get("conceded", 0),
                wickets=b.get("wickets", 0),
                econ=b.get("economy"),
            ))

    return result


# ── Crawl orchestration ─────────────────────────────────────────────


async def crawl_live_match(
    match_url: str, match_number: int, team1: str, team2: str,
) -> LiveMatchData | None:
    """Crawl a single live match page and extract rich data."""
    try:
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(
                url=match_url,
                config=CrawlerRunConfig(),
            )
            r = result._results[0] if hasattr(result, "_results") else result
            html = r.html if hasattr(r, "html") else ""
            if not html:
                return None
            data = _extract_next_data(html)
            if not data:
                console.print(
                    "  [yellow]__NEXT_DATA__ extraction failed[/yellow]"
                )
                return None
            return _parse_from_json(data, match_number, team1, team2)
    except Exception as e:
        console.print(f"  [yellow]Live crawl error: {e}[/yellow]")
        return None


def crawl_live_matches_sync(schedule_path: Path | None = None) -> list[LiveMatchData]:
    """Find live matches in schedule.json, crawl them, return rich data."""
    path = schedule_path or PUBLIC_API_DIR / "schedule.json"
    if not path.exists():
        return []

    schedule = json.loads(path.read_text(encoding="utf-8"))
    live = [
        m for m in schedule
        if m.get("status") == "live" and m.get("match_url")
    ]

    if not live:
        return []

    console.print(f"\n[bold]Live Match Crawl[/bold] — {len(live)} live match(es)")

    results: list[LiveMatchData] = []
    for m in live:
        label = f"M{m['match_number']}: {m['team1'].upper()} vs {m['team2'].upper()}"
        console.print(f"  Crawling {label}...")
        data = asyncio.run(
            crawl_live_match(m["match_url"], m["match_number"], m["team1"], m["team2"])
        )
        if data:
            results.append(data)
            batters = ", ".join(
                f"{b.name} {b.runs}({b.balls})" for b in data.batters
            ) or "—"
            console.print(
                f"    {data.score1 or '?'} vs {data.score2 or '?'}"
                f"  CRR: {data.current_rr or '?'}"
                f"  Batters: {batters}"
            )

    return results


def patch_schedule_with_live(results: list[LiveMatchData]) -> int:
    """Patch schedule.json with enriched live match data. Returns count patched."""
    path = PUBLIC_API_DIR / "schedule.json"
    if not path.exists() or not results:
        return 0

    schedule = json.loads(path.read_text(encoding="utf-8"))
    patched = 0

    for data in results:
        for m in schedule:
            if m["match_number"] == data.match_number:
                if data.score1:
                    m["score1"] = data.score1
                if data.score2:
                    m["score2"] = data.score2
                if data.overs1:
                    m["overs1"] = f"{data.overs1} ov"
                if data.overs2:
                    m["overs2"] = f"{data.overs2} ov"
                if data.batting:
                    m["batting"] = data.batting
                # Always sync innings-specific fields — clears stale
                # data when value is absent (e.g. 1st-innings forecast
                # after 2nd innings starts).
                m["current_rr"] = data.current_rr
                m["required_rr"] = data.required_rr
                m["live_forecast"] = data.live_forecast
                m["status_text"] = data.status_text
                m["win_prob_team1"] = data.win_prob_team1
                m["win_prob_team2"] = data.win_prob_team2
                if data.toss and not m.get("toss"):
                    m["toss"] = data.toss
                if data.status == "completed":
                    m["status"] = "completed"
                patched += 1
                break

    if patched:
        # Write to both output dirs
        for p in [path, DATA_DIR / "schedule.json"]:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(schedule, f, ensure_ascii=False, indent=2)
                f.write("\n")

    return patched


def write_live_snapshot(results: list[LiveMatchData]) -> None:
    """Write rich live match data to live-match.json for frontend/future use."""
    if not results:
        return

    # Strip raw_markdown for the JSON output (too large)
    data = []
    for r in results:
        d = asdict(r)
        d.pop("raw_markdown", None)
        # Convert dataclass lists
        d["batters"] = [asdict(b) for b in r.batters] if r.batters else []
        d["bowlers"] = [asdict(b) for b in r.bowlers] if r.bowlers else []
        data.append(d)

    for p in [PUBLIC_API_DIR / "live-match.json", DATA_DIR / "live-match.json"]:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")


def write_live_archive(results: list[LiveMatchData]) -> None:
    """Append raw crawl snapshots to an archive file for later analysis."""
    if not results:
        return

    archive_path = DATA_DIR / "live-crawl-archive.jsonl"
    with open(archive_path, "a", encoding="utf-8") as f:
        for r in results:
            entry = {
                "match_number": r.match_number,
                "team1": r.team1,
                "team2": r.team2,
                "score1": r.score1,
                "score2": r.score2,
                "overs1": r.overs1,
                "overs2": r.overs2,
                "current_rr": r.current_rr,
                "required_rr": r.required_rr,
                "win_prob_team1": r.win_prob_team1,
                "win_prob_team2": r.win_prob_team2,
                "live_forecast": r.live_forecast,
                "status_text": r.status_text,
                "toss": r.toss,
                "batting": r.batting,
                "status": r.status,
                "crawled_at": r.crawled_at,
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── CLI entry point ─────────────────────────────────────────────────


def run_once() -> None:
    """Single crawl pass: find live matches, crawl, patch, archive."""
    results = crawl_live_matches_sync()
    if results:
        patched = patch_schedule_with_live(results)
        write_live_snapshot(results)
        write_live_archive(results)
        console.print(f"  Patched {patched} match(es) in schedule.json")
        console.print(f"  Archived {len(results)} snapshot(s)")
    else:
        console.print("  No live matches to crawl")


def run_watch(interval: int = 90) -> None:
    """Poll for live matches every `interval` seconds until none remain."""
    console.print(f"[bold]Live crawl watch mode[/bold] — polling every {interval}s")
    consecutive_empty = 0

    while True:
        try:
            results = crawl_live_matches_sync()
            if results:
                consecutive_empty = 0
                patched = patch_schedule_with_live(results)
                write_live_snapshot(results)
                write_live_archive(results)
                console.print(
                    f"  [green]Updated {patched} match(es)[/green] — "
                    f"next poll in {interval}s"
                )
            else:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    console.print(
                        "  [dim]No live matches for 3 consecutive checks."
                        " Stopping watch.[/dim]"
                    )
                    break
                console.print(f"  [dim]No live matches — retrying in {interval}s[/dim]")

            time.sleep(interval)
        except KeyboardInterrupt:
            console.print("\n[bold]Stopped.[/bold]")
            break


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Live match crawler")
    parser.add_argument("--watch", action="store_true", help="Poll every 90s")
    parser.add_argument(
        "--interval", type=int, default=90, help="Poll interval in seconds (default: 90)"
    )
    args = parser.parse_args()

    if args.watch:
        run_watch(interval=args.interval)
    else:
        run_once()
