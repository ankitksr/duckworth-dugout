"""Ticker panel — scrolling intel items.

LLM-powered smart ticker with static fallback.
Merges imminent milestones from records.json.
"""

import asyncio
import json
import re as _re
from dataclasses import asdict
from datetime import datetime, timezone

from rich.console import Console

from pipeline.clock import today_ist_iso
from pipeline.context import SyncContext
from pipeline.writer import write_panel

console = Console()


def sync(ctx: SyncContext) -> None:
    """Sync the Ticker panel."""
    today_str = today_ist_iso()
    today_only = [
        m for m in ctx.today_matches
        if m.date == today_str
    ] if ctx.today_matches else []

    items = []

    # Try smart ticker (LLM-powered)
    try:
        from pipeline.intel.smart_ticker import generate_smart_ticker

        items = asyncio.run(generate_smart_ticker(ctx.season, today_only))
    except Exception as e:
        console.print(f"  [yellow]Smart ticker skipped: {e}[/yellow]")

    # Fallback to static ticker
    if not items:
        from pipeline.sources.ticker import generate_ticker_items

        items = generate_ticker_items(today_only, ctx.season)

    if items:
        data = [asdict(i) for i in items]
        merged = _merge_milestone_ticker(data, ctx.data_dir)
        write_panel(
            "ticker", merged,
            data_dir=ctx.data_dir, public_dir=ctx.public_dir,
            db_conn=ctx.db_conn, season=ctx.season,
        )
        items_count = len(merged)
    else:
        items_count = 0

    ctx.meta["ticker"] = {"synced_at": _now_iso(), "items": items_count}


# ── Milestone merger ──────────────────────────────────────────────────────


def _parse_stat_value(stat_str: str) -> tuple[int | None, str]:
    m = _re.match(r"(\d[\d,]*)\s+(.+)", stat_str.strip())
    if not m:
        return None, ""
    val = int(m.group(1).replace(",", ""))
    unit = m.group(2).strip().rstrip("s")
    return val, unit


def _milestone_to_ticker_text(entry: dict) -> str | None:
    player = entry.get("player", "")
    current_str = entry.get("current", "")
    target_str = entry.get("target", "")

    if not player or not target_str:
        return None

    cur_val, cur_unit = _parse_stat_value(current_str)
    tgt_val, tgt_unit = _parse_stat_value(target_str)

    if cur_val is not None and tgt_val is not None and tgt_val > cur_val:
        delta = tgt_val - cur_val
        unit = tgt_unit or cur_unit
        unit_display = unit if delta == 1 else unit + "s"
        text = (
            f"{player} needs {delta} {unit_display}"
            f" to reach {tgt_val:,} career IPL {tgt_unit + 's'}"
        )
    else:
        note = entry.get("note", "")
        text = f"{player}: {note}" if note else f"{player} approaching {target_str}"

    return text[:100] if len(text) <= 100 else text[:97] + "..."


def _merge_milestone_ticker(ticker_data: list[dict], data_dir) -> list[dict]:
    from pathlib import Path

    records_path = Path(data_dir) / "records.json"
    if not records_path.exists():
        return ticker_data

    try:
        records = json.loads(records_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ticker_data

    imminent = records.get("imminent", [])
    if not imminent:
        return ticker_data

    existing_texts = {
        item["text"].lower()
        for item in ticker_data
        if item.get("category") == "MILESTONE"
    }

    added = 0
    for entry in imminent:
        text = _milestone_to_ticker_text(entry)
        if not text or text.lower() in existing_texts:
            continue
        player = entry.get("player", "").lower()
        target_str = entry.get("target", "").lower()
        already_covered = any(
            player in t and target_str.split()[0] in t
            for t in existing_texts
        )
        if already_covered:
            continue

        ticker_data.append({"category": "MILESTONE", "text": text})
        existing_texts.add(text.lower())
        added += 1

    if added:
        console.print(
            f"  [green]Ticker: merged {added} imminent milestone(s) from records[/green]"
        )
    return ticker_data


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
