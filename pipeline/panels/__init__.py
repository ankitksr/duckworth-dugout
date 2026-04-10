"""Panel registry — tier assignments and sync ordering."""

TIERS: dict[str, list[str]] = {
    "hot": ["intel_log", "wire"],
    "warm": ["standings", "caps", "schedule", "ticker", "pulse", "availability"],
    "cool": ["scenarios", "records", "briefing", "narratives",
             "dossier", "match_notes"],
}

# availability runs in warm tier (when articles get ingested via
# _init_db_and_articles) but lives BEFORE wire in PANEL_ORDER so that on
# combined runs (hot+warm+cool, e.g. the 6x-daily CI cron), wire's roster
# context sees the freshly extracted availability state. On hot-only runs,
# availability is skipped and wire reads whatever events are already in the
# DB from the most recent warm cycle.
PANEL_ORDER: list[str] = [
    "intel_log", "availability", "standings", "caps", "schedule", "pulse",
    "wire", "ticker", "scenarios", "records", "briefing",
    "narratives", "dossier", "match_notes",
]


def resolve_panels(tiers: list[str]) -> set[str]:
    """Expand tier names (or 'all') into a set of panel names."""
    if "all" in tiers:
        return set(PANEL_ORDER)
    panels: set[str] = set()
    for tier in tiers:
        panels.update(TIERS.get(tier, []))
    return panels
