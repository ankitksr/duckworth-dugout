"""War Room snapshot persistence — versioned panel data in DuckDB.

Each panel's JSON output is snapshotted on change. Duplicate data
(same context_hash) is skipped, so repeated syncs without new match
results produce zero new rows.

Usage:
    from pipeline.snapshots import maybe_snapshot
    maybe_snapshot(conn, "standings", data, "2026")
"""

import hashlib
import json
from typing import Any

import duckdb
from rich.console import Console

console = Console()


def _payload_hash(data: Any) -> str:
    """Deterministic hash of JSON-serializable data."""
    content = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode()).hexdigest()[:24]


def maybe_snapshot(
    conn: duckdb.DuckDBPyConnection,
    panel: str,
    data: Any,
    season: str,
) -> bool:
    """Insert a snapshot row only if panel data has changed.

    Compares the hash of the new payload against the most recent
    snapshot for this panel+season. Skips if identical.

    Returns True if a new snapshot was inserted.
    """
    h = _payload_hash(data)

    last = conn.execute(
        """
        SELECT context_hash FROM war_room_snapshots
        WHERE panel = ? AND season = ?
        ORDER BY snapshot_at DESC
        LIMIT 1
        """,
        [panel, season],
    ).fetchone()

    if last and last[0] == h:
        return False

    # Generate next ID (DuckDB doesn't auto-increment INTEGER PKs)
    row = conn.execute(
        "SELECT coalesce(max(id), 0) + 1 FROM war_room_snapshots"
    ).fetchone()
    next_id = row[0] if row else 1

    conn.execute(
        """
        INSERT INTO war_room_snapshots (id, panel, payload, context_hash, season)
        VALUES (?, ?, ?::JSON, ?, ?)
        """,
        [next_id, panel, json.dumps(data, ensure_ascii=False), h, season],
    )
    return True
