"""Post-match scorecard extraction from per-article structured claims.

Reads `match_result_claim` rows out of war_room_article_extractions
(populated by article_extraction.py) and aggregates them across all
articles mentioning a team pair to produce a unified MatchExtract.

Replaces the old per-team-pair LLM call: each article is now extracted
exactly once by the upstream layer, and this module just tallies the
results. Net effect: zero LLM calls during schedule sync (down from
one call per scoreless match).

Usage:
    from pipeline.intel.extract import extract_match_results
    extracts = await extract_match_results(conn, schedule_matches)
"""

import json
from collections import Counter
from dataclasses import dataclass

import duckdb
from rich.console import Console

from pipeline.intel.article_extraction import EXTRACTION_VERSION
from pipeline.models import ScheduleMatch
from pipeline.sources.feeds import detect_teams

console = Console()


@dataclass
class MatchExtract:
    """Aggregated match data derived from per-article extractions."""

    team1: str  # franchise ID (who batted first, per the LLM's interpretation)
    team2: str  # franchise ID (who chased)
    team1_score: str  # "141/10"
    team1_overs: str  # "" — overs not extracted at the article level
    team2_score: str  # "145/4"
    team2_overs: str  # ""
    winner: str  # franchise ID
    margin: str  # "6 wickets"
    result_text: str  # "DC won by 6 wickets"
    player_of_match: str | None  # "Sameer Rizvi"
    hero_stat: str | None  # "70*(47)"


def _resolve_team_id(name: str) -> str:
    """Resolve a team name to franchise ID using detect_teams."""
    if not name:
        return ""
    teams = detect_teams(name)
    return teams[0] if teams else name.lower().strip()


def _aggregate(values: list[str]) -> str:
    """Most-common non-empty value (majority vote). Empty if all empty."""
    non_empty = [v.strip() for v in values if v and v.strip()]
    if not non_empty:
        return ""
    return Counter(non_empty).most_common(1)[0][0]


def _query_claims(
    conn: duckdb.DuckDBPyConnection,
    team1: str,
    team2: str,
    match_date: str,
) -> list[dict]:
    """Fetch all per-article match result claims for a team pair.

    Returns claims as dicts (parsed from the stored JSON column).
    """
    sql = """
        SELECT e.match_result_claim
        FROM war_room_articles a
        JOIN war_room_article_extractions e
          ON e.article_guid = a.guid AND e.extraction_version = ?
        WHERE a.is_ipl = TRUE
          AND e.is_relevant = TRUE
          AND list_contains(a.teams, ?)
          AND list_contains(a.teams, ?)
          AND a.published >= (CAST(? AS DATE) - INTERVAL '1 day')
          AND a.published <= (CAST(? AS DATE) + INTERVAL '3 days')
          AND e.match_result_claim IS NOT NULL
        ORDER BY a.published DESC
    """
    try:
        rows = conn.execute(
            sql, [EXTRACTION_VERSION, team1, team2, match_date, match_date],
        ).fetchall()
    except Exception:
        return []

    claims: list[dict] = []
    for (raw,) in rows:
        if not raw:
            continue
        try:
            claim = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            continue
        if not isinstance(claim, dict):
            continue
        # Skip empty claims (article wasn't a match report)
        if not (claim.get("winner") or claim.get("team1_score") or claim.get("team2_score")):
            continue
        claims.append(claim)
    return claims


def _aggregate_match(
    match: ScheduleMatch,
    claims: list[dict],
) -> MatchExtract | None:
    """Aggregate per-article claims into a single MatchExtract.

    Aligns each claim's team1/team2 to match.team1/match.team2 by franchise
    ID. Drops claims that resolve to a different team pair.
    """
    # Per-team score buckets keyed by franchise ID
    scores: dict[str, list[str]] = {match.team1: [], match.team2: []}
    winners: list[str] = []
    margins: list[str] = []
    potms: list[str] = []
    heroes: list[str] = []

    for claim in claims:
        t1_fid = _resolve_team_id(claim.get("team1", ""))
        t2_fid = _resolve_team_id(claim.get("team2", ""))
        valid_pair = {t1_fid, t2_fid} == {match.team1, match.team2}
        if not valid_pair:
            continue

        # Map per-team scores by franchise ID
        if claim.get("team1_score") and t1_fid in scores:
            scores[t1_fid].append(claim["team1_score"])
        if claim.get("team2_score") and t2_fid in scores:
            scores[t2_fid].append(claim["team2_score"])

        winner_fid = _resolve_team_id(claim.get("winner", ""))
        if winner_fid in (match.team1, match.team2):
            winners.append(winner_fid)
        if claim.get("margin"):
            margins.append(claim["margin"])
        if claim.get("player_of_match"):
            potms.append(claim["player_of_match"])
        if claim.get("hero_stat"):
            heroes.append(claim["hero_stat"])

    # Need at least one valid claim
    if not winners and not any(scores.values()):
        return None

    winner = _aggregate(winners)
    if not winner:
        return None

    team1_score = _aggregate(scores[match.team1])
    team2_score = _aggregate(scores[match.team2])
    margin = _aggregate(margins)
    potm = _aggregate(potms)
    hero = _aggregate(heroes)

    winner_short = winner.upper()
    result_text = (
        f"{winner_short} won by {margin}" if margin else f"{winner_short} won"
    )

    return MatchExtract(
        team1=match.team1,
        team2=match.team2,
        team1_score=team1_score,
        team1_overs="",
        team2_score=team2_score,
        team2_overs="",
        winner=winner,
        margin=margin,
        result_text=result_text,
        player_of_match=potm or None,
        hero_stat=hero or None,
    )


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
    """Aggregate match result claims from the article extraction store.

    For each completed match missing scores or hero, query all per-article
    match_result_claim rows for that team pair, vote across non-empty
    fields, and return a MatchExtract. Async signature is preserved for
    backward compatibility but no LLM calls happen.
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
    console.print(f"  [dim]Extract: {', '.join(parts)}[/dim]")

    extracts: list[MatchExtract] = []
    for match in needs_extract:
        claims = _query_claims(conn, match.team1, match.team2, match.date)
        if not claims:
            console.print(
                f"  [yellow]Extract: no claims for"
                f" {match.team1.upper()} vs {match.team2.upper()}[/yellow]"
            )
            continue

        ex = _aggregate_match(match, claims)
        if ex is None:
            console.print(
                f"  [yellow]Extract: claims for"
                f" {match.team1.upper()} vs {match.team2.upper()}"
                " did not aggregate cleanly[/yellow]"
            )
            continue

        extracts.append(ex)
        console.print(
            f"  [green]Extract: {ex.result_text}"
            f" ({ex.team1_score} vs {ex.team2_score})"
            f" — {len(claims)} article claim(s)[/green]"
        )

    return extracts
