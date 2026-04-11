# Pipeline reference

Quick lookup for the duckworth-dugout sync pipeline. Covers the CLI surface,
panel + tier registry, per-panel resource needs, the Cloudflare Cron schedule,
runtime budgets, and manual override commands.

For implementation rationale and history, see the commits between `141f236`
and `f6af0bf` (the seven-phase refactor that produced this shape) and
`/Users/ankitksr/.claude/plans/transient-sleeping-feather.md`.

## CLI command reference

The pipeline exposes one sync command. `WHAT` is a comma-separated list of
tier names and/or panel names. The runner expands tiers, dedupes, and runs in
`PANEL_ORDER`.

| Invocation | What runs | Cost | Use case |
|---|---|---|---|
| `pipeline sync live` | standings + schedule + pulse | ~5–10s, no LLM | Fast refresh during a match — what live-update fires |
| `pipeline sync hot` | intel_log + wire | ~30–60s, LLM | Article ingest + wire generators |
| `pipeline sync live,hot` | live + intel_log + wire | ~60–90s, LLM | The 30-min sync-deploy hot run |
| `pipeline sync warm` | live + caps + ticker + availability + roster + scenarios + records | ~60–120s, LLM | Mid-cost periodic refresh |
| `pipeline sync cool` | briefing + narratives + dossier + match_notes | ~2–5min, heavy LLM | Per-match LLM augmentation |
| `pipeline sync all` | every panel | ~3–6min, full LLM | Full sync — what the 4h cron fires |
| `pipeline sync standings` | single panel | ~3–5s | Manual standings refresh |
| `pipeline sync standings,pulse` | two panels | ~5–8s | Mixed list (panels + tiers can be combined freely) |
| `pipeline sync` | defaults to `all` | full | Bare invocation |

Optional flags: `--season 2026`, `--watch --interval 300` (loop), `--force` (bypass LLM hash cache).

The other CLI commands (unchanged by the refactor):

| Command | Purpose |
|---|---|
| `pipeline pull-enrichment` | Download `enrichment.duckdb` from the latest GitHub release snapshot |
| `pipeline migrate-articles` | One-shot extraction of every unprocessed article (vs the 30/run cap in `sync`) |
| `pipeline seed-sample` | Copy `data/sample/*.json` into `frontend/public/api/ipl/war-room/` for dev |

## Tier composition

| Tier | Panels | LLM? | Notes |
|---|---|:-:|---|
| **live** | standings, schedule, pulse | no | Fast refresh path. PANEL_ORDER puts these first so downstream LLM panels read fresh state. |
| **hot** | intel_log, wire, caps | yes | Article ingest + wire generators + cap leaderboards (ESPN crawl4ai). Triggers `_init_articles` (body crawl + LLM extraction). Caps refreshes within ~30 min of a match completing. |
| **warm** | standings, schedule, pulse, caps, ticker, availability, roster, scenarios, records | yes | Superset of live + medium-cost panels (caps also in hot for 30-min cadence). |
| **cool** | briefing, narratives, dossier, match_notes | yes | Per-match heavy LLM panels. |
| **all** | everything | yes | Magic preset for the full sync. |

Tiers may overlap. `sync live,warm` dedupes — runs each panel once in `PANEL_ORDER`.

`PANEL_ORDER`:

```
standings → schedule → pulse        # live tier
→ intel_log                          # article ingest (hot)
→ caps                               # hot (ESPN crawl) + warm superset
→ availability → roster
→ wire → ticker → scenarios → records
→ briefing → dossier → narratives → match_notes
```

## Per-panel resource needs

The runner inspects the active panel set and only fires the resource gates
that any active panel actually needs. `sync pulse` opens the DB but skips
RSS fetch and article store entirely.

| Panel | RSS feeds | DB conn | Article store | LLM | Output |
|---|:-:|:-:|:-:|:-:|---|
| intel_log | ✓ | ✓ | ✓ | – | intel-log.json |
| availability | – | ✓ | ✓ | – | availability.json |
| roster | – | ✓ | – | – | roster.json |
| standings | ✓ | ✓ | – | – | standings.json |
| caps | ✓ | ✓ | – | – | caps.json |
| schedule | – | ✓ | – | gated | schedule.json |
| pulse | – | ✓ | – | – | pulse.json |
| wire | ✓ | ✓ | ✓ | ✓ | wire.json |
| ticker | – | ✓ | – | ✓ | ticker.json |
| scenarios | – | ✓ | – | ✓ | scenarios.json |
| records | – | ✓ | – | ✓ | records.json |
| briefing | – | ✓ | – | ✓ | briefing.json |
| dossier | – | ✓ | – | ✓ | dossier.json |
| narratives | – | ✓ | – | ✓ | narratives.json |
| match_notes | – | ✓ | – | ✓ | match-notes.json |

**Resource consumer sets** (defined in `pipeline/sync.py`):

| Set | Panels | Trigger |
|---|---|---|
| `RSS_CONSUMERS` | intel_log, wire, standings, caps | `_fetch_feeds(ctx)` |
| `ARTICLE_CONSUMERS` | intel_log, wire, availability | `_init_articles(ctx)` (body crawl + LLM extraction). Also implies RSS fetch. |
| `DB_CONSUMERS` | roster, availability, pulse, schedule, standings, caps, wire, briefing, dossier, narratives, scenarios, records, match_notes | `_open_db(ctx)` |
| `LLM_PANELS` | wire, ticker, scenarios, records, briefing, dossier, narratives, match_notes | When **none** are active, `ctx.skip_llm = True` and the schedule panel skips its inline `extract_match_results` step. |

`schedule`'s LLM step is gated on `ctx.skip_llm`. So `sync live` and `sync schedule`
both run lean (no LLM). `sync warm` or `sync all` run schedule with extraction.

## Single-panel sync and upstream staleness

The runner does **not** auto-resolve panel-to-panel dependency closures. If
you ask for `sync pulse` alone, the pulse panel runs — but its upstream
inputs (`standings.json`, `schedule.json`) are read **from disk** as they
were last published, not freshly refreshed.

This applies to every derived panel that reads other panels' outputs:

| Panel | Disk-loaded upstream when run alone |
|---|---|
| pulse | standings.json, schedule.json |
| ticker | schedule.json (today_matches), standings.json (via LLM context) |
| wire | schedule.json (today_matches), standings.json (via LLM context) |
| briefing | schedule.json (next match lookup) |
| dossier | schedule.json (today_matches) |
| narratives | schedule.json + standings.json (via LLM context) |
| scenarios | standings.json (via LLM context) |
| records | standings.json + cricsheet (via LLM context) |
| match_notes | schedule.json |

For the **non-LLM derived panels** (just pulse today), the panel prints an
explicit warning at runtime when it detects stale upstream:

```
$ pipeline sync pulse
...
  Note: standings, schedule not refreshed in this run; pulse reads from
  disk (possibly stale). For fresh pulse, run `pipeline sync live` or
  `pipeline sync standings,schedule,pulse`.
  Pulse: 18 schedule matches, 14 from Cricsheet, 10 teams
```

For **LLM panels**, the LLM hash cache (briefing/dossier/wire/scenarios/etc)
already gates regeneration on the inputs they care about, so single-panel
mode is safe for prompt iteration — the cache returns the previous output
if the inputs haven't changed. Use `--force` to bypass the hash cache.

**Rule of thumb**:

| Goal | Run this |
|---|---|
| Fast accurate refresh of a cheap panel | `pipeline sync live` |
| Single panel against fresh upstream | `pipeline sync standings,schedule,<panel>` |
| LLM panel iteration with deterministic inputs (cached) | `pipeline sync <panel>` |
| LLM panel iteration with fresh inputs + bypass cache | `pipeline sync <panel> --force` |

This is a deliberate design trade-off in the refactor — we chose tier-based
ordering over a full panel-DAG runner. Production cron paths
(`live` / `live,hot` / `all`) always run upstream panels first via PANEL_ORDER,
so the staleness gap only matters for manual single-panel invocations.

## Cloudflare Worker cron schedule

Triggers live in `cloudflare/wrangler.toml` and route through `cloudflare/worker.js`.
Cloudflare Cron fires within ~1s of the schedule (vs GitHub Actions cron which
drifts 10–40 min). All gating happens in the Worker (free CPU) so out-of-window
fires never reach GitHub Actions runners.

| Cron (UTC) | When | Worker action | GH workflow | Pipeline command |
|---|---|---|---|---|
| `*/5 * * * *` | Every 5 min, gated to **March-May + match window** | dispatch | `live-update.yml` | `pipeline sync live` |
| `*/30 * * * *` | Every 30 min during match window | dispatch w/ inputs | `sync-deploy.yml` | `pipeline sync live,hot` |
| `*/30 * * * *` | Top-of-hour, **off-window** in season | dispatch w/ inputs | `sync-deploy.yml` | `pipeline sync hot` |
| `10 1,5,9,13,17,21 * * *` | Six times per day, every 4h | dispatch w/ inputs | `sync-deploy.yml` | `pipeline sync all` |

**Match window** in `worker.js`:

| Day type | UTC window | IST window |
|---|---|---|
| Weekday (Mon–Fri) | 13:00 – 19:59 | 18:30 – 01:30 |
| Weekend (Sat–Sun) | 09:00 – 19:59 | 14:30 – 01:30 |

**Out of window**: live-update fires are silently dropped at the Worker level.
**Out of season** (Jun–Feb): all three crons are silent no-ops.

## Workflow runtime breakdown

| Workflow fire | Worker → GH | Runner spin-up | Pipeline | Build | Deploy | **Total** |
|---|---|---|---|---|---|---|
| live-update (`sync live`) | <1s | ~10s | ~5–10s | 0s (dist cached) | ~5s wrangler | **~20–30s** |
| sync-deploy hot (`sync live,hot`) | <1s | ~15s | ~60–90s | ~25s | ~10s | **~110–140s** |
| sync-deploy all (`sync all`) | <1s | ~15s | ~3–5min | ~25s | ~10s | **~3.5–6min** |

Live-update is intentionally tight. The Cloudflare-shaped dist is cached after
each sync-deploy build under cache key `dist-cf`; live-update restores it,
overlays fresh JSON into `frontend/dist/api/ipl/war-room/`, and runs
`wrangler pages deploy` directly. No `npm ci` + Astro rebuild.

End-to-end target: a match score change visible on `https://duckworth-dugout.pages.dev`
within ~30 seconds of the underlying source updating.

## Cache keys (GH Actions)

| Key | Owner | Path | Purpose |
|---|---|---|---|
| `api-data` | sync-deploy.yml | `frontend/public/api/ipl/war-room` | Last published panel JSON. Restored at start of every workflow run. |
| `dist-cf` | sync-deploy.yml | `frontend/dist` | Cloudflare-shaped (root base) Astro build output. live-update restores + overlays fresh JSON. |
| `enrichment-db` | sync-deploy.yml | `data/enrichment.duckdb` | Article store, wire history, snapshots. Also published as a release asset (`data-snapshot`). |
| `cricket-db` | sync-deploy.yml | `data/cricket.duckdb` | Cricsheet ball-by-ball DB. Updated daily at UTC 04:00 via the duckworth-mcp ingest. |
| `playwright-chromium` | both workflows | `~/.cache/ms-playwright` | Headless Chromium for crawl4ai. |

GitHub Actions caches are immutable per key. sync-deploy uses the
`gh cache delete <key> || true` + `actions/cache/save` pattern to overwrite.
live-update only restores caches; it never saves, so concurrent live-update
runs can't race the api-data cache against sync-deploy.

Both workflows share the `concurrency: pipeline-deploy` group with
`cancel-in-progress: false`, so concurrent fires queue rather than cancel.

## Manual overrides

```bash
# Ad-hoc CLI run anywhere with the repo cloned
uv run python -m pipeline sync live           # fast refresh
uv run python -m pipeline sync briefing       # single LLM panel
uv run python -m pipeline sync live --watch   # loop every 5 min
uv run python -m pipeline sync all --force    # bypass LLM hash cache

# Trigger a workflow manually (skips Cloudflare cron, runs immediately)
gh workflow run live-update.yml
gh workflow run sync-deploy.yml -f tiers=live,hot
gh workflow run sync-deploy.yml -f panel=standings
gh workflow run sync-deploy.yml -f tiers=all -f force=true
gh workflow run sync-deploy.yml -f update_cricket_db=true   # also refresh cricket.duckdb
```

`gh workflow run sync-deploy.yml` with no inputs defaults to `all` (full sync).

## Cloudflare Worker setup (one-time)

```bash
cd cloudflare

# 1. Authenticate with Cloudflare (opens a browser)
npx wrangler login

# 2. Set the GitHub PAT — paste it interactively when prompted
#    (must be a fine-grained PAT with Actions: Read & Write
#     scoped to ankitksr/duckworth-dugout)
npx wrangler secret put GITHUB_PAT

# 3. Deploy the worker
npx wrangler deploy
```

After deploy, the worker is reachable at the Cloudflare Workers dashboard.
The **Triggers** tab lists all three cron entries; the **Logs** tab shows
each scheduled fire and any dispatch failures.

To rotate the GitHub PAT later: re-issue the PAT, then `npx wrangler secret put GITHUB_PAT`
again from `cloudflare/`.

## Verification checklist

After `wrangler deploy`, wait ~5 minutes and verify:

1. **Cloudflare Workers dashboard** → `duckworth-dugout-cron` → Logs: should see entries like `Dispatched live-update.yml` (in window) or `Outside match window, skipping live-update` (off window).
2. **GitHub Actions** → `Live Score Update` runs list: new runs triggered by `workflow_dispatch` arriving every 5 min on the Cloudflare cron.
3. **First live-update run logs** → "Sync live panels" prints Cricbuzz standings parse + pulse computation in <10s. "Restore cached dist" should hit on the second run onward (the very first run after the refactor lands will fall back to a full Astro build because the `dist-cf` cache doesn't exist yet — subsequent runs are fast).
4. **Live site** `https://duckworth-dugout.pages.dev` → schedule + standings reflect each cron fire within ~30s.

If Worker logs show 401/403 dispatch failures, the GitHub PAT either lacks
`Actions: Read & Write` or is scoped to the wrong repo. Re-issue and re-run
`npx wrangler secret put GITHUB_PAT`.

If GH Actions runs are firing but the live site isn't updating, check the
"Restore cached dist" step in the run logs — on the very first run after the
refactor, `dist-cf` is missing and the fallback rebuild fires instead. After
that first sync-deploy, subsequent live-updates hit the cache and finish in ~25s.

## Quick architectural map

```
                  ┌──────────────────────────┐
                  │  Cloudflare Worker Cron  │
                  │  (cloudflare/worker.js)  │
                  └──────┬─────────┬─────────┘
                         │         │
              every 5min │         │ every 30min / 4h
                         ▼         ▼
              ┌────────────────┐ ┌──────────────────┐
              │ live-update.yml│ │ sync-deploy.yml  │
              │ (Cloudflare    │ │ (GH Pages +      │
              │  Pages only)   │ │  Cloudflare)     │
              └───────┬────────┘ └────────┬─────────┘
                      │                   │
                      ▼                   ▼
              ┌─────────────────────────────────┐
              │   pipeline sync <preset>        │
              │     ↓                           │
              │   resolve_panels()              │
              │     ↓                           │
              │   Per-panel resource gating     │
              │     ↓                           │
              │   PANEL_ORDER execution         │
              └─────────────────────────────────┘
                      │
                      ▼
              ┌─────────────────────────────────┐
              │ Sources                         │
              │  - cricbuzz / espn (crawl4ai)   │
              │  - wisden / ca / ct / espn RSS  │
              │  - wikipedia (HTML scrape)      │
              │  - cricsheet (local DuckDB)     │
              │  - article store (DB + LLM)    │
              └─────────────────────────────────┘
                      │
                      ▼
              ┌─────────────────────────────────┐
              │ Outputs                         │
              │  frontend/public/api/ipl/       │
              │    war-room/*.json              │
              │  data/war-room/*.json (mirror)  │
              └─────────────────────────────────┘
```
