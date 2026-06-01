// Off-season switch — single source of truth for the wind-down state.
//
// When `concluded` is true the dashboard stops pretending a match is live
// or upcoming: the top bar suppresses the (frozen) LIVE badge, a champions
// banner renders under the header, and the pre-match Briefing slot is
// replaced by the SeasonWrap. The data panels below (standings, pulse,
// narratives, intel) stay as-is — they read as an honest season archive,
// not a false claim about the present moment.
//
// To reopen for IPL 2027: set `concluded` to false (and refresh the other
// fields once the next season's champion is known).

export interface SeasonInfo {
  /** Master switch. false → normal in-season behaviour. */
  concluded: boolean;
  /** Season year, shown in the banner. */
  year: string;
  /** Champion franchise id — maps to CSS var `--<id>` and the standings entry. */
  champion: string;
  /** Full franchise name for the banner / wrap. */
  championName: string;
  /** Fallback "data frozen …" date. The banner prefers meta.last_sync. */
  frozenAt: string;
  /** Optional final scoreline, e.g. "RCB beat PBKS by 6 runs". null hides it. */
  finalResult: string | null;
}

export const SEASON: SeasonInfo = {
  concluded: true,
  year: "2026",
  champion: "rcb",
  championName: "Royal Challengers Bengaluru",
  frozenAt: "2026-05-31",
  finalResult: null,
};
