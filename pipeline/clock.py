"""Clock helpers for explicit UTC instants and IST product dates."""

from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

def today_ist_iso() -> str:
    """Return the current product date in IST as YYYY-MM-DD."""
    return datetime.now(IST).date().isoformat()
