"""Sync context — shared state passed to every panel."""

from dataclasses import dataclass, field
from pathlib import Path

import duckdb


@dataclass
class SyncContext:
    """Shared context threaded through all panel sync functions."""

    season: str
    data_dir: Path
    public_dir: Path
    db_conn: duckdb.DuckDBPyConnection | None = None
    meta: dict = field(default_factory=dict)

    # Shared feed items (populated once, consumed by multiple panels)
    wisden_items: list | None = None
    ca_items: list | None = None
    ct_items: list | None = None
    espn_items: list | None = None

    # Cross-panel data (standings feeds downstream to schedule, pulse, etc.)
    standings_rows: list | None = None
    schedule_matches: list | None = None
    today_matches: list = field(default_factory=list)

    # Per-article extraction stats populated by sync._init_db_and_articles
    # and read by the availability panel for its payload telemetry.
    extraction_stats: dict = field(default_factory=dict)
