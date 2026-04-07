"""Post-match scorecard extraction via LLM from the articles store.

Queries war_room_articles (DuckDB) for articles about scoreless matches,
sends the combined text to Gemini Flash, extracts structured match data.

No keyword filtering — all relevant articles are concatenated and the LLM
decides what's useful. Cached by match key (team pair + date), not prompt hash,
so resyncs don't burn LLM calls.

Usage:
    from pipeline.intel.extract import extract_match_results
    extracts = await extract_match_results(conn, schedule_matches)
"""

import json
import re
from dataclasses import dataclass
from typing import Any

import duckdb
from rich.console import Console

from pipeline.intel.articles import retrieve_for_match
from pipeline.intel.schemas import MatchExtractResponse
from pipeline.llm.cache import LLMCache
from pipeline.models import ScheduleMatch
from pipeline.sources.feeds import detect_teams

console = Console()

_CACHE_TASK = "war_room_extract"


@dataclass
class MatchExtract:
    """Structured data extracted from RSS match articles."""

    team1: str  # franchise ID (who batted first)
    team2: str  # franchise ID (who chased)
    team1_score: str  # "141/10"
    team1_overs: str  # "18.4"
    team2_score: str  # "145/4"
    team2_overs: str  # "17.1"
    winner: str  # franchise ID
    margin: str  # "6 wickets"
    result_text: str  # "DC won by 6 wickets"
    player_of_match: str | None  # "Sameer Rizvi"
    hero_stat: str | None  # "70*(47)"


_SYSTEM_PROMPT = """\
You are a cricket data extractor. Given article text about an IPL match, \
extract the structured scorecard data. Be precise with numbers — scores, \
overs, and margins must exactly match what the articles say. If multiple \
articles mention different numbers, prefer the most commonly mentioned. \
If a field is not mentioned anywhere, use an empty string."""

_USER_PROMPT = """\
Extract the match result data from these IPL articles about {team1} vs {team2}:

{article_text}

Return ONLY a JSON object with these fields:
- team1_name: who batted first (full or short name)
- team1_score: first innings score (e.g. "141/10")
- team1_overs: first innings overs (e.g. "18.4")
- team2_name: who batted second / chased
- team2_score: second innings score (e.g. "145/4")
- team2_overs: second innings overs (e.g. "17.1")
- winner_name: winning team name
- margin: victory margin (e.g. "6 wickets", "34 runs")
- player_of_match: MOTM name or empty string
- hero_name: best performer's name
- hero_stat: best performer's stat line (e.g. "70*(47)", "3/27")"""


def _resolve_team_id(name: str) -> str:
    """Resolve a team name to franchise ID using detect_teams."""
    teams = detect_teams(name)
    return teams[0] if teams else name.lower().strip()


def _make_match_key(team1: str, team2: str, date: str) -> str:
    """Stable cache key for a match — independent of prompt text."""
    pair = "_".join(sorted([team1, team2]))
    return f"{pair}_{date}"


async def _extract_from_articles(
    article_text: str,
    team1: str,
    team2: str,
    match_key: str,
    cache: LLMCache,
) -> dict[str, Any] | None:
    """Send combined article text to Gemini Flash for extraction."""
    from pipeline.llm.gemini import GeminiProvider

    # Check cache by match key (not prompt hash)
    cached = cache.get(_CACHE_TASK, match_key)
    if cached and cached.get("parsed"):
        console.print(
            f"  [dim]Extract: cache hit for {match_key}[/dim]"
        )
        return cached["parsed"]

    provider = GeminiProvider()
    prompt = _USER_PROMPT.format(
        team1=team1.upper(),
        team2=team2.upper(),
        article_text=article_text,
    )

    result = await provider.generate(
        prompt,
        system=_SYSTEM_PROMPT,
        temperature=0.1,
        response_schema=MatchExtractResponse,
    )

    # Parse response — handle markdown fences, raw JSON
    parsed = result.get("parsed")
    if not parsed:
        text = result.get("text", "").strip()
        if text.startswith("```"):
            text = re.sub(r"```(?:json)?\n?", "", text).strip()
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                try:
                    parsed = json.loads(m.group())
                except (json.JSONDecodeError, ValueError):
                    pass
            if not parsed:
                console.print(
                    "  [yellow]Extract: failed to parse"
                    " LLM response[/yellow]"
                )
                return None

    # Only cache if extraction produced actual scores — empty results
    # should be retried on next sync when more articles may be available.
    has_scores = bool(
        parsed.get("team1_score") or parsed.get("team2_score")
    )
    if has_scores:
        cache.put(_CACHE_TASK, match_key, {
            "parsed": parsed,
            "usage": result.get("usage", {}),
        })
    else:
        console.print(
            f"  [yellow]Extract: no scores found for {match_key}"
            " — not caching (will retry)[/yellow]"
        )

    return parsed


def _parsed_to_extract(parsed: dict[str, Any]) -> MatchExtract | None:
    """Convert parsed LLM output to a MatchExtract.

    Returns None if essential fields (scores, teams) are missing.
    """
    try:
        t1 = _resolve_team_id(parsed.get("team1_name", ""))
        t2 = _resolve_team_id(parsed.get("team2_name", ""))
        winner = _resolve_team_id(parsed.get("winner_name", ""))

        if not t1 or not t2 or not winner:
            return None

        t1_score = parsed.get("team1_score", "")
        t2_score = parsed.get("team2_score", "")
        if not t1_score and not t2_score:
            console.print(
                "  [yellow]Extract: LLM returned empty scores"
                " — articles may lack scorecard data[/yellow]"
            )
            return None

        margin = parsed.get("margin", "")
        winner_short = winner.upper()
        result_text = (
            f"{winner_short} won by {margin}" if margin
            else f"{winner_short} won"
        )

        return MatchExtract(
            team1=t1,
            team2=t2,
            team1_score=t1_score,
            team1_overs=parsed.get("team1_overs", ""),
            team2_score=t2_score,
            team2_overs=parsed.get("team2_overs", ""),
            winner=winner,
            margin=margin,
            result_text=result_text,
            player_of_match=parsed.get("player_of_match") or parsed.get("hero_name") or None,
            hero_stat=parsed.get("hero_stat") or None,
        )
    except (KeyError, TypeError):
        return None


def patch_schedule_from_extracts(
    matches: list[ScheduleMatch],
    extracts: list[MatchExtract],
) -> int:
    """Apply extracted match data to schedule entries.

    Patches two categories of completed matches:
    - Missing scores: full patch (scores, winner, result, hero)
    - Missing hero only: patch hero_name and hero_stat from extraction

    Returns count of patched matches.
    """
    extract_map: dict[frozenset[str], MatchExtract] = {}
    for ex in extracts:
        extract_map[frozenset([ex.team1, ex.team2])] = ex

    count = 0
    for match in matches:
        if match.status != "completed":
            continue

        pair = frozenset([match.team1, match.team2])
        ex = extract_map.get(pair)
        if not ex:
            continue

        if match.score1 is None:
            # Full patch: scores + winner + result + hero
            if ex.team1 == match.team1:
                match.score1 = ex.team1_score
                match.score2 = ex.team2_score
                match.overs1 = (
                    f"{ex.team1_overs} ov" if ex.team1_overs else None
                )
                match.overs2 = (
                    f"{ex.team2_overs} ov" if ex.team2_overs else None
                )
            else:
                match.score1 = ex.team2_score
                match.score2 = ex.team1_score
                match.overs1 = (
                    f"{ex.team2_overs} ov" if ex.team2_overs else None
                )
                match.overs2 = (
                    f"{ex.team1_overs} ov" if ex.team1_overs else None
                )

            match.winner = ex.winner
            match.result = ex.result_text
            match.hero_name = ex.player_of_match or match.hero_name
            match.hero_stat = ex.hero_stat or match.hero_stat
            count += 1
        elif match.hero_name is None:
            # Hero-only patch: scores already present
            if ex.player_of_match:
                match.hero_name = ex.player_of_match
                match.hero_stat = ex.hero_stat or match.hero_stat
                count += 1

    return count


async def extract_match_results(
    conn: duckdb.DuckDBPyConnection,
    matches: list[ScheduleMatch],
) -> list[MatchExtract]:
    """Extract match results from the articles store.

    Runs for completed matches that are either:
    - Missing scores (primary use case)
    - Missing hero_name (POTM fallback from RSS)

    Queries war_room_articles for relevant content, sends to LLM,
    returns structured MatchExtract objects.
    """
    needs_extract = [
        m for m in matches
        if m.status == "completed"
        and (m.score1 is None or m.hero_name is None)
    ]

    if not needs_extract:
        return []

    scoreless = sum(1 for m in needs_extract if m.score1 is None)
    heroless = sum(1 for m in needs_extract if m.score1 is not None and m.hero_name is None)
    parts = []
    if scoreless:
        parts.append(f"{scoreless} missing scores")
    if heroless:
        parts.append(f"{heroless} missing hero")
    console.print(
        f"  [dim]Extract: {', '.join(parts)}[/dim]"
    )

    cache = LLMCache()
    extracts: list[MatchExtract] = []

    for match in needs_extract:
        match_key = _make_match_key(
            match.team1, match.team2, match.date,
        )

        # Retrieve articles from DuckDB
        article_text = retrieve_for_match(
            conn, match.team1, match.team2, match.date,
        )

        if not article_text:
            console.print(
                f"  [yellow]Extract: no articles for"
                f" {match.team1.upper()} vs"
                f" {match.team2.upper()}[/yellow]"
            )
            continue

        console.print(
            f"  [dim]Extract: {len(article_text)} chars"
            f" for {match.team1.upper()} vs"
            f" {match.team2.upper()}[/dim]"
        )

        parsed = await _extract_from_articles(
            article_text, match.team1, match.team2, match_key, cache,
        )
        if parsed:
            extract = _parsed_to_extract(parsed)
            if extract:
                extracts.append(extract)
                console.print(
                    f"  [green]Extract: {extract.result_text}"
                    f" ({extract.team1_score}"
                    f" vs {extract.team2_score})[/green]"
                )

    return extracts
