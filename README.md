# Duckworth Dugout

IPL season command center — live standings, match timelines, cap races, AI-powered intel, and season pulse in a single-screen dashboard.

**[Live site](https://ankitksr.github.io/duckworth-dugout)**

## Panels

| Panel | What it shows |
|-------|---------------|
| **Standings** | Points table with W/L/NRR, playoff qualification line |
| **Match Timeline** | Completed, live & upcoming fixtures with scores and hero performances |
| **Season Pulse** | River chart of every team's rank trajectory across the season |
| **Cap Race** | Orange Cap, Purple Cap, strike rate, economy & MVP leaderboards |
| **AI Wire** | LLM-generated editorial signals — scenarios, records, match briefings |
| **Intel Feed** | Aggregated cricket news from ESPNcricinfo, Wisden, CricketAddictor |
| **Briefing & Dossier** | Pre-match tactical analysis with H2H, venue stats & threat assessment |
| **Narratives** | Per-team season arc — form, momentum, storylines |
| **Ticker** | Scrolling factual highlights with category tags |

## Tech stack

| Layer | Tech |
|-------|------|
| Frontend | [Astro](https://astro.build) + React 19 — static site with interactive islands |
| Pipeline | Python 3.12+, DuckDB, Pydantic, Click |
| LLM | Google Gemini (flash + pro) via `google-genai` |
| Data | [Cricsheet](https://cricsheet.org) ball-by-ball data, ESPNcricinfo / Wisden / CricketAddictor RSS |
| Deployment | GitHub Pages (static build on push to `main`) |

## Prerequisites

- **Python** >= 3.12 with [uv](https://docs.astral.sh/uv/)
- **Node.js** >= 22.12
- **Gemini API key** (required for LLM-powered panels; data panels work without it)

## Setup

```bash
# Clone and install
git clone https://github.com/ankitksr/duckworth-dugout.git
cd duckworth-dugout

# Python pipeline
cp .env.example .env          # configure your Gemini API key
uv sync

# Frontend
cd frontend
npm install
```

## Data pipeline

The `pipeline/` directory syncs live data from RSS feeds and Cricsheet, runs LLM intelligence passes, and exports static JSON to `frontend/public/api/`.

Panels are organised into tiers by refresh frequency:

| Tier | Panels | Typical interval |
|------|--------|------------------|
| **Hot** | intel_log, wire | ~5 min |
| **Warm** | standings, caps, schedule, ticker, pulse | Periodic |
| **Cool** | scenarios, records, briefing, narratives, dossier, match_notes | On demand |

```bash
uv run python -m pipeline sync                          # all tiers
uv run python -m pipeline sync --tiers hot              # hot tier only
uv run python -m pipeline sync --tiers hot,warm         # multiple tiers
uv run python -m pipeline sync --panel standings        # single panel
uv run python -m pipeline sync --watch                  # continuous (5-min default)
uv run python -m pipeline sync --watch --interval 120   # custom interval (seconds)
uv run python -m pipeline sync --force                  # bypass caches
uv run python -m pipeline seed-sample                   # seed frontend with sample JSON
```

## Frontend

```bash
cd frontend
npm run dev       # dev server at localhost:4321
npm run build     # type-check + static build -> dist/
npm run check     # Astro type-check only
npm run preview   # preview the built site
```

The frontend fetches all data from static JSON files under `/api/ipl/war-room/`. During development, run the pipeline at least once (or use `seed-sample`) to populate `frontend/public/api/`.

## Configuration

All pipeline configuration is via environment variables (see `.env.example`):

| Variable | Required | Description |
|----------|----------|-------------|
| `CT_LLM_API_KEY` | Yes (for LLM panels) | Gemini API key |
| `CT_LLM_VERTEX` | No | Use Vertex AI instead of AI Studio (`true`/`false`) |
| `CT_LLM_GCP_PROJECT` | If Vertex | GCP project ID |
| `CT_LLM_GCP_LOCATION` | If Vertex | GCP region (default: `us-central1`) |
| `CT_LLM_MODEL` | No | Flash model override (default: `gemini-2.5-flash`) |
| `CT_LLM_MODEL_PRO` | No | Pro model override (default: `gemini-3-pro-preview`) |
| `CT_LLM_RATE_LIMIT_RPM` | No | LLM rate limit (default: `10` req/min) |
| `CRICKET_DB_PATH` | No | Path to Cricsheet DuckDB (default: `data/cricket.duckdb`) |

## Project structure

```
duckworth-dugout/
├── frontend/                   # Astro + React static site
│   ├── src/
│   │   ├── components/         # React components (WarRoomView)
│   │   ├── hooks/              # Data fetching & state management
│   │   ├── types/              # TypeScript interfaces
│   │   ├── styles/             # CSS (dark theme, grid layout)
│   │   ├── layouts/            # Astro layouts
│   │   └── pages/              # Astro pages
│   └── public/api/             # Static JSON (pipeline output)
├── pipeline/                   # Python data pipeline
│   ├── panels/                 # Per-panel sync modules
│   ├── sources/                # Data source parsers (RSS, Wikipedia, Cricsheet)
│   ├── intel/                  # LLM intelligence generators
│   │   └── prompts/            # System/user prompt templates
│   ├── llm/                    # LLM provider abstraction (Gemini)
│   ├── db/                     # DuckDB schema & connection
│   ├── ipl/                    # Franchise metadata
│   └── cache/                  # Cache management
├── data/war-room/              # Pipeline output (JSON + DuckDB)
└── .github/workflows/          # GitHub Pages deploy
```

## License

MIT
