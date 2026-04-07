"""Live match crawler — enriches live matches via ESPNcricinfo page scraping.

Crawls the match URL for live IPL matches to extract rich data that RSS
doesn't provide: overs, current run rate, win probability, live forecast,
toss result, batting/bowling figures, and ball-by-ball status.

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
    live_forecast: str | None = None  # "KKR 189"
    status_text: str | None = None  # "Match delayed by rain"

    # Toss
    toss: str | None = None  # "KKR chose to bat"

    # Current batters & bowler on strike
    batters: list[LiveBatter] = field(default_factory=list)
    bowlers: list[LiveBowler] = field(default_factory=list)

    # Raw crawled markdown (for future use / LLM processing)
    raw_markdown: str | None = None

    crawled_at: str = ""  # ISO 8601


# ── Parsing helpers ─────────────────────────────────────────────────

# Match header score line: "(3.4/20 ov) 25/2" or "186/4"
_HEADER_SCORE_RE = re.compile(
    r"(?:\((\d+\.?\d*)/\d+\s*[Oo]v\)\s*)?(\d{1,3}/\d{1,2})"
)


def _is_valid_cricket_score(score: str) -> bool:
    """Reject impossible scores like 900/41."""
    if "/" not in score:
        return False
    try:
        runs, wkts = score.split("/")
        return int(wkts) <= 10 and int(runs) <= 500
    except ValueError:
        return False
_CRR_RE = re.compile(r"Current RR:\s*([\d.]+)")
_RRR_RE = re.compile(r"Required RR:\s*([\d.]+)")
_FORECAST_RE = re.compile(r"Live Forecast:\s*(\S.+)")
_CURRENT_OVER_RE = re.compile(r"Current Over\s+(\d+)")


def _extract_match_zone(markdown: str, team1: str, team2: str) -> str:
    """Extract just the match-specific content, excluding sidebar scores."""
    lines = markdown.split("\n")
    # Find the match title line: "# RR vs MI, 13th Match..."
    # Must be a heading (starts with #) to avoid matching sidebar links
    t1u, t2u = team1.upper(), team2.upper()
    start = 0
    for i, line in enumerate(lines):
        if line.startswith("#") and t1u in line.upper() and t2u in line.upper():
            start = i
            break

    # End at footer/terms section
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if "Terms of Use" in lines[i] or "© 20" in lines[i]:
            end = i
            break

    return "\n".join(lines[start:end])


def _find_score_block(zone_lines: list[str], team_id: str) -> tuple[str | None, str | None]:
    """Find score and overs for a team in the match header.

    ESPNcricinfo format in crawled markdown (first ~15 lines of zone):
        ![KKR Flag](...)[KKR](...)
        (3.4/20 ov) 25/2
        ![PBKS Flag](...)[PBKS](...)
        KKR chose to bat.
    Only searches the header area to avoid picking up scores from
    Scoring Breakdown / other sections further down.
    """
    team_upper = team_id.upper()
    # Only look in the first 15 lines (match header area)
    header = zone_lines[:15]
    for i, line in enumerate(header):
        if team_upper in line.upper() and ("Flag" in line or f"[{team_upper}]" in line):
            # Check the next line only for a score pattern
            if i + 1 < len(header):
                m = _HEADER_SCORE_RE.search(header[i + 1])
                if m:
                    overs = m.group(1)
                    score = m.group(2)
                    if _is_valid_cricket_score(score):
                        return score, overs
            # No score on the next line = team hasn't batted yet
            return None, None
    return None, None


def parse_live_match(
    markdown: str,
    match_number: int,
    team1: str,
    team2: str,
) -> LiveMatchData:
    """Parse crawled ESPNcricinfo match page markdown into structured data."""
    data = LiveMatchData(
        match_number=match_number,
        team1=team1,
        team2=team2,
        status="live",
        crawled_at=datetime.now(timezone.utc).isoformat(),
        raw_markdown=markdown,
    )

    # Extract match-specific zone (exclude sidebar with other matches)
    zone = _extract_match_zone(markdown, team1, team2)
    zone_lines = zone.split("\n")

    # Extract scores and overs for each team
    score1, overs1 = _find_score_block(zone_lines, team1)
    score2, overs2 = _find_score_block(zone_lines, team2)
    if score1:
        data.score1 = score1
    if score2:
        data.score2 = score2
    if overs1:
        data.overs1 = overs1
    if overs2:
        data.overs2 = overs2

    # Batting team: look for "chose to bat/field" or score with overs (active innings)
    for line in zone_lines:
        lower = line.lower()
        if "chose to bat" in lower:
            # The team that chose to bat is batting first
            t1u, t2u = team1.upper(), team2.upper()
            if t1u in line.upper():
                data.batting = team1
            elif t2u in line.upper():
                data.batting = team2
            break
        if "chose to field" in lower:
            t1u, t2u = team1.upper(), team2.upper()
            if t1u in line.upper():
                data.batting = team2  # Other team bats
            elif t2u in line.upper():
                data.batting = team1
            break

    # If second innings, batting team is the one without completed overs
    if data.score2 and data.overs2 and not data.batting:
        data.batting = team2
    elif data.score1 and data.overs1 and not data.score2:
        data.batting = team1

    # Current run rate
    crr_match = _CRR_RE.search(zone)
    if crr_match:
        data.current_rr = float(crr_match.group(1))

    # Required run rate
    rrr_match = _RRR_RE.search(zone)
    if rrr_match:
        data.required_rr = float(rrr_match.group(1))

    # Live forecast
    forecast_match = _FORECAST_RE.search(zone)
    if forecast_match:
        data.live_forecast = forecast_match.group(1).strip()

    # Win probability — look for "TEAM XX.XX%" pattern near "Win Prob"
    prob_idx = zone.find("Win Prob")
    if prob_idx >= 0:
        prob_section = zone[prob_idx:prob_idx + 300]
        t1u, t2u = team1.upper(), team2.upper()
        for m in re.finditer(r"(\w+)\s+([\d.]+)%", prob_section):
            tn, pct = m.group(1).upper(), float(m.group(2))
            if pct > 1:
                if tn == t1u or t1u.startswith(tn):
                    data.win_prob_team1 = pct
                elif tn == t2u or t2u.startswith(tn):
                    data.win_prob_team2 = pct

    # Toss — only from match zone, look for "chose to bat/field"
    for line in zone_lines:
        lower = line.lower()
        if "chose to" in lower or "elected to" in lower:
            clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line.strip())
            # Only keep if it mentions our teams
            if team1.upper() in clean.upper() or team2.upper() in clean.upper():
                # Trim trailing noise like ".Stats view"
                clean = re.sub(r"\.\s*Stats.*$", "", clean, flags=re.IGNORECASE)
                data.toss = clean.rstrip(".")
                break

    # Status text from match zone only
    for line in zone_lines:
        lower = line.lower().strip()
        if not lower or lower.startswith("[") or lower.startswith("!"):
            continue
        if "delayed" in lower and "rain" in lower:
            data.status_text = re.sub(r"\*{1,2}", "", line.strip())
            break
        if "need" in lower and ("ball" in lower or "run" in lower):
            # Ensure it's about our teams
            t1u, t2u = team1.upper(), team2.upper()
            if t1u in line.upper() or t2u in line.upper():
                data.status_text = re.sub(r"\*{1,2}", "", line.strip())
                break

    # Detect completion — only in match zone header area (first 20 lines)
    for line in zone_lines[:20]:
        lower = line.lower()
        if "won by" in lower or "match tied" in lower or "no result" in lower:
            data.status = "completed"
            break

    return data


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
            md = r.markdown_v2.raw_markdown if hasattr(r, "markdown_v2") else r.markdown
            if not md:
                return None
            return parse_live_match(md, match_number, team1, team2)
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
            console.print(
                f"    Score: {data.score1 or '?'}"
                f" ({data.overs1 or '?'} ov)"
                f"  CRR: {data.current_rr or '?'}"
                f"  Forecast: {data.live_forecast or '?'}"
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
                if data.current_rr is not None:
                    m["current_rr"] = data.current_rr
                if data.required_rr is not None:
                    m["required_rr"] = data.required_rr
                if data.live_forecast:
                    m["live_forecast"] = data.live_forecast
                if data.status_text:
                    m["status_text"] = data.status_text
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
