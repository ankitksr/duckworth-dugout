"""Player availability state derivation.

Pure read-side module — no LLM calls. Reads from
war_room_player_availability_events (populated by article_extraction.py)
and derives the current state per player.

Rules:
  1. Latest event per player wins (ordered by article_published DESC,
     extracted_at DESC, id DESC).
  2. Clear-on-play override: if the player has a match appearance more
     recent than their latest event's article_published, status is
     forced to 'available' with reason 'returned to play'.

Usage:
    from pipeline.intel.availability import current_availability, last_played_dates
    played = last_played_dates(conn, season)
    state = current_availability(conn, season, played)
    # → {"Jasprit Bumrah": {"status": "out", "reason": "back stress", ...}}
"""

from datetime import date, datetime

import duckdb


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
        WITH ranked AS (
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
                quote,
                ROW_NUMBER() OVER (
                    PARTITION BY player_name
                    ORDER BY article_published DESC NULLS LAST,
                             extracted_at DESC,
                             id DESC
                ) AS rn
            FROM war_room_player_availability_events
            WHERE season = ?
        )
        SELECT player_name, franchise_id, status, reason, expected_return,
               article_guid, article_published, source, confidence, quote
        FROM ranked
        WHERE rn = 1
    """
    try:
        rows = conn.execute(sql, [season]).fetchall()
    except Exception:
        return {}

    last_played = last_played or {}
    result: dict[str, dict] = {}

    for (player, fid, status, reason, expected_return, guid,
         article_published, source, confidence, quote) in rows:

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
