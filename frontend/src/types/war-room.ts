/**
 * War Room types — interfaces matching pipeline JSON shapes
 * from /api/ipl/war-room/*.json
 */

// ── standings.json ──

export interface WRStanding {
  franchise_id: string;
  short_name: string;
  primary_color: string;
  played: number;
  wins: number;
  losses: number;
  no_results: number;
  points: number;
  nrr: string; // "+4.171" or "-"
  position: number;
  qualified: boolean;
}

// ── schedule.json ──

export type WRFixtureStatus = "scheduled" | "live" | "completed";

export interface WRFixture {
  match_number: number;
  date: string; // "YYYY-MM-DD"
  time: string; // "19:30 IST"
  venue: string;
  city: string;
  team1: string; // franchise_id
  team2: string;
  status: WRFixtureStatus;
  score1: string | null;
  score2: string | null;
  batting: string | null; // franchise_id of batting team
  match_url: string | null;
  // Completed match fields
  winner: string | null;
  result: string | null;
  hero_name: string | null;
  hero_stat: string | null;
  note: string | null;        // editorial one-liner
  // Live match fields
  overs1: string | null;
  overs2: string | null;
  status_text: string | null;
  current_rr: number | null;
  required_rr: number | null;
  live_forecast: string | null;
  win_prob_team1: number | null;
  win_prob_team2: number | null;
}

// ── caps.json ──

export interface WRCapEntry {
  rank: number;
  player: string;
  team: string; // franchise_id
  team_short: string;
  stat: string; // "81 runs" or "3 wkts"
  innings?: number | null;
}

export interface WRCapSource {
  via: string; // "Wisden", "Wikipedia", "Cricsheet"
  updated: string; // ISO 8601 or date string
}

export interface WRCaps {
  orange_cap: WRCapEntry[];
  purple_cap: WRCapEntry[];
  best_sr: WRCapEntry[];
  best_econ: WRCapEntry[];
  mvp?: WRCapEntry[];
  updated: string; // ISO 8601
  sources?: Record<string, WRCapSource>;
}

// ── ticker.json ──

export type WRTickerCategory =
  | "H2H"
  | "VENUE"
  | "FORM"
  | "MATCHUP"
  | "IMPACT"
  | "STANDINGS"
  | "MILESTONE"
  | "SCENARIO"
  | "EMERGING"
  | "QUIRK"
  | "RECORD";

export interface WRTickerItem {
  category: WRTickerCategory;
  text: string;
}

// ── intel-log.json ──

export interface WRIntelItem {
  id: string;
  title: string;
  snippet: string | null;
  source: string; // feed key: "espncricinfo", "crictracker", etc.
  source_name: string; // display: "ESPNcricinfo"
  url: string;
  published: string; // ISO 8601
  teams: string[]; // franchise_ids
  image_url: string | null;
  author: string | null;
  categories: string[];
}

// ── meta.json ──

export interface WRPanelMeta {
  synced_at: string;
  items?: number;
  teams?: number;
  orange?: number;
  purple?: number;
  fixtures?: number;
  live_matches?: number;
  source?: string;
}

export interface WRMeta {
  season: string;
  last_sync: string;
  panels: {
    intel_log: WRPanelMeta;
    standings: WRPanelMeta;
    caps: WRPanelMeta;
    schedule: WRPanelMeta;
    ticker: WRPanelMeta;
  };
}

// ── Aggregate state ──

// ── pulse.json ──

export interface WRPulseSnapshot {
  match: number;
  date: string;
  result: "W" | "L" | "NR";
  rank: number;
  points: number;
  nrr?: number;
}

export interface WRPulseTeam {
  fid: string;
  short: string;
  color: string;
  current_rank: number;
  points: number;
  nrr: string;
  played: number;
  snapshots: WRPulseSnapshot[];
}

// ── scenarios.json ──

export interface WRIfTonightScenario {
  result: string;
  impact: string;
}

export interface WRIfTonight {
  match: string;
  scenarios: WRIfTonightScenario[];
}

export interface WREliminationEntry {
  team: string;
  risk: "danger" | "watch" | "safe";
  key_metric: string;
  insight: string;
}

export interface WRQualMathEntry {
  tag: string;
  fact: string;
}

export interface WRScenarios {
  matches_played: number;
  situation_brief: string;
  /** @deprecated use situation_brief */
  headline?: string;
  elimination_watch: WREliminationEntry[];
  if_tonight: WRIfTonight[];
  qualification_math: WRQualMathEntry[];
}

// ── records.json ──

export interface WRRecordEntry {
  player: string;
  team?: string;
  current?: string;
  target?: string;
  note: string;
}

export interface WRSeasonBest {
  stat: string;
  holder: string;
  value: string;
  record: string;
  record_holder: string;
}

export interface WRRecords {
  imminent: WRRecordEntry[];
  on_track: WRRecordEntry[];
  season_bests: WRSeasonBest[];
}

// ── briefing.json ──

export interface WRVenueTeamRecord {
  played: number;
  wins: number;
  losses: number;
}

export interface WRVenueStats {
  name: string;
  city: string;
  matches?: number;
  avg_1st_inn?: number;
  avg_1st_inn_recent?: number;      // last 3 seasons (if ≥6 matches)
  avg_2nd_inn?: number;
  avg_2nd_inn_recent?: number;      // last 3 seasons (if ≥6 matches)
  chase_win_pct?: number;
  toss_field_pct?: number;
  defend_180_pct?: number;
  defend_160_pct?: number;
  defend_under_160_pct?: number;
  highest?: number;
  lowest?: number;
  last_5_1st_inn?: number[];
  last_5_2nd_inn?: number[];
  avg_pp_score?: number;             // powerplay avg (since 2023)
  team_records?: Record<string, WRVenueTeamRecord>;
  note?: string;                     // LLM-generated narrative
}

export interface WRFormEntry {
  wins: number;
  losses: number;
  nrr: number;
  position: number;
  last5: string[];                   // ["W", "L", "W", ...]
  trend: string;                     // LLM-generated narrative
}

export interface WRPhaseStatLine {
  pp_bat_sr?: number;
  pp_bowl_econ?: number;
  death_bat_sr?: number;
  death_bowl_econ?: number;
  matches?: number;
  till_match?: number;
}

export interface WRPhaseStats extends WRPhaseStatLine {
  since?: string;                    // mega auction season cutoff
  season?: WRPhaseStatLine;          // current-season overlay
}

export interface WRMatchup {
  player1: string;
  player1_team: string;
  player1_role: string;
  player2: string;
  player2_team: string;
  player2_role: string;
  insight: string;
}

export interface WRBriefing {
  match: string;
  team1_id?: string;                 // franchise ID ("kkr")
  team2_id?: string;
  date?: string;                     // "2026-04-06"
  time?: string;                     // "19:30 IST"
  match_number?: number;
  venue_stats?: WRVenueStats;
  h2h: Record<string, unknown>;
  form: Record<string, WRFormEntry | unknown>;
  squad_news: string[];
  key_matchups: (WRMatchup | { matchup: string; insight: string })[];
  tactical_edge: string;
  favoured?: string;                 // "PBKS" | "KKR" | "even"
  preview_links?: { title: string; url: string }[];
  phase_stats?: Record<string, WRPhaseStats>;

  // Legacy fields (pre-v2 pipeline) — kept for backward compat
  venue_profile?: {
    name: string;
    avg_score: number;
    bat_first_pct: number;
    note: string;
  };
}

// ── narratives.json ──

export interface WRNextTest {
  opponent: string;        // franchise_id
  match_number: number;
  context: string;         // editorial on why this match matters
  playoff_path: string;    // qualification pace sentence
}

export interface WRNarrative {
  franchise_id: string;
  title: string;
  mood: "rising" | "falling" | "steady" | "volatile" | "dominant";
  mood_symbol: string;
  narrative: string;
  key_question: string;
  // Enriched fields (v2)
  buffer?: string;         // strategic position callout
  buffer_tag?: string;     // "BEST BUFFER" | "MUST-WIN ZONE" | etc.
  arc_bullets?: string[];  // 3 structured arc bullets
  next_test?: WRNextTest;  // next opponent + playoff context
}

// ── dossier.json ──

export interface WRDossierPlayer {
  player: string;
  role?: string;
  type?: string;
  threat: "high" | "medium" | "low";
  season_stat?: string;              // "108 runs, SR 152"
  insight: string;
}

export interface WRDossier {
  opponent: string;
  batting_threat: number;
  bowling_threat: number;
  batting_analysis: WRDossierPlayer[];
  bowling_analysis: WRDossierPlayer[];
  weaknesses: string[];
  how_to_win: string[];
}

// ── wire.json ──

export interface WRWireItem {
  headline: string;
  text: string;
  emoji: string;
  category: string;
  severity: "signal" | "alert" | "alarm";
  teams: string[];
  generated_at: string;
  match_day: string;
}

// ── aggregate ──

export interface WRData {
  standings: WRStanding[];
  schedule: WRFixture[];
  caps: WRCaps;
  ticker: WRTickerItem[];
  intelLog: WRIntelItem[];
  pulse: WRPulseTeam[];
  meta: WRMeta;
  // LLM intel
  scenarios: WRScenarios | null;
  records: WRRecords | null;
  briefings: WRBriefing[];
  narratives: WRNarrative[];
}
