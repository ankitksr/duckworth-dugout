"""Per-request LLM usage ledger.

Writes one row to the `llm_usage` table in enrichment.duckdb for every
LLM call (or app-layer cache hit). Best-effort: failures are logged,
never raised — a telemetry outage must not break a sync.

The `sync_id` is propagated via a ContextVar set once at the top of
`sync_panels()`, so panels don't have to thread it manually.
"""

from __future__ import annotations

import contextvars
import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

import duckdb

from pipeline.config import ENRICHMENT_DB_PATH
from pipeline.llm.pricing import PRICING_VERSION, compute_cost

log = logging.getLogger(__name__)

# Set at the top of each sync run; None outside of a sync (e.g. when
# running the `cost` CLI or standalone scripts).
_sync_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "llm_usage_sync_id", default=None,
)


def set_sync_id(value: str | None) -> None:
    """Set the active sync_id for subsequent record() calls."""
    _sync_id.set(value)


def current_sync_id() -> str | None:
    return _sync_id.get()


@dataclass
class UsageEvent:
    """One LLM call (or cache hit) worth recording.

    For multi-round `generate_with_tools` calls, tokens are the SUM
    across rounds and `tool_rounds` is the round count.
    """

    panel: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_read_tokens: int = 0
    cache_write_tokens: int = 0
    tool_rounds: int = 1
    latency_ms: int | None = None
    retries: int = 0
    success: bool = True
    error: str | None = None
    sub_key: str | None = None
    app_cache_hit: bool = False
    # Populated at record time from the ContextVar if not set here.
    sync_id: str | None = field(default=None)


_INSERT_SQL = """
INSERT INTO llm_usage (
    request_id, sync_id, panel, sub_key, provider, model,
    input_tokens, output_tokens, cached_read_tokens, cache_write_tokens,
    tool_rounds, latency_ms, retries, success, error,
    app_cache_hit, cost_usd, pricing_version
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def record(event: UsageEvent) -> None:
    """Insert one row. Never raises."""
    try:
        cost = (
            Decimal(0) if event.app_cache_hit
            else compute_cost(
                event.model,
                event.input_tokens,
                event.output_tokens,
                event.cached_read_tokens,
            )
        )
        sync_id = event.sync_id or current_sync_id()
        params = (
            uuid.uuid4().hex,
            sync_id,
            event.panel,
            event.sub_key,
            event.provider,
            event.model,
            event.input_tokens,
            event.output_tokens,
            event.cached_read_tokens,
            event.cache_write_tokens,
            event.tool_rounds,
            event.latency_ms,
            event.retries,
            event.success,
            event.error,
            event.app_cache_hit,
            str(cost),
            PRICING_VERSION,
        )
        # Short-lived connection — DuckDB allows multiple writers to the
        # same file. Skip init_db here; the sync orchestrator has
        # already run it. If the table is missing we swallow below.
        conn = duckdb.connect(str(ENRICHMENT_DB_PATH))
        try:
            conn.execute(_INSERT_SQL, params)
        finally:
            conn.close()
    except Exception as exc:
        log.warning("llm_usage ledger write failed: %s", exc)
