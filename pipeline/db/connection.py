"""DuckDB connection management with ATTACH for cricket.duckdb.

Architecture:
  - enrichment.duckdb (local) — war room editorial data (articles, wire, snapshots)
  - cricket.duckdb (external, READ_ONLY) — Cricsheet facts from duckworth-mcp
"""

from pathlib import Path

import duckdb

from pipeline.config import CRICKET_DB_PATH, ENRICHMENT_DB_PATH

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection() -> duckdb.DuckDBPyConnection:
    """Get a DuckDB connection to the enrichment DB with cricket.duckdb attached."""
    ENRICHMENT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(ENRICHMENT_DB_PATH))
    _attach_cricket_db(conn)
    init_db(conn)
    return conn


def init_db(conn: duckdb.DuckDBPyConnection) -> None:
    """Apply war-room schema (idempotent)."""
    if not _SCHEMA_PATH.exists():
        return
    schema_sql = _SCHEMA_PATH.read_text()
    for statement in schema_sql.split(";"):
        lines = [ln for ln in statement.splitlines() if not ln.strip().startswith("--")]
        cleaned = "\n".join(lines).strip()
        if cleaned:
            conn.execute(cleaned)


def _attach_cricket_db(conn: duckdb.DuckDBPyConnection) -> None:
    """Attach duckworth-mcp's cricket.duckdb as read-only."""
    if not CRICKET_DB_PATH.exists():
        return  # cricket.duckdb is optional; warm+ panels handle its absence
    attached = conn.execute(
        "SELECT database_name FROM duckdb_databases() WHERE database_name = 'cricket'"
    ).fetchone()
    if not attached:
        conn.execute(f"ATTACH '{CRICKET_DB_PATH}' AS cricket (READ_ONLY)")


def preflight_check(conn: duckdb.DuckDBPyConnection) -> int:
    """Verify cricket.duckdb is attached and readable. Returns match count."""
    count = conn.execute("SELECT COUNT(*) FROM cricket.matches").fetchone()[0]
    return count
