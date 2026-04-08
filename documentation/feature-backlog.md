# Feature Backlog — from user research (Apr 2026)

Prioritized by user demand (how many of 6 personas asked for it) × feasibility.

## P0 — High impact, data already available

### 1. Player form cards
**Asked by:** CSK fan, GT fan, RR fan, fantasy player, journalist
**What:** Click a player name anywhere (cap race, briefing, team file) → popover/panel showing: last 5 innings scores, season SR, batting position, role. For bowlers: economy, wickets, overs bowled per match.
**Data source:** `__NEXT_DATA__` from scorecard pages has full `inningBatsmen`/`inningBowlers` per match. Could also use Cricsheet career data already in `cricket.duckdb`.
**Effort:** Medium — needs pipeline to build per-player JSON, frontend component.

### 2. Scenario simulator ("what if X wins next N?")
**Asked by:** GT fan, CSK fan, journalist, RR fan
**What:** Interactive or pre-computed scenarios: "If GT wins their next 5, they finish at position X with NRR ~Y." Show playoff probability per team, not just top/bottom extremes.
**Data source:** Standings + remaining schedule → simulate all outcomes. Could pre-compute common paths (win next 3, win next 5, win all).
**Effort:** Medium — LLM or algorithmic, needs frontend display.

### 3. Injury/availability panel
**Asked by:** CSK fan, GT fan, fantasy player, journalist
**What:** Single panel: player → Out / Doubtful / Playing, sourced from Wire + Intel Feed. Currently scattered across Wire cards.
**Data source:** LLM extraction from Intel Feed articles. Flag entities mentioned with injury/rest/dropped keywords.
**Effort:** Medium — entity extraction exists in `intel/extract.py`, needs availability classification.

### 4. H2H records in team view
**Asked by:** CSK fan, GT fan, RR fan, journalist
**What:** When team is selected, show their all-time IPL record vs each opponent (W-L).
**Data source:** Already in `cricket.duckdb` — simple query on `matches` table.
**Effort:** Low — query + frontend component.

## P1 — High impact, moderate effort

### 5. Briefing look-ahead (next 2-3 matches)
**Asked by:** CSK fan, journalist
**What:** Generate briefing for upcoming matches beyond just tonight's. Let users peek at CSK vs DC briefing 2 days early.
**Data source:** Already supported by pipeline — briefing generates for "next upcoming match." Could pre-generate for next 2-3.
**Effort:** Low — pipeline already has the capability, just needs to run for more matches.

### 6. Venue stats by player
**Asked by:** Fantasy player, journalist
**What:** In briefing venue tab, show player career stats at this ground (batting avg, bowling economy).
**Data source:** `cricket.duckdb` has `batting_scorecard` + `matches` with venue. Cross-join with tonight's playing XI.
**Effort:** Medium — needs per-player venue query + briefing prompt update.

### 7. Wire deduplication
**Asked by:** Journalist, casual viewer
**What:** Cap at 2-3 cards per team per signal type. Currently CSK has 8+ doom cards saying similar things.
**Data source:** Post-generation dedup pass comparing semantic similarity of wire card text.
**Effort:** Low — add dedup logic in `intel/wire.py` after generation.

## P2 — Nice to have

### 8. Hero card for casual viewers
**What:** Prominent card at top: "Tonight: KKR vs LSG, 7:30 PM Kolkata. RR lead the table. Last night: GT won by 1 run." Plain English, zero jargon.
**Effort:** Low — derive from schedule + standings, render above the grid.

### 9. Predicted playing XI
**What:** Parse predicted XI from Intel Feed articles (CricketAddictor, CricTracker publish these daily). Surface in briefing panel.
**Effort:** Medium — LLM extraction from article bodies, needs entity matching to squad.

### 10. Share card / social export
**What:** One-button shareable graphic: team stats, standings, match result — formatted for WhatsApp/Twitter.
**Effort:** Medium — canvas/SVG generation, download button.

### 11. Streak badges + visual celebrations
**What:** "W3" badge on standings for win streaks. Gold highlight for table leader. Visual polish for dominant teams.
**Effort:** Low — CSS + conditional rendering.

### 12. NRR tooltips + jargon explainers
**What:** Hover/tap on NRR, SR, Econ → plain English explanation. "NRR +2.4 means RR are winning by large margins on average."
**Effort:** Low — tooltip component + static text.

### 13. Slower/pausable ticker
**What:** Reduce ticker scroll speed. Pause on hover/tap.
**Effort:** Low — CSS animation-duration tweak + JS pause handler.
