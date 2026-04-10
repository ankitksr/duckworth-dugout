import { useMemo, useState } from "react";
import { useWarRoomState } from "../../hooks/useWarRoom";
import type { WRBriefing, WRScenarios, WRVenueStats } from "../../types/war-room";
import { getFormEntry, isStructuredMatchup } from "../helpers";

type BriefingTab = "edge" | "intel" | "matchups" | "form" | "venue";

function splitMatch(match: string): [string, string] {
  const parts = match.split(/\s+vs\s+/i);
  return [parts[0]?.trim() ?? "", parts[1]?.trim() ?? ""];
}

function firstSentence(text: string | null | undefined): string {
  if (!text) return "";
  const clean = text.trim();
  const m = clean.match(/(.+?[.!?])(?:\s|$)/);
  return m?.[1] ?? clean;
}

function nrrFmt(nrr: number | string): string {
  const n = typeof nrr === "string" ? parseFloat(nrr) : nrr;
  if (!Number.isFinite(n)) return String(nrr);
  return (n > 0 ? "+" : "") + n.toFixed(3);
}

// ── Venue Intel (defend thresholds + last 5 first-innings scores) ──

// Helper: build a subtle team-tinted gradient over the card body color.
// Used by Edge (favoured), Standings Swing, Form team cards.
function teamTint(lower: string): string {
  return `linear-gradient(180deg, color-mix(in srgb, var(--${lower}) 8%, transparent), color-mix(in srgb, var(--${lower}) 2%, transparent)), var(--wr-s2)`;
}

function VenueIntel({ vs }: { vs: WRVenueStats }) {
  const d180 = vs.defend_180_pct;
  const dUnder = vs.defend_under_160_pct;
  const last5 = vs.last_5_1st_inn;
  const last5_2nd = vs.last_5_2nd_inn;
  if (d180 == null && !last5?.length && !last5_2nd?.length) return null;

  const chipClass = (s: number) =>
    `wr-br-chip${s >= 180 ? " high" : s < 150 ? " low" : ""}`;

  return (
    <div className="wr-br-stack wr-br-stack-tight">
      {d180 != null && dUnder != null && (
        <div className="wr-br-defend">
          <span className="wr-br-defend-good">180+ DEFENDED {d180}%</span>
          <span className="wr-br-defend-bad">&lt;160 DEFENDED {dUnder}%</span>
        </div>
      )}
      {last5 && last5.length > 0 && (
        <div className="wr-br-chips-row">
          <span className="wr-br-chips-label">1ST INN &middot; LAST 5</span>
          <div className="wr-br-chips">
            {last5.map((s, i) => <span key={i} className={chipClass(s)}>{s}</span>)}
          </div>
        </div>
      )}
      {last5_2nd && last5_2nd.length > 0 && (
        <div className="wr-br-chips-row">
          <span className="wr-br-chips-label">2ND INN &middot; LAST 5</span>
          <div className="wr-br-chips">
            {last5_2nd.map((s, i) => <span key={i} className={chipClass(s)}>{s}</span>)}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Hero Strip — standalone matchup overview card ──

function HeroStrip({ briefing }: { briefing: WRBriefing }) {
  const [t1, t2] = splitMatch(briefing.match);
  const t1L = t1.toLowerCase();
  const t2L = t2.toLowerCase();
  const f1 = getFormEntry(briefing.form, t1);
  const f2 = getFormEntry(briefing.form, t2);

  const vs = briefing.venue_stats;
  const isRecent = vs?.avg_1st_inn_recent != null;
  const avgScore = vs?.avg_1st_inn_recent ?? vs?.avg_1st_inn ?? briefing.venue_profile?.avg_score ?? null;
  const chaseWin = vs?.chase_win_pct ?? null;
  const tossField = vs?.toss_field_pct ?? null;
  const h2h = briefing.h2h as { total?: number; [k: string]: unknown } | null;
  const t1Wins = h2h ? (h2h[`${t1}_wins`] as number ?? 0) : 0;
  const t2Wins = h2h ? (h2h[`${t2}_wins`] as number ?? 0) : 0;
  const h2hTotal = h2h?.total ?? (t1Wins + t2Wins);

  const venueName = vs?.name ?? briefing.venue_profile?.name ?? "";
  const city = vs?.city ?? "";
  const venueLabel = city && venueName ? `${venueName}, ${city}` : venueName || city;
  const previewLink = briefing.preview_links?.[0] ?? null;

  const teamSide = (team: string, f: ReturnType<typeof getFormEntry>, lower: string, right?: boolean) => (
    <div className={`wr-bp-side${right ? " right" : ""}`}>
      <span className="wr-bp-name" style={{ color: `var(--${lower})` }}>{team}</span>
      {f && (
        <div className="wr-bp-form-line">
          <span className="wr-bp-standing">#{f.position}</span>
          {f.last5 && f.last5.length > 0 && (
            <div className="wr-br-mh-dots">
              {f.last5.map((r, i) => (
                <span key={i} className={`wr-br-fo-dot ${r === "W" ? "w" : r === "NR" ? "nr" : "l"}`} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );

  return (
    <section
      className="wr-bp-hero"
      style={{
        background: [
          `radial-gradient(ellipse 45% 100% at 0% 50%, color-mix(in srgb, var(--${t1L}) 14%, transparent), transparent)`,
          `radial-gradient(ellipse 45% 100% at 100% 50%, color-mix(in srgb, var(--${t2L}) 10%, transparent), transparent)`,
          "linear-gradient(180deg, rgba(16, 20, 30, 0.96), rgba(12, 14, 19, 0.98))",
        ].join(", "),
      }}
    >
      {/* Section 1: Matchup — team names with form below each */}
      <div className="wr-bp-identity">
        {teamSide(t1, f1, t1L)}
        <span className="wr-bp-vs">vs</span>
        {teamSide(t2, f2, t2L, true)}
      </div>

      <div className="wr-bp-divider" aria-hidden="true" />

      {/* Section 2: Match details — venue, time, preview.
          The venue label has two variants: the desktop spans show full
          stadium name + city + time on separate lines; the mobile span
          collapses to "city · time · M#" on a single line. CSS toggles
          which is visible per @container width. */}
      <div className="wr-bp-details">
        <div className="wr-bp-detail-venue">{venueLabel}</div>
        <div className="wr-bp-detail-meta">
          {briefing.time}
          {briefing.match_number != null && <> &middot; M{briefing.match_number}</>}
        </div>
        <div className="wr-bp-detail-compact" aria-hidden="true">
          {(city || venueName).toUpperCase()}
          {briefing.time && <> &middot; {briefing.time}</>}
          {briefing.match_number != null && <> &middot; M{briefing.match_number}</>}
        </div>
        {previewLink && (
          <a href={previewLink.url} target="_blank" rel="noopener noreferrer" className="wr-bp-preview">
            <span className="wr-bp-preview-tag">ESPNcricinfo Preview</span>
            <span className="wr-bp-preview-title">{previewLink.title}</span>
            <span>&#x2197;</span>
          </a>
        )}
      </div>

      <div className="wr-bp-divider" aria-hidden="true" />

      {/* Section 3: Stats — metric on top, label below */}
      <div className="wr-bp-metrics">
        {avgScore != null && (
          <div className="wr-bp-metric">
            <strong>{avgScore}</strong>
            <span>{isRecent ? "1ST INN (3Y)" : "1ST INN AVG"}</span>
          </div>
        )}
        {chaseWin != null && (
          <div className="wr-bp-metric">
            <strong>{chaseWin}%</strong>
            <span>CHASE</span>
          </div>
        )}
        {tossField != null && (
          <div className="wr-bp-metric">
            <strong>{tossField}%</strong>
            <span>TOSS&rarr;FIELD</span>
          </div>
        )}
        {h2hTotal > 0 && (
          <div className="wr-bp-metric">
            <strong>{t1Wins}&ndash;{t2Wins}</strong>
            <span>H2H ALL-TIME</span>
          </div>
        )}
      </div>
    </section>
  );
}

// ── Tab: MATCH EDGE ──

function EdgeTab({ briefing, ifTonight }: {
  briefing: WRBriefing;
  ifTonight: WRScenarios["if_tonight"][0] | null;
}) {
  const [t1, t2] = splitMatch(briefing.match);
  const t1L = t1.toLowerCase();
  const t2L = t2.toLowerCase();
  const favoured = briefing.favoured;
  const favouredLower = favoured?.toLowerCase() ?? "";
  const h2h = briefing.h2h as { total?: number; note?: string; [k: string]: unknown } | null;
  const h2hNote = h2h?.note || null;
  const [, t1Short] = splitMatch(briefing.match);
  void t1Short; // unused but keeps destructure consistent
  const t1Wins = h2h ? (h2h[`${t1}_wins`] as number ?? 0) : 0;
  const t2Wins = h2h ? (h2h[`${t2}_wins`] as number ?? 0) : 0;
  const h2hTotal = h2h?.total ?? (t1Wins + t2Wins);

  const teamFavoured = favoured && favoured !== "even";

  return (
    <div className="wr-br-cols">
      {/* Main column: Match Edge + Head to Head cards */}
      <div className="wr-br-stack">
        <div
          className={`wr-br-card${teamFavoured ? " team" : ""}`}
          style={teamFavoured ? { background: teamTint(favouredLower) } : undefined}
        >
          <div className="wr-br-card-hd">
            <span className="wr-br-label">Match Edge</span>
            {teamFavoured && (
              <span className="wr-br-edge-badge" style={{ background: `var(--${favouredLower})` }}>
                {favoured} FAVOURED
              </span>
            )}
            {favoured === "even" && (
              <span className="wr-br-edge-badge even">EVEN CONTEST</span>
            )}
          </div>
          {briefing.tactical_edge && (
            <div className="wr-br-card-body">{briefing.tactical_edge}</div>
          )}
        </div>

        {h2hNote && (
          <div className="wr-br-card">
            <div className="wr-br-card-hd">
              <span className="wr-br-label">Head to Head</span>
              {h2hTotal > 0 && (
                <span className="wr-br-card-hd-aside" style={{ font: "700 9px 'JetBrains Mono', monospace", letterSpacing: "0.5px" }}>
                  <span style={{ color: `var(--${t1L})` }}>{t1} {t1Wins}</span>
                  <span style={{ color: "var(--wr-tm)" }}>&ndash;</span>
                  <span style={{ color: `var(--${t2L})` }}>{t2Wins} {t2}</span>
                </span>
              )}
            </div>
            <div className="wr-br-card-body">{h2hNote}</div>
          </div>
        )}
      </div>

      {/* Sidebar column: Standings Swing — two team-tinted cards */}
      <div className="wr-br-section">
        <div className="wr-br-section-hd">
          <span className="wr-br-label">Standings Swing</span>
        </div>
        {ifTonight && ifTonight.scenarios.length >= 2 ? (
          <div className="wr-br-stack">
            {ifTonight.scenarios.slice(0, 2).map((s, i) => {
              const isT1 = s.result.toLowerCase().includes(t1L);
              const winTeam = isT1 ? t1 : t2;
              const teamVar = isT1 ? t1L : t2L;
              return (
                <div key={i} className="wr-br-card team" style={{ background: teamTint(teamVar) }}>
                  <div className="wr-br-card-hd">
                    <span className="wr-br-label" style={{ color: `var(--${teamVar})` }}>
                      {winTeam} WIN
                    </span>
                  </div>
                  <div className="wr-br-card-body">{s.impact}</div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="wr-empty">No standings scenarios available</div>
        )}
      </div>
    </div>
  );
}

// ── Tab: INTEL ──

function IntelTab({ briefing }: { briefing: WRBriefing }) {
  const news = briefing.squad_news ?? [];
  const links = briefing.preview_links ?? [];

  return (
    <div className="wr-br-cols" style={{ gridTemplateColumns: "1fr" }}>
      <div className="wr-br-section">
        <div className="wr-br-section-hd">
          <span className="wr-br-label">Squad News</span>
          <span className="wr-br-count">{news.length}</span>
        </div>
        {news.length > 0 ? (
          <div className="wr-br-card" style={{ padding: 0 }}>
            {news.map((item, i) => (
              <div key={i} className="wr-br-row">
                <span className="wr-br-row-lead" aria-hidden>&#9656;</span>
                <div className="wr-br-row-main">{item}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="wr-empty">No squad updates tracked</div>
        )}
      </div>

      {links.length > 0 && (
        <div className="wr-br-section">
          <div className="wr-br-section-hd">
            <span className="wr-br-label">On ESPNcricinfo</span>
          </div>
          <div className="wr-br-card" style={{ padding: 0 }}>
            {links.map((link, i) => (
              <a
                key={i}
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                className="wr-br-row"
              >
                <span className="wr-br-row-lead" aria-hidden>&#x2197;</span>
                <div className="wr-br-row-main">{link.title}</div>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Tab: MATCHUPS ──

function MatchupsTab({ briefing }: { briefing: WRBriefing }) {
  const matchups = briefing.key_matchups ?? [];

  if (matchups.length === 0) {
    return (
      <div className="wr-br-cards" style={{ gridTemplateColumns: "1fr" }}>
        <div className="wr-empty">No matchups available</div>
      </div>
    );
  }

  return (
    <div className="wr-br-cards">
      {matchups.map((mu, i) =>
        isStructuredMatchup(mu) ? (
          <div key={i} className="wr-br-card">
            <div className="wr-br-card-hd">
              <span className="wr-br-mu-player" style={{ color: `var(--${mu.player1_team.toLowerCase()})` }}>
                {mu.player1}
                <small>{mu.player1_team} &middot; {mu.player1_role}</small>
              </span>
              <span className="wr-br-mu-x" aria-hidden>&times;</span>
              <span className="wr-br-mu-player right" style={{ color: `var(--${mu.player2_team.toLowerCase()})` }}>
                {mu.player2}
                <small>{mu.player2_team} &middot; {mu.player2_role}</small>
              </span>
            </div>
            <div className="wr-br-card-body">{mu.insight}</div>
          </div>
        ) : (
          <div key={i} className="wr-br-card">
            <div className="wr-br-card-hd">
              <span className="wr-br-label">{mu.matchup}</span>
            </div>
            <div className="wr-br-card-body">{mu.insight}</div>
          </div>
        ),
      )}
    </div>
  );
}

// ── Tab: FORM ──

function FormTab({ briefing }: { briefing: WRBriefing }) {
  const [t1, t2] = splitMatch(briefing.match);

  const TeamCard = ({ team }: { team: string }) => {
    const lower = team.toLowerCase();
    const f = getFormEntry(briefing.form, team);
    if (!f) {
      return (
        <div className="wr-br-card">
          <div className="wr-empty">No form data for {team}</div>
        </div>
      );
    }

    const nrr = typeof f.nrr === "number" ? f.nrr : parseFloat(String(f.nrr));
    const mood = nrr > 0 ? "rising" : nrr < -0.5 ? "falling" : "steady";
    const ps = briefing.phase_stats?.[team];

    return (
      <div className="wr-br-card team" style={{ background: teamTint(lower) }}>
        <div className="wr-br-card-hd">
          <span className="wr-br-form-name" style={{ color: `var(--${lower})` }}>{team}</span>
          <span className={`wr-br-form-mood ${mood}`}>
            {mood === "rising" ? "\u25B2" : mood === "falling" ? "\u25BC" : "\u25B8"}
          </span>
          <span className="wr-br-form-pos">#{f.position}</span>
        </div>
        <div className="wr-br-form-stats">
          <span><strong>{f.wins}W {f.losses}L</strong></span>
          <span>
            NRR <strong className={nrr > 0 ? "up" : nrr < 0 ? "down" : ""}>{nrrFmt(nrr)}</strong>
          </span>
          {f.last5 && f.last5.length > 0 && (
            <div className="wr-br-mh-dots">
              {f.last5.map((r, i) => (
                <span key={i} className={`wr-br-fo-dot ${r === "W" ? "w" : r === "NR" ? "nr" : "l"}`} />
              ))}
            </div>
          )}
        </div>
        {ps && (ps.pp_bat_sr || ps.death_bowl_econ) && (
          <div className="wr-bp-phase-grid">
            <span className="wr-bp-pg-corner" />
            <span className="wr-bp-pg-col">Since {ps.since ?? "2025"}</span>
            <span className="wr-bp-pg-col wr-bp-pg-col-szn">
              This season{ps.season?.till_match ? ` (M${ps.season.till_match})` : ""}
            </span>
            <span className="wr-bp-pg-row">PP BAT SR</span>
            <span className="wr-bp-pg-val">{ps.pp_bat_sr ?? "—"}</span>
            <span className="wr-bp-pg-val wr-bp-pg-szn-val">{ps.season?.pp_bat_sr ?? "—"}</span>
            <span className="wr-bp-pg-row">PP BOWL ECON</span>
            <span className="wr-bp-pg-val">{ps.pp_bowl_econ ?? "—"}</span>
            <span className="wr-bp-pg-val wr-bp-pg-szn-val">{ps.season?.pp_bowl_econ ?? "—"}</span>
            <span className="wr-bp-pg-row">DEATH BAT SR</span>
            <span className="wr-bp-pg-val">{ps.death_bat_sr ?? "—"}</span>
            <span className="wr-bp-pg-val wr-bp-pg-szn-val">{ps.season?.death_bat_sr ?? "—"}</span>
            <span className="wr-bp-pg-row">DEATH BOWL ECON</span>
            <span className="wr-bp-pg-val">{ps.death_bowl_econ ?? "—"}</span>
            <span className="wr-bp-pg-val wr-bp-pg-szn-val">{ps.season?.death_bowl_econ ?? "—"}</span>
          </div>
        )}
        {f.trend && <div className="wr-br-card-foot">{f.trend}</div>}
      </div>
    );
  };

  return (
    <div className="wr-br-cards">
      <TeamCard team={t1} />
      <TeamCard team={t2} />
    </div>
  );
}

// ── Tab: VENUE ──

function VenueTab({ briefing }: { briefing: WRBriefing }) {
  const vs = briefing.venue_stats;

  if (!vs) {
    return (
      <div className="wr-br-cols" style={{ gridTemplateColumns: "1fr" }}>
        <div className="wr-empty">No venue data available</div>
      </div>
    );
  }

  // Compose the venue stats array up-front so the JSX stays clean.
  const stats: { label: string; value: number | string; detail: string }[] = [];
  if (vs.avg_1st_inn != null) stats.push({ label: "AVG 1ST INNS", value: vs.avg_1st_inn, detail: "All-time at venue" });
  if (vs.avg_1st_inn_recent != null) stats.push({ label: "AVG 1ST INNS (3Y)", value: vs.avg_1st_inn_recent, detail: "Since 2023" });
  if (vs.avg_2nd_inn != null) stats.push({ label: "AVG 2ND INNS", value: vs.avg_2nd_inn, detail: "Chase baseline" });
  if (vs.avg_2nd_inn_recent != null) stats.push({ label: "AVG 2ND INNS (3Y)", value: vs.avg_2nd_inn_recent, detail: "Since 2023" });
  if (vs.avg_pp_score != null) stats.push({ label: "AVG POWERPLAY", value: vs.avg_pp_score, detail: "Since 2023" });
  if (vs.highest != null) stats.push({ label: "HIGHEST", value: vs.highest, detail: "Venue ceiling" });
  if (vs.lowest != null) stats.push({ label: "LOWEST", value: vs.lowest, detail: "Venue floor" });

  const teamRecords = vs.team_records ?? {};
  const playerRecords = vs.player_venue_stats ?? [];
  const hasGroundContext = vs.note || vs.defend_180_pct != null || vs.last_5_1st_inn?.length;

  return (
    <div className="wr-br-cols">
      {/* Main column: venue intrinsic — stats grid + ground context.
          Both describe the venue itself; pairing them in one column
          balances the column heights against the historical data on
          the right. */}
      <div className="wr-br-stack">
        <div className="wr-br-section">
          <div className="wr-br-section-hd">
            <span className="wr-br-label">Venue Stats</span>
          </div>
          <div className="wr-br-metrics-grid">
            {stats.map((s) => (
              <div key={s.label} className="wr-br-metric">
                <span className="wr-br-metric-value">{s.value}</span>
                <span className="wr-br-metric-label">{s.label}</span>
                <span className="wr-br-metric-detail">{s.detail}</span>
              </div>
            ))}
          </div>
        </div>

        {hasGroundContext && (
          <div className="wr-br-section">
            <div className="wr-br-section-hd">
              <span className="wr-br-label">Ground Context</span>
            </div>
            <div className="wr-br-card">
              {vs.note && <div className="wr-br-card-body" style={{ marginBottom: 8 }}>{vs.note}</div>}
              <VenueIntel vs={vs} />
            </div>
          </div>
        )}
      </div>

      {/* Sidebar column: historical performance — who has done what
          at this venue. Team Records on top, Player Records below. */}
      <div className="wr-br-stack">
        {Object.keys(teamRecords).length > 0 && (
          <div className="wr-br-section">
            <div className="wr-br-section-hd">
              <span className="wr-br-label">At This Venue</span>
            </div>
            <div className="wr-br-card" style={{ padding: 0 }}>
              {Object.entries(teamRecords).map(([team, rec]) => {
                const pct = rec.played > 0 ? Math.round((rec.wins / rec.played) * 100) : 0;
                return (
                  <div key={team} className="wr-br-row">
                    <span className="wr-br-row-lead" style={{ color: `var(--${team.toLowerCase()})` }}>{team}</span>
                    <div className="wr-br-row-main">
                      <strong>{rec.wins}W</strong> &ndash; {rec.losses}L
                    </div>
                    <div className="wr-br-row-trail">{pct}%</div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {playerRecords.length > 0 && (
          <div className="wr-br-section">
            <div className="wr-br-section-hd">
              <span className="wr-br-label">Player Records at Venue</span>
            </div>
            <div className="wr-br-card" style={{ padding: 0 }}>
              {playerRecords.map((p) => {
                const teamL = p.team.toLowerCase();
                const statLine = p.type === "bat"
                  ? `${p.runs} runs · avg ${p.avg} · SR ${p.sr}`
                  : `${p.wickets} wkts · econ ${p.econ}`;
                return (
                  <div key={`${p.player}-${p.type}`} className="wr-br-row">
                    <span className="wr-br-row-lead" style={{ color: `var(--${teamL})` }}>{p.team}</span>
                    <div className="wr-br-row-main">
                      <strong style={{ color: `var(--${teamL})` }}>{p.player}</strong>
                      <span className="wr-br-row-sub">{statLine}</span>
                    </div>
                    <div className="wr-br-row-trail">{p.matches}<span className="muted">inn</span></div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {Object.keys(teamRecords).length === 0 && playerRecords.length === 0 && (
          <div className="wr-empty">No historical records for this venue</div>
        )}
      </div>
    </div>
  );
}

// ── Main Panel ──

export function BriefingPanel() {
  const { briefings, scenarios } = useWarRoomState();
  const [activeIdx, setActiveIdx] = useState(0);
  const [activeTab, setActiveTab] = useState<BriefingTab>("edge");

  const safeIdx = briefings && briefings.length > 0
    ? Math.min(activeIdx, briefings.length - 1) : 0;
  const briefing = briefings?.[safeIdx] ?? null;

  const ifTonight = useMemo(() => {
    if (!scenarios?.if_tonight?.length || !briefing) return null;
    const teams = briefing.match.split(/\s+vs\s+/i).map((t) => t.trim().toUpperCase());
    return (
      scenarios.if_tonight.find((it) =>
        teams.some((t) => it.match.toUpperCase().includes(t)),
      ) ?? scenarios.if_tonight[0]
    );
  }, [briefing?.match, scenarios?.if_tonight]);

  if (!briefing) {
    return (
      <div className="wr-pnl wr-briefing-pnl">
        <div className="wr-ph">Briefing <sub>PRE-MATCH</sub></div>
        <div className="wr-briefing-empty">
          <div className="wr-empty">No upcoming match briefing available</div>
        </div>
      </div>
    );
  }

  const tabs: { key: BriefingTab; label: string }[] = [
    { key: "edge", label: "MATCH EDGE" },
    { key: "matchups", label: "MATCHUPS" },
    { key: "intel", label: "INTEL" },
    { key: "form", label: "FORM" },
    { key: "venue", label: "VENUE" },
  ];

  let content;
  switch (activeTab) {
    case "matchups": content = <MatchupsTab briefing={briefing} />; break;
    case "intel": content = <IntelTab briefing={briefing} />; break;
    case "form": content = <FormTab briefing={briefing} />; break;
    case "venue": content = <VenueTab briefing={briefing} />; break;
    default: content = <EdgeTab briefing={briefing} ifTonight={ifTonight} />;
  }

  return (
    <div className="wr-pnl wr-briefing-pnl">
      <div className="wr-ph">
        Briefing <sub>PRE-MATCH</sub>
        {briefings.length > 1 && (
          <span className="wr-br-match-pills">
            {briefings.map((b, i) => (
              <button
                key={i}
                className={`wr-br-match-pill ${safeIdx === i ? "on" : ""}`}
                onClick={() => { setActiveIdx(i); setActiveTab("edge"); }}
              >
                {b.match}
              </button>
            ))}
          </span>
        )}
      </div>

      <HeroStrip briefing={briefing} />

      <div className="wr-briefing-content-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={`wr-bct${activeTab === tab.key ? " on" : ""}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="wr-briefing-scroll">
        {content}
      </div>
    </div>
  );
}
