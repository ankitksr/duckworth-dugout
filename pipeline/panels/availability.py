"""Player availability panel.

Runs the per-article extraction layer (article_extraction.py) over any
unprocessed articles, then derives current player availability state and
writes availability.json. The per-article cache means hot-only runs that
have no new articles are essentially no-ops (LLM-cost-free).

Sits in PANEL_ORDER between intel_log and wire so that wire's hot-tier
roster context is always backed by the latest availability state.
"""

import asyncio
from datetime import datetime, timezone

from rich.console import Console

from pipeline.context import SyncContext
from pipeline.writer import write_panel

console = Console()


def sync(ctx: SyncContext) -> None:
    """Sync the player availability panel."""
    # Ensure DB connection (mirrors wire panel — hot-only runs may not
    # have called _init_db_and_articles).
    db_conn = ctx.db_conn
    if db_conn is None:
        try:
            from pipeline.db.connection import get_connection

            db_conn = get_connection()
            ctx.db_conn = db_conn
        except Exception as e:
            console.print(f"  [yellow]Availability: DB connection failed: {e}[/yellow]")
            return

    # 1. Extraction pass (capped — drains backlog over multiple syncs)
    try:
        from pipeline.intel.article_extraction import run_extraction
        stats = asyncio.run(run_extraction(db_conn, ctx.season, max_articles=30))
    except Exception as e:
        console.print(f"  [yellow]Article extraction failed: {e}[/yellow]")
        stats = {"events": 0, "processed": 0, "errors": 0}

    # 2. Derive current state
    try:
        from pipeline.intel.availability import (
            current_availability,
            last_played_dates,
        )
        played = last_played_dates(db_conn, ctx.season)
        state = current_availability(db_conn, ctx.season, played)
    except Exception as e:
        console.print(f"  [yellow]Availability state derivation failed: {e}[/yellow]")
        state = {}

    # 3. Build payload (filter to actionable, non-available players)
    payload = _build_payload(state, ctx.season, stats.get("events", 0))

    # 4. Dual-write JSON
    write_panel(
        "availability", payload,
        data_dir=ctx.data_dir, public_dir=ctx.public_dir,
        db_conn=db_conn, season=ctx.season,
    )

    ctx.meta["availability"] = {
        "synced_at": _now_iso(),
        "new_events": stats.get("events", 0),
        "total_unavailable": payload["total_unavailable"],
    }


def _build_payload(
    state: dict[str, dict],
    season: str,
    new_events: int,
) -> dict:
    """Filter to actionable (non-available) players, group by team."""
    by_team: dict[str, list[dict]] = {}
    flat: list[dict] = []

    for player, info in sorted(state.items()):
        if info.get("status") == "available":
            continue
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
