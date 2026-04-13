# Duckworth Dugout

IPL monitor — a single-screen dashboard that surfaces live standings,
match timelines, cap races, and AI-powered editorial intelligence during the IPL season.

**Live site:** ankitksr.github.io/duckworth-dugout

## Vision

This is an analyst's war room, not a consumer app. The design language is dark, dense,
and information-rich — inspired by mission control screens and Bloomberg terminals.
Every pixel earns its place. The goal is situational awareness: a viewer should be able
to glance at the Dugout and immediately know who's winning, who's surging, what's at
stake tonight, and what the numbers say about tomorrow.

The AI layer isn't decorative — it synthesizes signals humans would miss. Wire cards
surface emerging patterns. Briefings combine H2H records, venue history, and squad
news into pre-match tactical reads. Narratives track each franchise's season arc.
The intelligence must be specific, grounded in data, and never generic.

## Project Structure

```
duckworth-dugout/
├── frontend/                    # Astro + React static site
│   ├── src/
│   │   ├── components/
│   │   │   ├── WarRoomView.tsx  # Root orchestrator (WarRoomProvider → 3-col layout)
│   │   │   ├── bridge/          # Center-column deep panels (Briefing, TeamIntel)
│   │   │   ├── panels/          # All dashboard panels + top/bottom bars
│   │   │   └── helpers.ts       # Utility functions (IST clock, NRR display, etc.)
│   │   ├── hooks/               # useWarRoom (state/context), useWarRoomData (fetch)
│   │   ├── types/war-room.ts    # TypeScript interfaces for all panel JSON shapes
│   │   ├── lib/svg-smooth.ts    # Catmull-Rom SVG utilities (pulse river chart)
│   │   ├── styles/dugout.css    # All styles — dark theme, 3-col grid, panel cards
│   │   ├── layouts/             # DugoutLayout.astro (fonts, meta)
│   │   └── pages/index.astro    # Entry point — renders <WarRoomView client:load />
│   └── public/api/ipl/war-room/ # Static JSON consumed by frontend (pipeline output)
├── pipeline/                    # Python data pipeline
│   ├── __main__.py              # Click CLI (sync, seed-sample)
│   ├── config.py                # Paths, HTTP, LLM settings (all via env vars)
│   ├── context.py               # SyncContext — shared state threaded through panels
│   ├── sync.py                  # Orchestrator — tier dispatch, feed fetch, panel loop
│   ├── writer.py                # Dual-write: data/war-room/ + frontend/public/api/
│   ├── models.py                # Dataclasses for all panel outputs
│   ├── snapshots.py             # DuckDB versioned snapshots
│   ├── panels/                  # Per-panel sync modules (one per panel)
│   ├── sources/                 # Data source parsers (RSS, Wikipedia, Cricsheet, live)
│   ├── intel/                   # LLM intelligence generators + prompt templates
│   │   └── prompts/             # System/user .md prompt pairs per intel type
│   ├── llm/                     # LLM provider abstraction (Gemini, cache, rate limit)
│   ├── db/                      # DuckDB connection + schema
│   ├── ipl/                     # Franchise metadata (colors, names, Cricsheet IDs)
│   └── cache/                   # Cache management
├── data/
│   ├── war-room/                # Pipeline JSON output + enrichment.duckdb
│   └── sample/                  # Sample JSON for dev seeding (seed-sample command)
├── cache/                       # Runtime caches (LLM responses, Wikipedia, manifests)
└── .github/workflows/         # GitHub Pages: push → deploy.yml; cron → sync-deploy.yml; match-window → live-update.yml
```

## Quick Start

```bash
cp .env.example .env              # set CT_LLM_API_KEY (Gemini)
uv sync                           # install Python deps

cd frontend && npm install         # install Node deps

# Run pipeline (at least once, or use seed-sample for dev)
uv run python -m pipeline sync
uv run python -m pipeline seed-sample   # alternative: use sample JSON

# Dev server
cd frontend && npm run dev         # localhost:4321
```

## Architecture

### Data Flow

```
RSS Feeds (Wisden, ESPNcricinfo, CricTracker, CricketAddictor)
  + Wikipedia (fixture scraping, fallback standings)
  + Cricsheet DuckDB (ball-by-ball, career stats — via ATTACH)
      ↓
  SyncContext (shared feeds, standings, today's matches)
      ↓
  Panel sync modules (ordered, dependency-aware)
      ↓
  LLM Intelligence (Gemini flash/pro, structured output, cached)
      ↓
  Static JSON → data/war-room/ + frontend/public/api/
      ↓
  Astro static site → GitHub Pages (no runtime backend)
```

### Two-Database Pattern

Cricsheet data lives in `cricket.duckdb` (ball-by-ball match data from Cricsheet).
The pipeline ATTACHes it read-only and writes enrichment data (article store, snapshots)
to `enrichment.duckdb`. Cross-DB JOINs bridge the two.

Set `CRICKET_DB_PATH` env var to point at a shared cricket.duckdb (e.g. from duckworth-mcp).

### Frontend Architecture

Astro static site with a single React island (`<WarRoomView client:load />`).

Layout: 3-column grid inside `WarRoomInner`:
- **Left column** — Standings, Match Timeline, Cap Race
- **Center column** — Season Pulse (river chart, top), then contextual:
  - No team selected → BriefingPanel (pre-match tactical intel)
  - Team selected → TeamIntelPanel (arc, form, scout tabs)
- **Right column** — AI Wire, Intel Feed

Top bar: franchise pill buttons (team selection), scrolling ticker, IST clock.

All data fetched from `/api/ipl/war-room/*.json` on mount — zero API calls at runtime.

### Fonts

- **Anybody** (400/600/900) — display headings, panel titles
- **Inter** (300–700) — body text, data labels
- **JetBrains Mono** (400/500) — stats, numbers, ticker

## Panel Inventory

### Data Panels (warm tier)

| Panel | Source | JSON |
|-------|--------|------|
| **Standings** | Wisden RSS → CricketAddictor → Wikipedia → Cricsheet cascade | standings.json |
| **Schedule** | Wikipedia fixtures + Cricsheet enrichment (heroes, scores) | schedule.json |
| **Caps** | Wisden/CricketAddictor HTML tables → Cricsheet fallback | caps.json |
| **Pulse** | Derived from standings snapshots (rank trajectory per team) | pulse.json |
| **Ticker** | Smart highlights: H2H, venue, form, matchup, impact | ticker.json |

### Intel Panels (hot tier)

| Panel | Source | JSON |
|-------|--------|------|
| **Intel Log** | Aggregated RSS feeds + crawled article bodies | intel-log.json |
| **Wire** | LLM editorial signals (scenarios, records, insights) | wire.json |

### LLM Panels (cool tier)

| Panel | Model | Regeneration Trigger | JSON |
|-------|-------|---------------------|------|
| **Scenarios** | Flash | Standings hash change | scenarios.json |
| **Records** | Flash | Daily | records.json |
| **Briefing** | Pro | Match day + matchup | briefing.json |
| **Narratives** | Pro | Schedule results hash change | narratives.json |
| **Dossier** | Pro | Matchup + match day change | dossier.json |
| **Match Notes** | Pro | On demand | match_notes.json |

## Pipeline

### Sync Command

```bash
uv run python -m pipeline sync                          # all tiers
uv run python -m pipeline sync --tiers hot              # hot tier only
uv run python -m pipeline sync --tiers hot,warm         # multiple tiers
uv run python -m pipeline sync --panel standings        # single panel
uv run python -m pipeline sync --watch                  # continuous (5-min default)
uv run python -m pipeline sync --watch --interval 120   # custom interval
uv run python -m pipeline sync --force                  # bypass caches
```

### Tier System

| Tier | Panels | When |
|------|--------|------|
| **hot** | intel_log, wire | Every ~5 min (watch mode) |
| **warm** | standings, caps, schedule, ticker, pulse | Periodic refresh |
| **cool** | scenarios, records, briefing, narratives, dossier, match_notes | On demand / hash-triggered |

### Execution Order

Panels run in dependency order (defined in `panels/__init__.py`):

```
intel_log → standings → caps → schedule → pulse → wire → ticker
→ scenarios → records → briefing → narratives → dossier → match_notes
```

Standings must complete before schedule/pulse. Today's matches must load before
ticker/wire/briefing/dossier/scenarios/records/narratives.

### Staleness & Caching

Each LLM panel owns its own cache key:
- **Scenarios, Ticker** — standings hash (regenerate when table changes)
- **Narratives** — schedule results hash (regenerate when match results change)
- **Wire** — per-generator content-driven hash, prefixed with `HASH_VERSION`.
  Each generator anchors its hash to the signal it actually responds to:
  **situation** = standings + completions, **scout** = completions + cap
  leaders, **newsdesk** = recent article IDs, **preview** = today's fixture
  pairs, **take** = `_time_window()` (morning/afternoon/evening/night) +
  standings. A generator only re-runs when its content slice changes, so
  near-duplicates can't accumulate within a day. Bumping `HASH_VERSION`
  (in `wire_generators/__init__.py`) makes legacy same-day rows expire
  automatically on the next sync via the `hash_version` column on
  `war_room_wire`.
- **Briefing** — match day + team matchup pair
- **Dossier** — team matchup pair, reset on new match day
- **Records** — daily threshold

LLM responses are cached in `cache/llm/{panel}/`. Resyncs don't burn LLM calls
unless the cache key has changed.

### Data Source Cascade (Standings Example)

1. Parse from Wisden RSS HTML table
2. If empty → CricketAddictor RSS fallback
3. If empty → Wikipedia fixture scrape + aggregate
4. If empty → Cricsheet DuckDB query (last resort)
5. Patch with schedule data if stale

## LLM Intelligence Layer

### Models

- **Flash** (`gemini-2.5-flash`) — scenarios, records, ticker, wire, extract
- **Pro** (`gemini-3-pro-preview`) — briefing, dossier, narratives, match notes

### MCP Data Freshness Rule

duckworth-mcp (Cricsheet) lags 1–2 days for the current season. LLM queries using
Cricsheet data must scope to career/all-time stats. Current-season data comes from
RSS feeds + synced JSON, never from MCP season-filtered queries.

### Prompt Architecture

Each intel module has a system + user prompt pair in `intel/prompts/`:
- `{module}_system.md` — role, tone, output schema
- `{module}_user.md` — Jinja-style template filled with live data

LLM calls use structured JSON output (via `response_schema`) for reliable parsing.
Rate-limited to `CT_LLM_RATE_LIMIT_RPM` (default 10 req/min). Retry loop handles
429/500/503/RESOURCE_EXHAUSTED with exponential backoff.

### Intel Modules

| Module | What |
|--------|------|
| `wire.py` | Incremental editorial signals, severity-tagged, daily reset |
| `briefing.py` | Pre-match tactical brief (H2H + venue + squad news) |
| `dossier.py` | Opposition threat assessment (batting/bowling profiles) |
| `narrative.py` | Per-franchise season arc (mood, form, storylines) |
| `scenarios.py` | Playoff qualification math, elimination watch |
| `records.py` | Career milestones + season records approaching |
| `smart_ticker.py` | Data-driven ticker (career stats + current-season context) |
| `match_notes.py` | Live match commentary (on-demand) |

Supporting: `articles.py` (article store + body crawl), `extract.py` (entity extraction),
`tools.py` (Cricsheet query tools for LLM), `schemas.py` (Pydantic response models),
`roster_context.py` (player metadata: hand, role, style).

## Key Conventions

- **Python 3.13+**, managed by `uv`
- **DuckDB** with ATTACH pattern — cricket.duckdb (read-only) + enrichment.duckdb (read-write)
- **Dataclasses** in `pipeline/models.py` for all panel output shapes
- **Click CLI** — `sync` and `seed-sample` commands
- **Dual-write** — every panel writes to both `data/war-room/` and `frontend/public/api/`
- **Astro + React 19** — static-first, single React island
- **TypeScript interfaces** in `types/war-room.ts` mirror Python dataclasses
- **Dark theme** — `#0a0b0e` background, team colors via franchise metadata
- **No runtime backend** — all data is static JSON, deployed to GitHub Pages
- **Idempotent syncs** — safe to re-run; cache keys prevent redundant LLM calls

## Configuration

All pipeline config via environment variables (see `.env.example`):

| Variable | Required | Description |
|----------|----------|-------------|
| `CT_LLM_API_KEY` | Yes (for LLM panels) | Gemini API key |
| `CT_LLM_VERTEX` | No | Use Vertex AI (`true`/`false`) |
| `CT_LLM_GCP_PROJECT` | If Vertex | GCP project ID |
| `CT_LLM_GCP_LOCATION` | If Vertex | GCP region (default: `us-central1`) |
| `CT_LLM_MODEL` | No | Flash model override (default: `gemini-2.5-flash`) |
| `CT_LLM_MODEL_PRO` | No | Pro model override (default: `gemini-3-pro-preview`) |
| `CT_LLM_RATE_LIMIT_RPM` | No | Rate limit (default: `10` req/min) |
| `CRICKET_DB_PATH` | No | Cricsheet DuckDB path (default: `data/cricket.duckdb`) |
| `CT_LIVE_SOURCE` | No | Live score source: `auto` (crawl + RSS fallback, default), `crawl` (ESPN only), `rss` (RSS only — score string only, no CRR/RRR) |

## Lint

```bash
uv run ruff check pipeline/
cd frontend && npm run check    # Astro type-check
```

## Data Sources

| Source | What | Rate Limit |
|--------|------|-----------|
| Cricsheet (DuckDB) | Ball-by-ball match data, player profiles, venues | local |
| Wisden RSS | Standings, cap races, editorial | ~1 req/s |
| ESPNcricinfo RSS | News feed + article body crawl | ~1 req/s |
| CricketAddictor RSS | Standings/caps fallback | ~1 req/s |
| CricTracker RSS | News feed | ~1 req/s |
| Wikipedia | Season fixtures, scores, hero performances | 5 req/s |
