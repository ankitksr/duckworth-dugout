"""Panel registry — tier assignments and sync ordering.

Tiers are named panel sets — they may overlap. The "live" tier is the
fast-refresh path (deterministic, no LLM, no article crawl) and is the
shortest cycle that can deploy fresh scores + standings + pulse. Warm
tier is a strict superset of live for the 4h cron, hot tier covers the
article-driven panels, cool tier is all the LLM-heavy per-match work.
"""

TIERS: dict[str, list[str]] = {
    "live": ["standings", "schedule", "pulse"],
    "hot": ["intel_log", "wire", "caps"],
    "warm": [
        "standings", "schedule", "pulse", "caps",
        "ticker", "availability", "roster", "scenarios", "records",
    ],
    "cool": ["briefing", "narratives", "dossier", "match_notes"],
}

# Execution order: live-tier panels first (their outputs feed every
# downstream LLM panel), then article ingest, then derived panels and
# LLM panels. Standings/schedule/pulse moved ahead of intel_log so wire
# / briefing / dossier always read a fresh schedule.json + standings.json
# from ctx, not the stale cached copy.
PANEL_ORDER: list[str] = [
    "standings", "schedule", "pulse",
    "intel_log",
    "caps", "availability", "roster",
    "wire", "ticker", "scenarios", "records",
    "briefing", "dossier", "narratives", "match_notes",
]


def resolve_panels(names: list[str]) -> set[str]:
    """Expand tier names + panel names into a set of panel names.

    Accepts a mixed list — "live", "warm", "standings", "pulse" — and
    returns the union. "all" is a magic preset for every panel in
    PANEL_ORDER. Unknown names raise ValueError so typos surface
    immediately instead of silently dropping panels.
    """
    if "all" in names:
        return set(PANEL_ORDER)
    panels: set[str] = set()
    for n in names:
        if n in TIERS:
            panels.update(TIERS[n])
        elif n in PANEL_ORDER:
            panels.add(n)
        else:
            raise ValueError(
                f"Unknown panel or tier: {n!r}. "
                f"Valid tiers: {list(TIERS)}. "
                f"Valid panels: {PANEL_ORDER}."
            )
    return panels
