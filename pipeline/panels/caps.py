"""Cap Race panel — Orange/Purple Cap leaderboards.

Orange/Purple cascade: Wisden → CricketAddictor → ESPNcricinfo → Wikipedia → Cricsheet.
SR/Economy: ESPNcricinfo → Cricsheet.
MVP: ESPNcricinfo → Wikipedia.
"""

from dataclasses import asdict
from datetime import datetime, timezone

from rich.console import Console

from pipeline.context import SyncContext
from pipeline.writer import write_panel

console = Console()


def sync(ctx: SyncContext) -> None:
    """Sync cap race data."""
    from pipeline.sources.caps import caps_from_cricsheet, parse_caps, parse_caps_from_feed

    source = "wisden"
    caps = parse_caps(ctx.wisden_items or [])

    if not caps.orange_cap and not caps.purple_cap:
        source = "cricketaddictor"
        caps = parse_caps_from_feed(ctx.ca_items or [], source_name="CricketAddictor")

    # ESPNcricinfo: primary source for SR, Economy, MVP; fallback for Orange/Purple
    espn_caps = None
    try:
        from pipeline.sources.caps import caps_from_espncricinfo

        espn_caps = caps_from_espncricinfo(ctx.season)
    except Exception as e:
        console.print(f"  [yellow]ESPNcricinfo caps: {e}[/yellow]")

    # Backfill orange/purple from ESPNcricinfo if RSS sources missed them
    if espn_caps:
        if not caps.orange_cap and espn_caps.orange_cap:
            caps.orange_cap = espn_caps.orange_cap
            source = "espncricinfo"
        if not caps.purple_cap and espn_caps.purple_cap:
            caps.purple_cap = espn_caps.purple_cap

    # Wikipedia: fallback for orange/purple + MVP
    wiki_caps = None
    if not caps.orange_cap or not caps.purple_cap or not (espn_caps and espn_caps.mvp):
        try:
            from pipeline.sources.wikipedia import fetch_wikipedia_caps

            wiki_caps = fetch_wikipedia_caps(ctx.season)
            if wiki_caps:
                if not caps.orange_cap and wiki_caps.orange_cap:
                    caps.orange_cap = wiki_caps.orange_cap
                    source = "wikipedia"
                if not caps.purple_cap and wiki_caps.purple_cap:
                    caps.purple_cap = wiki_caps.purple_cap
        except Exception as e:
            console.print(f"  [yellow]Wikipedia caps: {e}[/yellow]")

    # SR and Economy: ESPNcricinfo (primary) → Cricsheet (fallback)
    cs_caps = None
    if espn_caps and espn_caps.best_sr:
        caps.best_sr = espn_caps.best_sr
        sr_source = "ESPNcricinfo"
    else:
        cs_caps = caps_from_cricsheet(ctx.season)
        caps.best_sr = cs_caps.best_sr
        sr_source = "Cricsheet"

    if espn_caps and espn_caps.best_econ:
        caps.best_econ = espn_caps.best_econ
        econ_source = "ESPNcricinfo"
    else:
        if not cs_caps:
            cs_caps = caps_from_cricsheet(ctx.season)
        caps.best_econ = cs_caps.best_econ
        econ_source = "Cricsheet"

    # MVP: ESPNcricinfo (primary) → Wikipedia (fallback)
    if espn_caps and espn_caps.mvp:
        caps.mvp = espn_caps.mvp
        mvp_source = "ESPNcricinfo"
    elif wiki_caps and wiki_caps.mvp:
        caps.mvp = wiki_caps.mvp
        mvp_source = "Wikipedia"
    else:
        mvp_source = "none"

    # Final fallback for orange/purple: Cricsheet
    if not caps.orange_cap or not caps.purple_cap:
        if not cs_caps:
            cs_caps = caps_from_cricsheet(ctx.season)
        if not caps.orange_cap:
            caps.orange_cap = cs_caps.orange_cap
            source = "cricsheet_fallback"
        if not caps.purple_cap:
            caps.purple_cap = cs_caps.purple_cap

    if not caps.updated:
        caps.updated = _now_iso()

    has_data = caps.orange_cap or caps.purple_cap or caps.best_sr or caps.best_econ
    if has_data:
        data = asdict(caps)

        # Per-category source info for frontend display
        now = _now_iso()
        rss_label = "Wisden" if source == "wisden" else (
            "CricketAddictor" if source == "cricketaddictor" else (
                "ESPNcricinfo" if source == "espncricinfo" else "Wikipedia"
            )
        )
        rss_time = caps.updated or now
        data["sources"] = {
            "orange": {"via": rss_label, "updated": rss_time},
            "purple": {"via": rss_label, "updated": rss_time},
            "mvp": {"via": mvp_source, "updated": now},
            "sr": {"via": sr_source, "updated": now},
            "econ": {"via": econ_source, "updated": now},
        }

        write_panel(
            "caps", data,
            data_dir=ctx.data_dir, public_dir=ctx.public_dir,
            db_conn=ctx.db_conn, season=ctx.season,
        )
        ctx.meta["caps"] = {
            "synced_at": now,
            "orange": len(caps.orange_cap),
            "purple": len(caps.purple_cap),
            "best_sr": len(caps.best_sr),
            "best_econ": len(caps.best_econ),
            "source": source,
        }
    else:
        ctx.meta["caps"] = {
            "synced_at": _now_iso(),
            "orange": 0,
            "purple": 0,
            "error": "no_data",
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
