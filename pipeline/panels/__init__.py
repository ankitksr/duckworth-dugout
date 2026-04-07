"""Panel registry — tier assignments and sync ordering."""

TIERS: dict[str, list[str]] = {
    "hot": ["intel_log", "wire"],
    "warm": ["standings", "caps", "schedule", "ticker", "pulse"],
    "cool": ["scenarios", "records", "briefing", "narratives",
             "dossier", "match_notes"],
}

PANEL_ORDER: list[str] = [
    "intel_log", "standings", "caps", "schedule", "pulse",
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
