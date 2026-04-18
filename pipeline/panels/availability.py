"""Player availability panel.

Derives current player availability from war_room_player_availability_events
and writes availability.json. The per-article extraction that populates
those events runs upstream in sync._init_db_and_articles so every tier —
not just warm — sees fresh availability state without coupling the wire
panel to the availability panel's schedule.
"""

from datetime import date, datetime, timezone

import duckdb
from rich.console import Console

from pipeline.clock import today_ist_iso
from pipeline.context import SyncContext
from pipeline.writer import write_panel

console = Console()

# Threshold past which a standing absence stops being "news" and becomes
# baseline — rendered separately in the availability block so prompts
# don't restate it as fresh injury news every match.
_BASELINE_DAYS = 7


def sync(ctx: SyncContext) -> None:
    """Sync the player availability panel."""
    db_conn = ctx.db_conn
    if db_conn is None:
        try:
            from pipeline.db.connection import get_connection

            db_conn = get_connection()
            ctx.db_conn = db_conn
        except Exception as e:
            console.print(f"  [yellow]Availability: DB connection failed: {e}[/yellow]")
            return

    # 1. Derive current state
    try:
        from pipeline.intel.availability import (
            current_availability,
            last_played_dates,
        )
        from pipeline.intel.roster_context import _query_appearances
        played = last_played_dates(db_conn, ctx.season)
        state = current_availability(db_conn, ctx.season, played)
        # Apply appearance-based overrides on top of strict derivation:
        #   1. soften stale 'doubtful' (medium-conf rehashes)
        #   2. clear OUT/doubtful when the player has played within a
        #      7-day window of the article date and no concrete return
        #      timeline is given (catches past-tense "missed the match"
        #      recap articles published days after the actual absence).
        appearances = _query_appearances(db_conn, ctx.season)
        state = _apply_appearance_overrides(state, appearances, played)
    except Exception as e:
        console.print(f"  [yellow]Availability state derivation failed: {e}[/yellow]")
        state = {}

    new_events = ctx.extraction_stats.get("events", 0)

    # 2. Build payload (filter to actionable, non-available players)
    first_flagged = _first_out_flagged_per_player(db_conn, ctx.season)
    payload = _build_payload(state, ctx.season, new_events, first_flagged)

    # 3. Dual-write JSON
    write_panel(
        "availability", payload,
        data_dir=ctx.data_dir, public_dir=ctx.public_dir,
        db_conn=db_conn, season=ctx.season,
    )

    ctx.meta["availability"] = {
        "synced_at": _now_iso(),
        "new_events": new_events,
        "total_unavailable": payload["total_unavailable"],
    }


_RECAP_TOLERANCE_DAYS = 7


def _apply_appearance_overrides(
    state: dict[str, dict],
    appearances: dict[str, int],
    last_played: dict[str, str],
) -> dict[str, dict]:
    """Override the strict derivation with two appearance-based rules.

    **Rule 1 — soften stale doubtful** (rehash detection):
    Drop a 'doubtful' flag when ALL of:
      - confidence is medium / low / unset (high-confidence stays)
      - player has at least one appearance this season
      - article has no expected_return value (no concrete medical timeline)

    Rationale: a low-confidence "head coach reveals shoulder niggle" piece
    rehashing an older injury shouldn't outrank evidence the player is
    actively in playing XIs.

    **Rule 2 — clear OUT/doubtful within recap window**:
    Drop an 'out' or 'doubtful' flag when ALL of:
      - article has no expected_return value
      - player has a last_played date within ±7 days of the article date
      - the recent appearance is on or after the article date - 7 days

    Rationale: an article published Apr 9 saying "X missed the match" can
    refer to a match days earlier; if the player has played in the same
    7-day window, the strict `played_date > article_date` clear-on-play
    misses it. Concrete medical timelines ("ruled out for season",
    expected_return = '2026-04-14') are never overridden.

    'OUT' flags with concrete timelines are always treated as load-bearing.
    """
    from datetime import date, timedelta

    def _parse_iso(s: object) -> date | None:
        if not isinstance(s, str) or not s.strip():
            return None
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None

    overridden: dict[str, dict] = {}
    for player, info in state.items():
        new_info = dict(info)
        status = info.get("status")
        confidence = info.get("confidence", "")
        exp_return = (info.get("expected_return") or "").strip()
        appears = appearances.get(player, 0)

        # Rule 1: stale-doubtful softening
        if (
            status == "doubtful"
            and confidence in ("medium", "low", "")
            and appears > 0
            and not exp_return
        ):
            new_info["status"] = "available"
            new_info["reason"] = "post-play (article rehash suppressed)"
            overridden[player] = new_info
            continue

        # Rule 2: recap-window clear for OUT/doubtful
        if (
            status in ("out", "doubtful")
            and not exp_return
            and appears > 0
            and player in last_played
        ):
            played_d = _parse_iso(last_played.get(player))
            article_d = _parse_iso(info.get("as_of"))
            if played_d and article_d:
                window_start = article_d - timedelta(days=_RECAP_TOLERANCE_DAYS)
                if played_d >= window_start:
                    new_info["status"] = "available"
                    new_info["reason"] = (
                        f"recent appearance {played_d.isoformat()} within "
                        f"{_RECAP_TOLERANCE_DAYS}d of article {article_d.isoformat()}"
                    )
                    overridden[player] = new_info
                    continue

        overridden[player] = new_info
    return overridden


def _first_out_flagged_per_player(
    conn: duckdb.DuckDBPyConnection,
    season: str,
) -> dict[str, date]:
    """Map player → date they were first flagged `out` in the current
    continuous absence.

    "Continuous absence" = earliest `out` event AFTER the most recent
    `available` event (if any). A player who was cleared and then re-flagged
    is counted from the re-flag, not from the first flag of the season.
    """
    try:
        rows = conn.execute(
            """
            WITH ranked AS (
                SELECT
                    player_name,
                    status,
                    article_published,
                    MAX(CASE WHEN status = 'available'
                            THEN article_published END)
                        OVER (PARTITION BY player_name
                              ORDER BY article_published
                              ROWS BETWEEN UNBOUNDED PRECEDING
                                       AND CURRENT ROW) AS last_available
                FROM war_room_player_availability_events
                WHERE season = ? AND article_published IS NOT NULL
            )
            SELECT player_name, MIN(article_published) AS first_out
            FROM ranked
            WHERE status = 'out'
              AND (last_available IS NULL OR article_published > last_available)
            GROUP BY player_name
            """,
            [season],
        ).fetchall()
    except Exception:
        return {}
    out: dict[str, date] = {}
    for name, first_out in rows:
        if first_out is None:
            continue
        if isinstance(first_out, datetime):
            out[name] = first_out.date()
        elif isinstance(first_out, date):
            out[name] = first_out
    return out


def _build_payload(
    state: dict[str, dict],
    season: str,
    new_events: int,
    first_flagged: dict[str, date],
) -> dict:
    """Filter to actionable (non-available) players, group by team.

    Each entry carries `days_since_flagged` + `is_baseline` so downstream
    consumers (briefing, dossier, wire) can distinguish fresh news from
    standing absences already absorbed into team form.
    """
    by_team: dict[str, list[dict]] = {}
    flat: list[dict] = []

    today = date.fromisoformat(today_ist_iso())

    for player, info in sorted(state.items()):
        if info.get("status") == "available":
            continue

        days_since = -1
        is_baseline = False
        first_out = first_flagged.get(player)
        if first_out:
            days_since = (today - first_out).days
            is_baseline = (
                info.get("status") == "out"
                and days_since > _BASELINE_DAYS
            )

        entry = {
            "player": player,
            "franchise_id": info.get("franchise_id", ""),
            "status": info.get("status", ""),
            "reason": info.get("reason", ""),
            "expected_return": info.get("expected_return", ""),
            "source": info.get("source", ""),
            "quote": info.get("quote", ""),
            "as_of": info.get("as_of", ""),
            "confidence": info.get("confidence", ""),
            "days_since_flagged": days_since,
            "is_baseline": is_baseline,
        }
        flat.append(entry)
        by_team.setdefault(entry["franchise_id"], []).append(entry)

    return {
        "generated_at": _now_iso(),
        "season": season,
        "new_events": new_events,
        "total_unavailable": len(flat),
        "by_team": by_team,
        "players": flat,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
