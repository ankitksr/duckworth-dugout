"""Pipeline configuration — paths, LLM settings, HTTP config."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (won't override existing env vars)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── Paths ──────────────────────────────────────────────────────────────────

ROOT_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT_DIR / "cache"
DATA_DIR = ROOT_DIR / "data"
MANIFESTS_DIR = CACHE_DIR / "manifests"

# DuckDB paths
ENRICHMENT_DB_PATH = DATA_DIR / "enrichment.duckdb"
CRICKET_DB_PATH = Path(
    os.environ.get("CRICKET_DB_PATH", str(DATA_DIR / "cricket.duckdb"))
)

# ── Wikipedia ──────────────────────────────────────────────────────────────

WIKIPEDIA_API_BASE = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_IPL_TITLE_TEMPLATE = "{year} Indian Premier League"
WIKIPEDIA_IPL_PERSONNEL_TEMPLATE = "List of {year} Indian Premier League personnel changes"

# ── HTTP Settings ──────────────────────────────────────────────────────────

REQUEST_TIMEOUT_CONNECT = 30.0
REQUEST_TIMEOUT_READ = 60.0
REQUEST_TIMEOUT_READ_LARGE = 300.0
MAX_RETRIES = 3
BACKOFF_BASE = 1.0
BACKOFF_MAX = 30.0
JITTER_MAX = 0.5

RATE_LIMITS = {
    "en.wikipedia.org": 5.0,
}

USER_AGENTS = [
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
]

# ── IPL Season Constants ──────────────────────────────────────────────────

# Year of the most recent IPL mega auction — used as the cutoff for
# team-composition-dependent stats (phase performance, form, etc.).
# Update this when a new mega auction occurs.
MEGA_AUCTION_SEASON = "2025"

# ── LLM Settings ──────────────────────────────────────────────────────────

GEMINI_API_KEY = os.environ.get("CT_LLM_API_KEY", "")
GEMINI_MODEL = os.environ.get("CT_LLM_MODEL") or "gemini-3-flash-preview"
GEMINI_MODEL_PRO = os.environ.get("CT_LLM_MODEL_PRO") or "gemini-3.1-pro-preview"
GEMINI_VERTEX = os.environ.get("CT_LLM_VERTEX", "").lower() in ("1", "true", "yes")
GOOGLE_CLOUD_PROJECT = os.environ.get("CT_LLM_GCP_PROJECT", "")
GOOGLE_CLOUD_LOCATION = os.environ.get("CT_LLM_GCP_LOCATION", "us-central1")
LLM_RATE_LIMIT_RPM = int(os.environ.get("CT_LLM_RATE_LIMIT_RPM", "10"))
LLM_MAX_RETRIES = 2
