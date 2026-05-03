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
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from pipeline.config import LIVE_SOURCE, LIVESCORES_RSS_URL
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


def _parse_from_json(
    data: dict,
    match_number: int,
    team1: str,
    team2: str,
) -> LiveMatchData:
    """Parse __NEXT_DATA__ JSON into LiveMatchData.

    All numeric live fields come from internally-consistent ESPN subsystems:
      - content.innings[isCurrent]      — runs/wickets/overs/target
      - content.supportInfo.liveInfo    — pre-computed CRR/RRR
      - match.liveInningPredictions     — current win probability
      - match.statusText                — "X need Y runs in Z balls"

    Match-level live* fields (liveOvers, liveBalls) are deliberately ignored
    — they lag the per-innings data and caused stale CRR/RRR in production.
    """
    match = data["match"]
    content = data.get("content", {})

    result = LiveMatchData(
        match_number=match_number,
        team1=team1,
        team2=team2,
        status="live",
        crawled_at=datetime.now(timezone.utc).isoformat(),
    )

    # ── Match status + status text (ESPN-authored) ─────────────
    # ESPN leaves `stage="RUNNING"` even after a match ends; the fields
    # that actually flip are `state` ("LIVE" → "POST") and `status`
    # ("Live" → "RESULT"). Trust those.
    state = (match.get("state") or "").upper()
    status_val = (match.get("status") or "").upper()
    if state == "POST" or status_val == "RESULT":
        result.status = "completed"
    result.status_text = match.get("statusText")

    # ── ESPN team id → franchise id mapping (used for toss) ────
    espn_id_to_fid: dict[int, str] = {}
    for t in match.get("teams", []):
        team_obj = t.get("team", {})
        espn_id = team_obj.get("id")
        if espn_id:
            espn_id_to_fid[espn_id] = _resolve_fid(team_obj.get("abbreviation", ""))

    # ── Innings: source of truth for scores, overs, batting ────
    innings = content.get("innings", [])
    current_inn = None
    for inn in innings:
        fid = _resolve_fid(inn.get("team", {}).get("abbreviation", ""))
        runs = inn.get("runs")
        wickets = inn.get("wickets")
        overs = inn.get("overs")
        score = f"{runs}/{wickets}" if runs is not None and wickets is not None else None
        overs_str = str(overs) if overs is not None else None

        if fid == team1:
            if score:
                result.score1 = score
            if overs_str:
                result.overs1 = overs_str
        elif fid == team2:
            if score:
                result.score2 = score
            if overs_str:
                result.overs2 = overs_str

        if inn.get("isCurrent"):
            result.batting = fid
            current_inn = inn

    # ── Pre-computed CRR/RRR from supportInfo.liveInfo ─────────
    # ESPN ships these directly. Note the typo: "requiredRunrate"
    # (lowercase 'rate'), not "requiredRunRate".
    live_info = content.get("supportInfo", {}).get("liveInfo", {})
    crr = live_info.get("currentRunRate")
    if isinstance(crr, (int, float)):
        result.current_rr = round(float(crr), 2)
    rrr = live_info.get("requiredRunrate")
    if isinstance(rrr, (int, float)):
        result.required_rr = round(float(rrr), 2)

    # ── Win probability from match.liveInningPredictions ───────
    # winProbability is the *batting* team's probability for the
    # innings identified by inningNumber.
    preds = match.get("liveInningPredictions") or {}
    win_prob = preds.get("winProbability")
    pred_inning = preds.get("inningNumber")
    if isinstance(win_prob, (int, float)) and current_inn:
        if pred_inning == current_inn.get("inningNumber") and result.batting:
            wp = round(float(win_prob), 1)
            other = round(100 - wp, 1)
            if result.batting == team1:
                result.win_prob_team1, result.win_prob_team2 = wp, other
            else:
                result.win_prob_team2, result.win_prob_team1 = wp, other

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


# ── RSS fallback ────────────────────────────────────────────────────

_RSS_MATCH_ID_RE = re.compile(r"/match/(\d+)\.html")
_RSS_ITEM_RE = re.compile(
    r"<item>\s*<title>(?P<title>.*?)</title>.*?<link>(?P<link>.*?)</link>",
    re.DOTALL,
)


def _fetch_livescores_rss() -> str | None:
    """Fetch the cricinfo livescores RSS feed. Returns raw XML or None."""
    try:
        req = urllib.request.Request(
            LIVESCORES_RSS_URL,
            headers={"User-Agent": "duckworth-dugout/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        console.print(f"  [yellow]Livescores RSS fetch error: {e}[/yellow]")
        return None


def _parse_rss_title(
    title: str, team1: str, team2: str,
) -> tuple[str | None, str | None, str | None]:
    """Parse an RSS livescores title into (score1, score2, batting_fid).

    Title format: "<Team1 Name> <score> [*] v <Team2 Name> <score> [*]"
    Asterisk marks the batting team. Team order in title may not match the
    schedule's team1/team2 order, so we look up by franchise long name.

    Returns (None, None, None) if the title can't be cleanly parsed.
    """
    if " v " not in title:
        return None, None, None
    left, right = title.split(" v ", 1)
    name1 = IPL_FRANCHISES.get(team1, {}).get("name", "")
    name2 = IPL_FRANCHISES.get(team2, {}).get("name", "")

    def extract(side: str) -> tuple[str | None, bool]:
        m = re.search(r"(\d+/\d+)\s*(\*?)", side)
        if not m:
            return None, False
        return m.group(1), bool(m.group(2))

    if name1 and name1 in left and name2 and name2 in right:
        s1, bat1 = extract(left)
        s2, bat2 = extract(right)
    elif name2 and name2 in left and name1 and name1 in right:
        s2, bat2 = extract(left)
        s1, bat1 = extract(right)
    else:
        return None, None, None

    batting = team1 if bat1 else team2 if bat2 else None
    return s1, s2, batting


def parse_rss_for_match(
    match_id: str, match_number: int, team1: str, team2: str,
) -> LiveMatchData | None:
    """Parse the livescores RSS feed for a specific match.

    Returns a LiveMatchData with only score1/score2/batting populated;
    every other field stays None so the frontend hides those widgets.
    """
    xml = _fetch_livescores_rss()
    if not xml:
        return None
    for m in _RSS_ITEM_RE.finditer(xml):
        link = m.group("link").strip()
        id_match = _RSS_MATCH_ID_RE.search(link)
        if not id_match or id_match.group(1) != match_id:
            continue
        title = re.sub(r"&amp;", "&", m.group("title")).strip()
        score1, score2, batting = _parse_rss_title(title, team1, team2)
        if not score1 and not score2:
            return None
        return LiveMatchData(
            match_number=match_number,
            team1=team1,
            team2=team2,
            status="live",
            score1=score1,
            score2=score2,
            batting=batting,
            crawled_at=datetime.now(timezone.utc).isoformat(),
        )
    return None


def _match_id_from_url(url: str) -> str | None:
    m = _RSS_MATCH_ID_RE.search(url or "")
    return m.group(1) if m else None


_WINNER_RE = re.compile(r"^\s*(.+?)\s+won\s+(?:by|the)\s+", re.IGNORECASE)


def _extract_winner_fid(
    status_text: str | None, team1: str, team2: str,
) -> str | None:
    """Parse ESPN's statusText to identify the winning franchise.

    Handles "PBKS won by 6 wickets (with 7 balls remaining)",
    "Punjab Kings won by 6 wickets", "PBKS won the Super Over".
    Returns None for tied / no result / abandoned / unparseable.
    """
    if not status_text:
        return None
    m = _WINNER_RE.match(status_text)
    if not m:
        return None
    name = m.group(1).strip()
    upper = name.upper()
    for fid in (team1, team2):
        franchise = IPL_FRANCHISES.get(fid, {})
        if upper == (franchise.get("short_name") or "").upper():
            return fid
        if name.lower() == (franchise.get("name") or "").lower():
            return fid
    return None


# ── Orchestration ────────────────────────────────────────────────────


def crawl_live_matches_sync(
    schedule_path: Path | None = None,
    live_matches: list[dict] | None = None,
) -> list[LiveMatchData]:
    """Fetch live matches via the configured source (LIVE_SOURCE).

    `live_matches` (preferred) is a pre-filtered list of dicts with
    match_number / team1 / team2 / match_url. Pass this when the caller
    has the in-memory state — reading schedule.json from disk would
    miss promotions made in the same sync (the caller writes the panel
    after this returns).

    Falls back to reading schedule_path / PUBLIC_API_DIR/schedule.json
    when live_matches is not supplied (run-once CLI path).
    """
    if live_matches is None:
        path = schedule_path or PUBLIC_API_DIR / "schedule.json"
        if not path.exists():
            return []
        schedule = json.loads(path.read_text(encoding="utf-8"))
        live = [
            m for m in schedule
            if m.get("status") == "live" and m.get("match_url")
        ]
    else:
        live = live_matches

    if not live:
        return []

    mode = LIVE_SOURCE if LIVE_SOURCE in ("auto", "crawl", "rss") else "auto"
    console.print(
        f"\n[bold]Live Match Fetch[/bold] — {len(live)} live match(es) "
        f"[dim](source={mode})[/dim]"
    )

    results: list[LiveMatchData] = []
    for m in live:
        label = f"M{m['match_number']}: {m['team1'].upper()} vs {m['team2'].upper()}"
        match_id = _match_id_from_url(m["match_url"])
        data: LiveMatchData | None = None

        if mode in ("auto", "crawl"):
            console.print(f"  Crawling {label}...")
            data = asyncio.run(
                crawl_live_match(
                    m["match_url"], m["match_number"], m["team1"], m["team2"],
                )
            )

        if data is None and mode in ("auto", "rss") and match_id:
            console.print(f"  RSS fallback for {label}...")
            data = parse_rss_for_match(
                match_id, m["match_number"], m["team1"], m["team2"],
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
                    # Backfill winner/result from ESPN's statusText so
                    # _patch_standings_with_schedule can fire without
                    # waiting for Cricsheet (lags 1–2 days in-season).
                    # Don't clobber values a prior authoritative overlay
                    # (Cricsheet / Wikipedia) already filled in.
                    if not m.get("winner"):
                        fid = _extract_winner_fid(
                            data.status_text, m["team1"], m["team2"],
                        )
                        if fid:
                            m["winner"] = fid
                    if not m.get("result") and data.status_text:
                        m["result"] = data.status_text
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
