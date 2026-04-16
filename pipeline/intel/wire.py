"""AI Wire — multi-generator editorial intelligence for the War Room.

Five specialized generators feed the wire panel, each focused on a
distinct editorial angle with its own context, tools, and voice:

  1. Situation Room — points table math, playoff scenarios (Flash)
  2. Scout Report   — player performances, form, cap races (Pro)
  3. News Desk      — editorial reaction to breaking articles (Flash)
  4. Matchday Preview — tactical previews for today's fixtures (Pro)
  5. The Take        — provocative counter-narratives, synthesis (Pro)

Generators 1-4 run in parallel. Generator 5 (The Take) runs after,
seeing the others' output for synthesis and counter-narrative.

The export function applies structural aggregation rules:
  - Per-team cap (max 4 visible entries)
  - Source diversity (no 3+ consecutive from same source)
  - Severity ordering (alarm > alert > signal)

Daily reset: previous day's entries are marked expired.

Usage:
    entries = await generate_wire(conn, season, today_matches)
    wire_data = export_wire_json(conn, season)
"""

import asyncio
from datetime import datetime, timezone

import duckdb
from rich.console import Console

from pipeline.clock import today_ist_iso
from pipeline.intel.live_context import (
    build_live_context,
    format_availability_block,
)
from pipeline.intel.roster_context import summary as roster_summary
from pipeline.intel.wire_generators import HASH_VERSION, GeneratorContext
from pipeline.intel.wire_generators.archive import TheArchiveGenerator
from pipeline.intel.wire_generators.newsdesk import NewsDeskGenerator
from pipeline.intel.wire_generators.preview import MatchdayPreviewGenerator
from pipeline.intel.wire_generators.scout import ScoutReportGenerator
from pipeline.intel.wire_generators.situation import SituationRoomGenerator
from pipeline.intel.wire_generators.take import TheTakeGenerator
from pipeline.ipl.franchise_metadata import IPL_FRANCHISES
from pipeline.models import ScheduleMatch

console = Console()

_SHORT = {fid: d["short_name"] for fid, d in IPL_FRANCHISES.items() if not d.get("defunct")}


# ── Base context builder ────────────────────────────────────────────

def _build_base_context(
    conn: duckdb.DuckDBPyConnection,
    season: str,
    live_ctx: dict,
) -> str:
    """Build the shared grounding context (~400 tokens) for all generators.

    Contains: season info, roster summary, table snapshot, and the
    verified injury/availability block. Pulls everything from live_ctx
    so all wire generators see the same snapshot the rest of the LLM
    layer sees.
    """
    parts: list[str] = []

    standings = live_ctx.get("standings") or []
    schedule = live_ctx.get("schedule") or []

    # Season header
    completed = sum(1 for m in schedule if m.get("status") == "completed")
    total = len(schedule)
    today = live_ctx.get("today_ist") or today_ist_iso()
    parts.append(
        f"SEASON: IPL {season} | {completed}/{total} matches completed | TODAY: {today}"
    )

    # Compact roster summary (1 line per team — names + captain/overseas markers)
    roster = roster_summary(conn, season)
    if roster:
        parts.append(roster)

    # Table snapshot (compact single-line per team)
    if standings:
        table_line = " | ".join(
            f"{s['position']}.{s['short_name']} {s['wins']}-{s['losses']} "
            f"NRR:{s['nrr']}"
            for s in standings
        )
        parts.append(f"TABLE SNAPSHOT:\n{table_line}")

    # Injury/availability ground truth (shared formatter so every LLM
    # generator renders it identically)
    avail_block = format_availability_block(live_ctx)
    if avail_block:
        parts.append(avail_block)

    return "\n\n".join(parts)


# ── DB helpers ──────────────────────────────────────────────────────

def _expire_previous_day(
    conn: duckdb.DuckDBPyConnection,
    season: str,
    today: str,
) -> int:
    """Mark entries from previous days as expired."""
    result = conn.execute(
        """
        UPDATE war_room_wire
        SET expired = TRUE
        WHERE season = ? AND expired = FALSE
          AND (match_day IS NULL OR match_day < ?)
        RETURNING id
        """,
        [season, today],
    ).fetchall()
    return len(result)


def _expire_legacy_hash_version(
    conn: duckdb.DuckDBPyConnection,
    season: str,
    today: str,
) -> int:
    """Expire same-day rows produced by an older hash version.

    When HASH_VERSION is bumped, the new generators emit hashes that can
    never collide with old rows — so old same-day rows would otherwise
    persist in the wire alongside the new ones. Idempotent: once a row is
    expired it no longer matches the WHERE clause.
    """
    result = conn.execute(
        """
        UPDATE war_room_wire
        SET expired = TRUE
        WHERE season = ? AND expired = FALSE AND match_day = ?
          AND coalesce(hash_version, 'v1') != ?
        RETURNING id
        """,
        [season, today, HASH_VERSION],
    ).fetchall()
    return len(result)


def _insert_items(
    conn: duckdb.DuckDBPyConnection,
    items: list[dict],
    season: str,
    today: str,
) -> None:
    """Insert generated wire items into the database."""
    if not items:
        return

    row = conn.execute(
        "SELECT coalesce(max(id), 0) FROM war_room_wire"
    ).fetchone()
    next_id = (row[0] if row else 0) + 1

    for i, item in enumerate(items):
        conn.execute(
            """
            INSERT INTO war_room_wire
                (id, headline, text, emoji, category, severity, teams,
                 source, context_hash, hash_version, season, match_day)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                next_id + i,
                item["headline"],
                item["text"],
                item["emoji"],
                item["category"],
                item["severity"],
                item["teams"],
                item.get("source", "wire"),
                item.get("_context_hash", ""),
                HASH_VERSION,
                season,
                today,
            ],
        )


# ── Main orchestrator ───────────────────────────────────────────────

async def generate_wire(
    conn: duckdb.DuckDBPyConnection,
    season: str,
    today_matches: list[ScheduleMatch],
    *,
    force: bool = False,
) -> list[dict]:
    """Run all wire generators and insert results.

    Generators 1-4 run in parallel via asyncio.gather.
    Generator 5 (The Take) runs after, seeing the others' output.

    Returns all newly generated items.
    """
    today_str = today_ist_iso()

    # Daily reset
    expired = _expire_previous_day(conn, season, today_str)
    if expired:
        console.print(f"  [dim]Wire: expired {expired} previous-day entries[/dim]")

    # Migration: expire same-day rows from older hash versions on first
    # post-deploy run after a HASH_VERSION bump.
    legacy = _expire_legacy_hash_version(conn, season, today_str)
    if legacy:
        console.print(
            f"  [dim]Wire: expired {legacy} legacy same-day entries "
            f"(hash_version != {HASH_VERSION})[/dim]"
        )

    # Force mode: expire today's entries too so stale same-day items don't persist
    if force:
        force_expired = conn.execute(
            """
            UPDATE war_room_wire
            SET expired = TRUE
            WHERE season = ? AND expired = FALSE AND match_day = ?
            RETURNING id
            """,
            [season, today_str],
        ).fetchall()
        if force_expired:
            console.print(f"  [dim]Wire: force-expired {len(force_expired)} same-day entries[/dim]")

    # Shared ground-truth bundle used by every LLM generator in this sync
    live_ctx = build_live_context(conn, season)
    standings = live_ctx.get("standings") or []
    caps = live_ctx.get("caps")
    schedule = live_ctx.get("schedule")

    if not standings:
        console.print("  [yellow]Wire: no standings — skipping[/yellow]")
        return []

    # Set enrichment DB connection for tools that need it
    from pipeline.intel.tools import set_enrichment_conn
    set_enrichment_conn(conn)

    # Build shared base context (includes injury/availability block)
    base_context = _build_base_context(conn, season, live_ctx)

    # Drop already-completed matches so generators (esp. Preview) only see
    # fixtures that still need editorial coverage. Without this, the LLM
    # can hallucinate previews for matches that already finished today.
    live_today = [m for m in today_matches if m.status != "completed"]
    if len(live_today) != len(today_matches):
        dropped = len(today_matches) - len(live_today)
        console.print(
            f"  [dim]Wire: filtered {dropped} completed match(es) from today's fixtures[/dim]"
        )

    ctx = GeneratorContext(
        conn=conn,
        season=season,
        today_matches=live_today,
        standings=standings,
        caps=caps,
        schedule=schedule,
        base_context=base_context,
    )

    # Instantiate generators
    situation = SituationRoomGenerator()
    scout = ScoutReportGenerator()
    newsdesk = NewsDeskGenerator()
    preview = MatchdayPreviewGenerator()
    archive = TheArchiveGenerator()
    take = TheTakeGenerator()

    # Phase 1: Run first five generators in parallel
    console.print(
        "  [dim]Wire: running generators "
        "(situation, scout, newsdesk, preview, archive)…[/dim]"
    )
    phase1_results = await asyncio.gather(
        situation.generate(ctx, force=force),
        scout.generate(ctx, force=force),
        newsdesk.generate(ctx, force=force),
        preview.generate(ctx, force=force),
        archive.generate(ctx, force=force),
        return_exceptions=True,
    )

    # Collect successful results from phase 1
    all_items: list[dict] = []
    phase1_names = ["situation", "scout", "newsdesk", "preview", "archive"]
    for i, result in enumerate(phase1_results):
        if isinstance(result, Exception):
            gen_name = phase1_names[i]
            console.print(f"  [yellow]Wire/{gen_name}: failed — {result}[/yellow]")
        elif isinstance(result, list):
            all_items.extend(result)

    # Phase 2: The Take — sees other generators' output
    console.print("  [dim]Wire: running The Take…[/dim]")
    take.set_other_outputs(all_items)
    try:
        take_items = await take.generate(ctx, force=force)
        all_items.extend(take_items)
    except Exception as e:
        console.print(f"  [yellow]Wire/take: failed — {e}[/yellow]")

    # Insert all items into DB
    _insert_items(conn, all_items, season, today_str)

    total = len(all_items)
    if total:
        console.print(f"  [green]Wire: {total} total dispatches generated[/green]")
    else:
        console.print("  [yellow]Wire: no dispatches generated this cycle[/yellow]")

    return all_items


# ── Export with aggregation ─────────────────────────────────────────

_MAX_PER_TEAM = 8
_MAX_CONSECUTIVE_SAME_SOURCE = 2


_SEVERITY_ORDER = ("alarm", "alert", "signal")


def _wire_generated_at_utc_iso(value: object) -> str:
    """Serialize wire timestamps as explicit UTC ISO 8601.

    The DuckDB column is a naive TIMESTAMP. Our DuckDB sessions are
    standardized to UTC, so naive values here represent UTC wall time.
    """
    if value is None:
        return ""

    dt: datetime | None = None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace(" ", "T"))
        except ValueError:
            return value

    if dt is None:
        return str(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def export_wire_json(
    conn: duckdb.DuckDBPyConnection,
    season: str,
) -> list[dict]:
    """Export non-expired wire entries with structural aggregation.

    Rules:
    1. Severity ordering: alarm > alert > signal.
    2. Within each severity tier, non-take desks come first in a
       newsroom-front-page order (situation → newsdesk → preview → scout),
       then take dispatches last — take now synthesizes the other desks,
       so it only makes sense after the reader has seen them.
    3. Per-team cap: max _MAX_PER_TEAM entries per team, applied across
       the full sorted list so top-ranked items win the slot.
    4. Source diversity within each severity tier: no more than
       _MAX_CONSECUTIVE_SAME_SOURCE in a row. Overflow is deferred to
       the end of the current tier, not the end of the whole list.
    """
    rows = conn.execute(
        """
        SELECT headline, text, emoji, category, severity,
               teams, generated_at, match_day,
               coalesce(source, 'wire') as source
        FROM war_room_wire
        WHERE season = ? AND expired = FALSE
        ORDER BY
            CASE severity
                WHEN 'alarm' THEN 0
                WHEN 'alert' THEN 1
                ELSE 2
            END,
            CASE coalesce(source, 'wire') WHEN 'take' THEN 1 ELSE 0 END,
            CASE coalesce(source, 'wire')
                WHEN 'situation' THEN 0
                WHEN 'newsdesk'  THEN 1
                WHEN 'preview'   THEN 2
                WHEN 'scout'     THEN 3
                WHEN 'archive'   THEN 4
                ELSE 5
            END,
            generated_at DESC
        """,
        [season],
    ).fetchall()

    # Build raw entries
    raw: list[dict] = [
        {
            "headline": r[0],
            "text": r[1],
            "emoji": r[2],
            "category": r[3],
            "severity": r[4],
            "teams": r[5] or [],
            "generated_at": _wire_generated_at_utc_iso(r[6]),
            "match_day": r[7],
            "source": r[8],
        }
        for r in rows
    ]

    # Per-team cap — iterates the full sorted list so alarm/alert items
    # win the team slots over signal items.
    team_counts: dict[str, int] = {}
    capped: list[dict] = []
    for entry in raw:
        teams = entry.get("teams", [])
        if teams:
            if any(team_counts.get(t, 0) >= _MAX_PER_TEAM for t in teams):
                continue
            for t in teams:
                team_counts[t] = team_counts.get(t, 0) + 1
        capped.append(entry)

    # Group by severity so source-diversity deferrals stay inside the
    # tier they came from instead of dropping to the bottom of the wire.
    by_severity: dict[str, list[dict]] = {s: [] for s in _SEVERITY_ORDER}
    other: list[dict] = []
    for entry in capped:
        sev = entry.get("severity", "")
        (by_severity[sev] if sev in by_severity else other).append(entry)

    final: list[dict] = []
    for sev in _SEVERITY_ORDER:
        final.extend(_apply_source_diversity(by_severity[sev]))
    final.extend(_apply_source_diversity(other))

    return final


def _apply_source_diversity(items: list[dict]) -> list[dict]:
    """Break long same-source runs by deferring overflow to the end.

    Linear pass: if the current item's source matches the previous
    emitted source and we've already emitted _MAX_CONSECUTIVE_SAME_SOURCE
    in a row, push the item onto a deferred queue. The deferred queue is
    appended to the end of the returned list (caller decides whether
    that's "end of tier" or "end of wire" by how it invokes us).
    """
    out: list[dict] = []
    deferred: list[dict] = []
    consecutive_source = ""
    consecutive_count = 0
    for entry in items:
        src = entry.get("source", "wire")
        if src == consecutive_source:
            consecutive_count += 1
            if consecutive_count > _MAX_CONSECUTIVE_SAME_SOURCE:
                deferred.append(entry)
                continue
        else:
            consecutive_source = src
            consecutive_count = 1
        out.append(entry)
    out.extend(deferred)
    return out
