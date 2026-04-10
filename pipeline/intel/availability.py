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

    Sourced from Cricsheet only. The scorecard crawl path returns
    appearance counts (not dates) so we accept the 1-6 day Cricsheet lag
    for clear-on-play override — a player who returns to play will be
    flagged as 'available' once Cricsheet catches up.
    """
    from pipeline.intel.roster_context import (
        _build_squad_name_index,
        _resolve_to_squad_name,
    )

    by_surname = _build_squad_name_index(conn, season)
    result: dict[str, str] = {}

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
        return result

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

    return result
