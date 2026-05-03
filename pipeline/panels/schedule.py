"""Schedule panel — fixtures + completed results + live overlay.

After Cricsheet + standings overlay, runs LLM extraction to fill
scores for completed-but-scoreless matches.
"""

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone

from rich.console import Console

from pipeline.context import SyncContext
from pipeline.writer import write_panel

console = Console()


def sync(ctx: SyncContext) -> None:
    """Sync schedule. Updates ctx.schedule_matches and ctx.today_matches."""
    from pipeline.sources.schedule import sync_schedule

    # Convert standings rows to dicts for schedule overlay
    std_dicts: list[dict] | None = None
    if ctx.standings_rows:
        std_dicts = [
            asdict(r) if hasattr(r, "__dataclass_fields__") else r
            for r in ctx.standings_rows
        ]

    matches = sync_schedule(ctx.season, standings=std_dicts)

    # LLM extraction: fill scores/hero for completed matches missing them.
    # Skipped when ctx.skip_llm (live tier) or when DB isn't open.
    if matches and ctx.db_conn is not None and not ctx.skip_llm:
        try:
            from pipeline.intel.extract import (
                extract_match_results,
                patch_schedule_from_extracts,
            )

            extracts = asyncio.run(extract_match_results(ctx.db_conn, matches))
            if extracts:
                patched = patch_schedule_from_extracts(matches, extracts)
                if patched:
                    console.print(
                        f"  [green]Schedule: {patched} match(es)"
                        " patched via LLM extraction[/green]"
                    )
        except Exception as e:
            console.print(f"  [yellow]Extract: LLM extraction skipped: {e}[/yellow]")

    # Editorial match notes — read from match-notes.json on disk and
    # apply to matches[].note. The match_notes panel (cool tier) is the
    # only place that GENERATES notes via LLM; this panel just merges
    # them into the schedule output so the frontend's m.note read works.
    if matches:
        _apply_match_notes_from_disk(matches, ctx.public_dir)

    # Live match enrichment via page crawl (before writing panel).
    # Pass live matches in-memory — schedule.json on disk is still the
    # previous run's state (we write below) so a fresh promotion this
    # sync wouldn't be visible to a disk-read filter.
    live_matches = [m for m in matches if m.status == "live" and m.match_url]
    if live_matches:
        try:
            from pipeline.sources.live_crawl import (
                crawl_live_matches_sync,
                write_live_archive,
                write_live_snapshot,
            )

            live_payload = [
                {
                    "match_number": m.match_number,
                    "team1": m.team1,
                    "team2": m.team2,
                    "match_url": m.match_url,
                }
                for m in live_matches
            ]
            results = crawl_live_matches_sync(live_matches=live_payload)
            if results:
                write_live_snapshot(results)
                write_live_archive(results)
                for r in results:
                    for m in matches:
                        if m.match_number == r.match_number:
                            if r.status == "completed":
                                m.status = "completed"
                            if r.overs1:
                                m.overs1 = f"{r.overs1} ov"
                            if r.overs2:
                                m.overs2 = f"{r.overs2} ov"
                            if r.status_text:
                                m.status_text = r.status_text
                            if r.score1:
                                m.score1 = r.score1
                            if r.score2:
                                m.score2 = r.score2
                            if r.current_rr:
                                m.current_rr = r.current_rr
                            if r.required_rr:
                                m.required_rr = r.required_rr
                            if r.live_forecast:
                                m.live_forecast = r.live_forecast
                            if r.toss and not m.toss:
                                m.toss = r.toss
                            if r.batting:
                                m.batting = r.batting
        except Exception as e:
            console.print(f"  [yellow]Live crawl: {e}[/yellow]")

    # Write panel after live enrichment so final state ships
    if matches:
        data = [asdict(m) for m in matches]
        write_panel(
            "schedule", data,
            data_dir=ctx.data_dir, public_dir=ctx.public_dir,
            db_conn=ctx.db_conn, season=ctx.season,
        )

    ctx.schedule_matches = matches
    ctx.today_matches = matches  # downstream panels filter by date themselves

    completed = sum(1 for m in matches if m.status == "completed")
    live_count = sum(1 for m in matches if m.status == "live")
    ctx.meta["schedule"] = {
        "synced_at": _now_iso(),
        "fixtures": len(matches),
        "completed": completed,
        "live_matches": live_count,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _apply_match_notes_from_disk(matches: list, public_dir) -> None:
    """Merge match-notes.json (written by the match_notes panel) onto matches.

    Frontend reads m.note from schedule.json. The match_notes panel is
    the single LLM source for these notes; this helper just looks them
    up by match_number and assigns. JSON dict keys can be ints or
    strings depending on serialization, so we try both.
    """
    import json as _json
    notes_path = public_dir / "match-notes.json"
    if not notes_path.exists():
        return
    try:
        notes = _json.loads(notes_path.read_text(encoding="utf-8"))
    except (_json.JSONDecodeError, OSError):
        return

    if not isinstance(notes, dict):
        return

    applied = 0
    for m in matches:
        note = notes.get(m.match_number) or notes.get(str(m.match_number))
        if note:
            m.note = note
            applied += 1
    if applied:
        console.print(
            f"  [green]Schedule: merged {applied} match note(s) from disk[/green]"
        )
