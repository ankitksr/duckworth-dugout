"""Panel registry — tier assignments and sync ordering."""

TIERS: dict[str, list[str]] = {
    "hot": ["intel_log", "wire"],
    "warm": ["standings", "caps", "schedule", "ticker", "pulse", "availability", "roster"],
    "cool": ["scenarios", "records", "briefing", "narratives",
             "dossier", "match_notes"],
}

# availability is a warm-tier read-side panel: the per-article extraction
# that populates availability events now runs upstream in
# sync._init_db_and_articles on every tier (including hot), so the wire's
# newsdesk generator always sees freshly-extracted articles regardless of
# which tier is active. availability still lives before wire in PANEL_ORDER
# so its derived state is current when downstream panels read it.
#
# roster sits next to availability — both are pure read-side warm panels
# that emit JSON for the frontend (squad list and current injury state).
PANEL_ORDER: list[str] = [
    "intel_log", "availability", "roster", "standings", "caps", "schedule",
    "pulse", "wire", "ticker", "scenarios", "records", "briefing",
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
