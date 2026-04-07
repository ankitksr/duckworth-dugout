"""Feed registry and team detection utilities for the War Room."""

import re

from pipeline.ipl.franchise_metadata import IPL_FRANCHISES

# ── Feed Registry ────────────────────────────────────────────────────────

FEEDS: dict[str, dict[str, str]] = {
    "espncricinfo": {
        "name": "ESPNcricinfo",
        "url": "https://www.espncricinfo.com/rss/content/story/feeds/0.xml",
    },
    "livescores": {
        "name": "Live Scores",
        "url": "https://static.cricinfo.com/rss/livescores.xml",
    },
    "wisden": {
        "name": "Wisden",
        "url": "https://www.wisden.com/feed",
    },
    "crictracker": {
        "name": "CricTracker",
        "url": "https://www.crictracker.com/feed/",
    },
    "cricketaddictor": {
        "name": "CricketAddictor",
        "url": "https://cricketaddictor.com/feed/",
    },
    "reddit": {
        "name": "Reddit r/Cricket",
        "url": "https://www.reddit.com/r/Cricket/search.rss?q=IPL&restrict_sr=1&sort=new",
    },
}

# Feeds used for Intel Log
INTEL_LOG_FEEDS = ["espncricinfo", "crictracker", "cricketaddictor", "reddit"]

# ── Team Detection ───────────────────────────────────────────────────────

# Build lookup: lowercased name/abbreviation → franchise ID
# Only include current (non-defunct) franchises
_TEAM_LOOKUP: dict[str, str] = {}
for _fid, _fdata in IPL_FRANCHISES.items():
    if _fdata.get("defunct"):
        continue
    # Full names (including historical — "Delhi Daredevils" → "dc")
    for _name in _fdata["cricsheet_names"]:
        _TEAM_LOOKUP[_name.lower()] = _fid
    # Short name: "CSK" → "csk"
    _TEAM_LOOKUP[_fdata["short_name"].lower()] = _fid

# Sort by length descending so longer names match first
# ("Chennai Super Kings" before "CSK", "Punjab Kings" before "Kings")
_TEAM_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE), fid)
    for name, fid in sorted(_TEAM_LOOKUP.items(), key=lambda x: -len(x[0]))
]

# IPL detection keywords
_IPL_KEYWORDS_RE = re.compile(
    r"\b(IPL|Indian Premier League)\b", re.IGNORECASE
)


def detect_teams(text: str) -> list[str]:
    """Detect IPL franchise IDs mentioned in text.

    Returns deduplicated list of franchise IDs, ordered by first appearance.
    """
    seen: set[str] = set()
    result: list[str] = []
    for pattern, fid in _TEAM_PATTERNS:
        if fid not in seen and pattern.search(text):
            seen.add(fid)
            result.append(fid)
    return result


def is_ipl_item(text: str) -> bool:
    """Check whether text relates to IPL.

    True if it mentions "IPL" / "Indian Premier League" or at least
    two known IPL franchise names.
    """
    if _IPL_KEYWORDS_RE.search(text):
        return True
    return len(detect_teams(text)) >= 2
