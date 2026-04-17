"""Live context — one ground-truth bundle shared across all LLM generators.

Every LLM generator in the Dugout pipeline needs the same baseline facts:
who's injured, where the table stands, what the other desks have already
filed today, how each team's rank is trending. Before this module each
generator loaded JSON files on its own, and several didn't bother — which
is how we ended up with fabricated injury claims in the wire and ticker.

`build_live_context` loads every JSON the LLM generators might want,
bundles it into a single dict, and (as a debugging artifact) writes it to
`data/war-room/live-context.json` so anyone can see exactly what the model
was looking at for a given sync.

The `format_*` helpers render the most commonly used sub-blocks as the
plain-text strings that go into prompts. Each generator imports what it
needs — no more ad-hoc `_load_json("availability.json")` calls scattered
across six files.

Usage:
    from pipeline.intel.live_context import (
        build_live_context,
        format_availability_block,
        format_wire_recent_block,
    )

    ctx = build_live_context(conn, season)
    availability_text = format_availability_block(ctx)
    wire_text = format_wire_recent_block(ctx)
"""

from __future__ import annotations

import json
from typing import Any

import duckdb

from pipeline.clock import today_ist_iso
from pipeline.config import DATA_DIR
from pipeline.ipl.franchise_metadata import IPL_FRANCHISES

_SHORT = {
    fid: d["short_name"]
    for fid, d in IPL_FRANCHISES.items()
    if not d.get("defunct")
}

_LIVE_CONTEXT_FILE = "live-context.json"


def _load_json(filename: str) -> Any:
    path = DATA_DIR / "war-room" / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _short(fid: str) -> str:
    return _SHORT.get(fid, fid.upper())


def _recent_wire_items(
    conn: duckdb.DuckDBPyConnection,
    season: str,
    limit: int = 30,
) -> list[dict]:
    """Pull recent non-expired wire dispatches for cross-desk grounding.

    Used by briefing/dossier/match_notes so they can see what the other
    desks have been filing today.
    """
    try:
        rows = conn.execute(
            """
            SELECT source, category, headline, text, teams, severity, match_day
            FROM war_room_wire
            WHERE season = ? AND expired = FALSE
            ORDER BY generated_at DESC
            LIMIT ?
            """,
            [season, limit],
        ).fetchall()
    except Exception:
        return []
    return [
        {
            "source": r[0],
            "category": r[1],
            "headline": r[2],
            "text": r[3],
            "teams": r[4] or [],
            "severity": r[5],
            "match_day": r[6],
        }
        for r in rows
    ]


def build_live_context(
    conn: duckdb.DuckDBPyConnection | None,
    season: str,
    *,
    write_debug: bool = True,
) -> dict:
    """Build the shared ground-truth bundle for all LLM generators.

    Pure aggregator: every field pulls from JSON already written by the
    sync pipeline (or from the wire DB for wire_recent). Safe to call
    repeatedly — cheap, idempotent, no LLM calls.

    If `write_debug` is True, also writes the bundle to
    `data/war-room/live-context.json` so the exact snapshot the LLMs saw
    can be inspected after the fact.
    """
    today = today_ist_iso()
    standings = _load_json("standings.json") or []
    schedule = _load_json("schedule.json") or []
    caps = _load_json("caps.json")
    availability = _load_json("availability.json")
    pulse = _load_json("pulse.json") or []
    scenarios = _load_json("scenarios.json")
    records = _load_json("records.json")
    live_match = _load_json("live-match.json")

    today_matches = [
        m for m in schedule if m.get("date") == today
    ]

    wire_recent: list[dict] = []
    if conn is not None:
        wire_recent = _recent_wire_items(conn, season)

    ctx: dict[str, Any] = {
        "today_ist": today,
        "season": season,
        "standings": standings,
        "schedule": schedule,
        "today_matches": today_matches,
        "caps": caps,
        "availability": availability,
        "pulse": pulse,
        "scenarios": scenarios,
        "records": records,
        "live_match": live_match,
        "wire_recent": wire_recent,
    }

    if write_debug:
        try:
            path = DATA_DIR / "war-room" / _LIVE_CONTEXT_FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(ctx, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass

    return ctx


# ── Prompt block formatters ─────────────────────────────────────────
#
# Each returns a prompt-ready string. Empty string if the input is
# missing so the caller can drop the block with a simple `if`.


def format_availability_block(ctx: dict) -> str:
    """Render availability.json as the verified-facts injury block.

    All LLM generators that discuss players embed this. The wording is
    deliberately blunt — the model has a strong prior (stale training
    data) to overcome, so the rule can't be subtle.
    """
    # Always emit the block — even when empty — so the LLM can tell the
    # difference between "no unavailable players" and "block was truncated."
    # Silence would implicitly license the fabricated-injury failure mode.
    empty_sentinel = (
        "INJURY/AVAILABILITY: none confirmed this sync — every squad member "
        "is available. Do not invent absences."
    )
    availability = ctx.get("availability")
    if not availability:
        return empty_sentinel
    by_team = availability.get("by_team") or {}
    lines: list[str] = []
    for fid, entries in by_team.items():
        for e in entries:
            player = (e.get("player") or "").strip()
            status = (e.get("status") or "").strip()
            reason = (e.get("reason") or "").strip()
            if not player or not status:
                continue
            tail = f" — {reason}" if reason else ""
            lines.append(f"  {player} ({_short(fid)}, {status}){tail}")
    if not lines:
        return empty_sentinel
    return (
        "INJURY/AVAILABILITY (the ONLY verified facts — do not invent any "
        "other player as injured, doubtful, missing, or unavailable):\n"
        + "\n".join(lines)
    )


def format_wire_recent_block(
    ctx: dict,
    *,
    limit: int = 15,
    exclude_sources: tuple[str, ...] = (),
) -> str:
    """Compact list of the N most recent non-expired wire dispatches.

    Cross-desk grounding for briefing/dossier/match_notes. Only includes
    headline + 1-line summary so the prompt doesn't bloat.
    """
    items = [
        w for w in ctx.get("wire_recent") or []
        if w.get("source") not in exclude_sources
    ][:limit]
    if not items:
        return ""
    lines = [
        f"  [{w['source']}:{w.get('category', '?')}] "
        f"{w['headline']} — {(w.get('text') or '')[:140]}"
        for w in items
    ]
    return "WIRE — what the AI desks have filed today:\n" + "\n".join(lines)


def format_pulse_block(ctx: dict) -> str:
    """Per-team rank trajectory line.

    Pulse is authoritative for rank movement — narrative should read it
    directly instead of re-deriving from standings. The data shape is a
    list of team objects each with a `snapshots` list carrying per-match
    `{match, rank, points, nrr, result}` entries.
    """
    pulse = ctx.get("pulse") or []
    if not pulse:
        return ""
    lines: list[str] = []
    for team in pulse:
        short = team.get("short") or team.get("fid", "?").upper()
        snapshots = team.get("snapshots") or []
        ranks = [s.get("rank") for s in snapshots if s.get("rank") is not None]
        if not ranks:
            continue
        first, last = ranks[0], ranks[-1]
        delta = first - last  # positive = improved (lower rank number)
        direction = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
        results = "".join(s.get("result", "?") for s in snapshots)
        arrow = "→".join(str(r) for r in ranks)
        lines.append(
            f"  {short}: ranks {arrow} {direction}{abs(delta)} | form {results}"
        )
    if not lines:
        return ""
    return (
        "RANK TRAJECTORY (per-team rank over time, lower=better; form = W/L per match):\n"
        + "\n".join(lines)
    )


def format_cap_race_block(ctx: dict, *, per_cap: int = 3) -> str:
    """Compact cap race leaders — orange + purple."""
    caps = ctx.get("caps") or {}
    parts: list[str] = []
    for key, label in (("orange_cap", "ORANGE CAP"), ("purple_cap", "PURPLE CAP")):
        entries = (caps.get(key) or [])[:per_cap]
        if not entries:
            continue
        line = ", ".join(
            f"{e.get('player', '?')} ({e.get('team_short', '?')}) "
            f"{e.get('stat', '')}"
            for e in entries
        )
        parts.append(f"{label}: {line}")
    return "\n".join(parts)


def format_scenarios_summary(ctx: dict) -> str:
    """One-paragraph playoff picture for cross-generator grounding.

    Used by briefing/dossier so the tactical brief reflects the stakes:
    a mid-table 4-4 team plays differently when one loss eliminates them.
    """
    scenarios = ctx.get("scenarios") or {}
    brief = (scenarios.get("situation_brief") or "").strip()
    elim = scenarios.get("elimination_watch") or []
    parts: list[str] = []
    if brief:
        parts.append(f"PLAYOFF PICTURE: {brief}")
    if elim:
        lines = [
            f"  {e.get('team', '?')} ({e.get('risk', '?')}): "
            f"{e.get('insight', '')}"
            for e in elim[:6]
        ]
        parts.append("ELIMINATION WATCH:\n" + "\n".join(lines))
    return "\n\n".join(parts)


def format_standings_block(ctx: dict) -> str:
    """Compact one-line-per-team standings snapshot."""
    standings = ctx.get("standings") or []
    if not standings:
        return ""
    lines = [
        f"  {s['position']}. {s['short_name']}"
        f" P={s['played']} W={s['wins']} L={s['losses']}"
        f" NRR={s['nrr']} Pts={s.get('points', '?')}"
        for s in standings
    ]
    return "STANDINGS:\n" + "\n".join(lines)
