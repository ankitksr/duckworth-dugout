"""Player availability state derivation.

Pure read-side module — no LLM calls. Reads from
war_room_player_availability_events (populated by article_extraction.py)
and derives the current state per player.

Rules (applied in order, within a 72-hour recency window per player):
  1. **Past-tense backstop:** events whose quote is obviously a historical
     recap ("X missed the match", "sat out", "with X unwell", "in X's
     absence") are demoted — an availability claim should be current or
     forward-looking. This catches extraction failures where a retrospective
     aside in an unrelated article (e.g. a ticket-scam story mentioning
     "Pandya missed the match because of illness") produced a fresh out
     event.
  2. **Source weighting:** within the recency window, higher-quality
     sources (ESPNcricinfo, Wisden) outweigh aggregators (CricketAddictor)
     even if the aggregator event is a day fresher. Outside the window,
     strict recency still wins.
  3. **Clear-on-play override:** if the player has a match appearance
     more recent than the winning event's article_published, status is
     forced to 'available' with reason 'returned to play'.

Usage:
    from pipeline.intel.availability import current_availability, last_played_dates
    played = last_played_dates(conn, season)
    state = current_availability(conn, season, played)
    # → {"Jasprit Bumrah": {"status": "out", "reason": "back stress", ...}}
"""

import re
from datetime import date, datetime, timedelta

import duckdb

# Higher = more authoritative. ESPNcricinfo has live scorecards + team
# news, Wisden runs direct playing XI reports, CricTracker is polished
# feature journalism, CricketAddictor is aggregator-heavy and prone to
# mixing past recap with current reporting.
_SOURCE_WEIGHT: dict[str, int] = {
    "espncricinfo": 10,
    "wisden": 9,
    "crictracker": 6,
    "cricketaddictor": 4,
}
_DEFAULT_WEIGHT = 3

# Events within this window compete by source weight; older events are
# strictly dominated by newer ones.
_RECENCY_WINDOW = timedelta(hours=72)

# Past-tense recap markers — quotes matching these describe a prior
# absence rather than a current status claim and should be demoted when
# a contradictory current-window event exists.
_PAST_TENSE_MARKERS = (
    r"\bmissed the\b",
    r"\bmissed a game\b",
    r"\bsat out\b",
    r"\bwas unavailable\b",
    r"\bhad missed\b",
    r"\bhad been unavailable\b",
    r"\bin .+'s absence\b",
    r"\bwith .+ unwell\b",
    r"\bleading in .+'s absence\b",
    r"\bwho had missed\b",
    r"\bafter having missed\b",
    r"\bafter missing\b",
)
_PAST_TENSE_RE = re.compile("|".join(_PAST_TENSE_MARKERS), re.IGNORECASE)


def _is_past_tense_recap(quote: str | None) -> bool:
    """Detect whether an event's quote is a historical recap.

    Intentionally conservative — only matches explicit past-tense phrases
    that describe a prior absence. A forward-looking claim like "will
    miss the next match" does NOT trigger this.
    """
    if not quote:
        return False
    return bool(_PAST_TENSE_RE.search(quote))


def _source_weight(source: str | None) -> int:
    if not source:
        return _DEFAULT_WEIGHT
    return _SOURCE_WEIGHT.get(source.strip().lower(), _DEFAULT_WEIGHT)


def _to_date(value: object) -> date | None:
    """Coerce a DuckDB result (date / datetime / str) to a date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None
    return None


def _pick_winning_event(events: list[tuple]) -> tuple | None:
    """Choose the canonical availability event for a player.

    Input: all events for a single player, pre-sorted most-recent first.
    Each tuple is (fid, status, reason, expected_return, guid,
    article_published, source, confidence, quote).

    Selection logic:
      1. Find the anchor = most recent non-past-tense event. If every
         event is a past-tense recap, fall back to the literal most
         recent (shouldn't happen in practice for legitimate extractions).
      2. Build the "decision window" = all events within _RECENCY_WINDOW
         hours of the anchor (anchor included).
      3. Within the window, pick the highest-source-weight event.
      4. Ties broken by most-recent article_published, then by event id
         (via the caller's pre-sort).

    The window-then-weight order matters: old high-quality events must
    not dominate new ones. Within a recent cluster of competing claims,
    source quality decides.
    """
    if not events:
        return None

    # Step 1: find a non-past-tense anchor
    anchor: tuple | None = None
    for e in events:
        quote = e[8]
        if not _is_past_tense_recap(quote):
            anchor = e
            break
    if anchor is None:
        anchor = events[0]  # fall back to most recent

    anchor_date = _to_date(anchor[5])
    if anchor_date is None:
        return anchor

    # Step 2: window around the anchor
    window_cutoff = anchor_date - _RECENCY_WINDOW.days * timedelta(days=1)
    window_candidates: list[tuple] = []
    for e in events:
        ed = _to_date(e[5])
        if ed is None:
            continue
        if ed >= window_cutoff:
            # Events inside or equal to the window — include but still
            # reject past-tense recaps from winning the pick.
            if _is_past_tense_recap(e[8]):
                continue
            window_candidates.append(e)

    if not window_candidates:
        return anchor

    # Step 3: highest source weight wins. Ties → pre-sorted order
    # (most-recent article_published already at the front).
    window_candidates.sort(
        key=lambda e: _source_weight(e[6]),
        reverse=True,
    )
    return window_candidates[0]


def current_availability(
    conn: duckdb.DuckDBPyConnection,
    season: str,
    last_played: dict[str, str] | None = None,
) -> dict[str, dict]:
    """Return current availability state per player.

    Output: {player_name: {franchise_id, status, reason, expected_return,
                           source, quote, confidence, as_of}}.

    last_played: optional dict of {player_name: ISO date string} of the
    most recent match the player appeared in. Used for clear-on-play
    override (only meaningful for status='out' or 'doubtful').
    """
    sql = """
        SELECT
            player_name,
            franchise_id,
            status,
            reason,
            expected_return,
            article_guid,
            article_published,
            source,
            confidence,
            quote
        FROM war_room_player_availability_events
        WHERE season = ?
        ORDER BY player_name,
                 article_published DESC NULLS LAST,
                 extracted_at DESC,
                 id DESC
    """
    try:
        rows = conn.execute(sql, [season]).fetchall()
    except Exception:
        return {}

    last_played = last_played or {}
    result: dict[str, dict] = {}

    # Group by player (rows are already sorted player_name ASC, then
    # most-recent-first within each player)
    by_player: dict[str, list[tuple]] = {}
    for r in rows:
        by_player.setdefault(r[0], []).append(r[1:])

    for player, events in by_player.items():
        chosen = _pick_winning_event(events)
        if chosen is None:
            continue
        (fid, status, reason, expected_return, guid,
         article_published, source, confidence, quote) = chosen

        # Clear-on-play override
        article_date = _to_date(article_published)
        played_date = _to_date(last_played.get(player))
        if (
            status in ("out", "doubtful")
            and played_date is not None
            and article_date is not None
            and played_date > article_date
        ):
            status = "available"
            reason = "returned to play"
            expected_return = None

        as_of_iso = ""
        if article_date is not None:
            as_of_iso = article_date.isoformat()

        result[player] = {
            "franchise_id": fid,
            "status": status,
            "reason": reason or "",
            "expected_return": expected_return or "",
            "source": source or "",
            "quote": quote or "",
            "confidence": confidence or "",
            "as_of": as_of_iso,
            "article_guid": guid,
        }

    return result


def last_played_dates(
    conn: duckdb.DuckDBPyConnection,
    season: str,
) -> dict[str, str]:
    """Most recent match date per player this season (ISO 8601).

    Sources, merged max-wins:
      1. Cricsheet (canonical, lags 1-6 days)
      2. ESPNcricinfo scorecard cache (fresh, only matches Cricsheet hasn't
         ingested yet)

    The scorecard layer was historically counts-only; we now derive dates
    by intersecting cached scorecard players against schedule.json's match
    dates by match_number. This closes the lag window for clear-on-play
    overrides — a player who returned to play in the last 1-6 days will be
    correctly marked available before Cricsheet catches up.
    """
    from pipeline.intel.roster_context import (
        _build_squad_name_index,
        _resolve_to_squad_name,
    )

    by_surname = _build_squad_name_index(conn, season)
    result: dict[str, str] = {}

    # 1. Cricsheet (canonical)
    cricket_sql = """
        SELECT p.name, MAX(m.date) AS last_date
        FROM (
            SELECT match_id, player_id FROM cricket.batting_scorecard
            UNION
            SELECT match_id, player_id FROM cricket.bowling_scorecard
        ) x
        JOIN cricket.players p ON x.player_id = p.id
        JOIN cricket.matches m ON x.match_id = m.id
        WHERE m.event_name = 'Indian Premier League'
          AND m.season = ?
        GROUP BY p.name
    """
    try:
        rows = conn.execute(cricket_sql, [season]).fetchall()
    except Exception:
        rows = []

    for name, last_date in rows:
        squad_name = _resolve_to_squad_name(name, by_surname)
        iso = ""
        if last_date is not None:
            if isinstance(last_date, (date, datetime)):
                iso = last_date.isoformat()[:10]
            else:
                iso = str(last_date)[:10]
        if iso and (squad_name not in result or iso > result[squad_name]):
            result[squad_name] = iso

    # 2. ESPNcricinfo scorecard cache (fills the 1-6 day lag window)
    try:
        sc_dates = _last_played_dates_from_scorecards()
        for raw_name, iso in sc_dates.items():
            squad_name = _resolve_to_squad_name(raw_name, by_surname)
            if squad_name not in result or iso > result[squad_name]:
                result[squad_name] = iso
    except Exception:
        pass

    return result


def _last_played_dates_from_scorecards() -> dict[str, str]:
    """Per-player most-recent match date from cached ESPNcricinfo scorecards.

    Loads schedule.json to map match_number → date, then walks the
    crawl/scorecard cache directory. Returns {raw_player_name: ISO date};
    name normalization to squad names is done by the caller.

    Pure file-system read — no network, no DB. Returns {} on any failure.
    """
    import json
    from pathlib import Path

    from pipeline.config import DATA_DIR, ROOT_DIR

    # Find schedule.json (try both locations)
    sched_path = None
    for candidate in (
        DATA_DIR / "war-room" / "schedule.json",
        ROOT_DIR / "frontend" / "public" / "api" / "ipl" / "war-room" / "schedule.json",
    ):
        if candidate.exists():
            sched_path = candidate
            break
    if sched_path is None:
        return {}

    try:
        schedule = json.loads(sched_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    by_match_num: dict[int, str] = {}
    for m in schedule:
        if m.get("status") != "completed":
            continue
        mn = m.get("match_number")
        d = m.get("date")
        if isinstance(mn, int) and isinstance(d, str) and d:
            by_match_num[mn] = d

    cache_dir = ROOT_DIR / "cache" / "crawl" / "scorecard"
    if not cache_dir.exists():
        return {}

    result: dict[str, str] = {}
    for cache_file in cache_dir.glob("m*.json"):
        try:
            mn = int(cache_file.stem.lstrip("m"))
        except ValueError:
            continue
        match_date = by_match_num.get(mn)
        if not match_date:
            continue
        try:
            data = json.loads(Path(cache_file).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for player in data.get("players", []):
            if not isinstance(player, str) or not player.strip():
                continue
            current = result.get(player)
            if current is None or match_date > current:
                result[player] = match_date

    return result
