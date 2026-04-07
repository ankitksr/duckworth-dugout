"""Intel Log panel — aggregate IPL news from multiple RSS feeds."""

import json

from rich.console import Console

from pipeline.context import SyncContext
from pipeline.sources.intel_log import sync_intel_log
from pipeline.writer import write_json

console = Console()


def sync(ctx: SyncContext) -> None:
    """Sync the Intel Log panel."""
    items = sync_intel_log()

    # intel_log writes its own persistence file; copy to public API
    src = ctx.data_dir / "intel-log.json"
    if src.exists():
        write_json(ctx.public_dir / "intel-log.json", json.loads(src.read_text()))

    ctx.meta["intel_log"] = {
        "synced_at": _now_iso(),
        "items": len(items),
    }


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
