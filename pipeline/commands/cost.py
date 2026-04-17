"""`pipeline cost` — summary of LLM spend from the llm_usage ledger.

Queries enrichment.duckdb and prints a rich table. Read-only; no side effects.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import click
import duckdb
from rich.console import Console
from rich.table import Table

from pipeline.config import ENRICHMENT_DB_PATH
from pipeline.db.connection import get_connection

console = Console()

_GROUPING = {
    "panel": "panel",
    "model": "model",
    "day":   "CAST(ts AS DATE)",
    "sync":  "sync_id",
}


@click.command("cost")
@click.option("--days", type=int, default=7, help="Window in days (ignored if --start given)")
@click.option("--start", type=str, default=None, help="Start date YYYY-MM-DD (inclusive)")
@click.option("--end",   type=str, default=None, help="End date YYYY-MM-DD (inclusive)")
@click.option(
    "--by", "group_by", type=click.Choice(list(_GROUPING)), default="panel",
    help="Group rows by this dimension",
)
@click.option("--panel", type=str, default=None, help="Filter to a single panel name")
@click.option("--model", type=str, default=None, help="Filter to a single model name")
def cost_report(
    days: int,
    start: str | None,
    end: str | None,
    group_by: str,
    panel: str | None,
    model: str | None,
) -> None:
    """Summarize LLM spend over a time window."""
    if not ENRICHMENT_DB_PATH.exists():
        console.print("[yellow]No enrichment.duckdb yet — run a sync first.[/yellow]")
        return

    start_dt, end_dt = _resolve_window(days=days, start=start, end=end)

    # get_connection() ensures init_db has applied the schema, so
    # selecting from llm_usage is safe even on a clean install.
    conn = get_connection()
    try:
        totals = _fetch_totals(conn, start_dt, end_dt, panel=panel, model=model)
        if totals["calls"] == 0 and totals["cache_hits"] == 0:
            console.print(
                f"[dim]No llm_usage rows in "
                f"[{start_dt.date()} .. {end_dt.date()}][/dim]"
            )
            return

        _print_header(start_dt, end_dt, totals, panel=panel, model=model)
        rows = _fetch_breakdown(conn, start_dt, end_dt, group_by, panel=panel, model=model)
        _print_breakdown(group_by, rows)
    finally:
        conn.close()


def _resolve_window(
    *, days: int, start: str | None, end: str | None,
) -> tuple[datetime, datetime]:
    """Inclusive [start, end] window. Defaults to last `days` days."""
    if start is not None:
        start_dt = datetime.combine(_parse_date(start), datetime.min.time())
    else:
        start_dt = datetime.combine(
            date.today() - timedelta(days=days - 1),
            datetime.min.time(),
        )

    if end is not None:
        end_dt = datetime.combine(_parse_date(end), datetime.max.time())
    else:
        end_dt = datetime.combine(date.today(), datetime.max.time())

    return start_dt, end_dt


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _where(panel: str | None, model: str | None) -> tuple[str, list]:
    clauses = ["ts BETWEEN ? AND ?"]
    params: list = []
    if panel:
        clauses.append("panel = ?")
        params.append(panel)
    if model:
        clauses.append("model = ?")
        params.append(model)
    return " AND ".join(clauses), params


def _fetch_totals(
    conn: duckdb.DuckDBPyConnection,
    start_dt: datetime,
    end_dt: datetime,
    *,
    panel: str | None,
    model: str | None,
) -> dict:
    where, extra = _where(panel, model)
    params = [start_dt, end_dt, *extra]
    row = conn.execute(f"""
        SELECT
            COUNT(*) FILTER (WHERE NOT app_cache_hit) AS calls,
            COUNT(*) FILTER (WHERE app_cache_hit)      AS cache_hits,
            COUNT(*) FILTER (WHERE NOT success)        AS failures,
            COALESCE(SUM(input_tokens), 0)             AS input_tokens,
            COALESCE(SUM(output_tokens), 0)            AS output_tokens,
            COALESCE(SUM(cost_usd), 0)                 AS cost_usd
        FROM llm_usage
        WHERE {where}
    """, params).fetchone()

    calls, cache_hits, failures, in_tok, out_tok, cost = row
    total = calls + cache_hits
    return {
        "calls":         calls,
        "cache_hits":    cache_hits,
        "failures":      failures,
        "input_tokens":  int(in_tok),
        "output_tokens": int(out_tok),
        "cost_usd":      float(cost),
        "hit_rate":      (cache_hits / total) if total else 0.0,
    }


def _fetch_breakdown(
    conn: duckdb.DuckDBPyConnection,
    start_dt: datetime,
    end_dt: datetime,
    group_by: str,
    *,
    panel: str | None,
    model: str | None,
) -> list[tuple]:
    col = _GROUPING[group_by]
    where, extra = _where(panel, model)
    params = [start_dt, end_dt, *extra]
    return conn.execute(f"""
        SELECT
            {col}                                         AS bucket,
            COUNT(*) FILTER (WHERE NOT app_cache_hit)     AS calls,
            COUNT(*) FILTER (WHERE app_cache_hit)         AS cache_hits,
            COALESCE(SUM(input_tokens), 0)                AS in_tok,
            COALESCE(SUM(output_tokens), 0)               AS out_tok,
            COALESCE(SUM(cost_usd), 0)                    AS cost
        FROM llm_usage
        WHERE {where}
        GROUP BY bucket
        ORDER BY cost DESC
    """, params).fetchall()


def _print_header(
    start_dt: datetime,
    end_dt: datetime,
    totals: dict,
    *,
    panel: str | None,
    model: str | None,
) -> None:
    window = f"{start_dt.date()} → {end_dt.date()}"
    filters = []
    if panel:
        filters.append(f"panel={panel}")
    if model:
        filters.append(f"model={model}")
    filter_str = f" [{', '.join(filters)}]" if filters else ""

    console.print()
    console.print(
        f"[bold]LLM spend[/bold]  [dim]{window}{filter_str}[/dim]"
    )
    console.print(
        f"  total calls : {totals['calls']}"
        f"    cache hits: {totals['cache_hits']}"
        f"  ({totals['hit_rate']:.0%})"
        f"    failures: {totals['failures']}"
    )
    console.print(
        f"  input tokens: {totals['input_tokens']:>12,}"
        f"    output tokens: {totals['output_tokens']:>12,}"
    )
    console.print(
        f"  [bold green]cost (USD)  : ${totals['cost_usd']:.4f}[/bold green]"
    )


def _print_breakdown(group_by: str, rows: list[tuple]) -> None:
    table = Table(show_header=True, header_style="bold", border_style="bright_black")
    table.add_column(group_by, style="cyan")
    table.add_column("calls",     justify="right")
    table.add_column("hits",      justify="right", style="dim")
    table.add_column("input",     justify="right")
    table.add_column("output",    justify="right")
    table.add_column("cost (USD)", justify="right", style="green")
    table.add_column("$/call",    justify="right", style="dim")

    for bucket, calls, hits, in_tok, out_tok, cost in rows:
        per_call = (float(cost) / calls) if calls else 0.0
        table.add_row(
            str(bucket),
            f"{calls}",
            f"{hits}",
            f"{int(in_tok):,}",
            f"{int(out_tok):,}",
            f"${float(cost):.4f}",
            f"${per_call:.4f}" if calls else "—",
        )

    console.print()
    console.print(table)
