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

    # LLM extraction: fill scores/hero for completed matches missing them
    if matches and ctx.db_conn is not None:
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

    # Editorial match notes
    if matches:
        try:
            from pipeline.intel.match_notes import generate_match_notes

            notes = asyncio.run(generate_match_notes(ctx.season))
            if notes:
                applied = 0
                for m in matches:
                    note = notes.get(m.match_number)
                    if note:
                        m.note = note
                        applied += 1
                if applied:
                    console.print(
                        f"  [green]Schedule: {applied} editorial note(s) applied[/green]"
                    )
        except Exception as e:
            console.print(f"  [yellow]Match notes: skipped: {e}[/yellow]")

    # Live match enrichment via page crawl (before writing panel)
    live_matches = [m for m in matches if m.status == "live" and m.match_url]
    if live_matches:
        try:
            from pipeline.sources.live_crawl import (
                crawl_live_matches_sync,
                write_live_archive,
                write_live_snapshot,
            )

            results = crawl_live_matches_sync()
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
