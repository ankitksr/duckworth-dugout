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

function VenueIntel({ vs }: { vs: WRVenueStats }) {
  const d180 = vs.defend_180_pct;
  const dUnder = vs.defend_under_160_pct;
  const last5 = vs.last_5_1st_inn;
  const last5_2nd = vs.last_5_2nd_inn;
  if (d180 == null && !last5?.length && !last5_2nd?.length) return null;

  return (
    <div className="wr-br-venue-intel">
      {d180 != null && dUnder != null && (
        <div className="wr-br-defend-row">
          <span className="wr-br-defend-safe">180+ defended {d180}%</span>
          <span className="wr-br-defend-sep">&middot;</span>
          <span className="wr-br-defend-danger">&lt;160 defended {dUnder}%</span>
        </div>
      )}
      {last5 && last5.length > 0 && (
        <div className="wr-br-last5">
          <span className="wr-br-last5-label">1ST INN &middot; LAST 5</span>
          {last5.map((s, i) => (
            <span key={i} className={`wr-br-last5-score${s >= 180 ? " high" : s < 150 ? " low" : ""}`}>{s}</span>
          ))}
        </div>
      )}
      {last5_2nd && last5_2nd.length > 0 && (
        <div className="wr-br-last5">
          <span className="wr-br-last5-label">2ND INN &middot; LAST 5</span>
          {last5_2nd.map((s, i) => (
            <span key={i} className={`wr-br-last5-score${s >= 180 ? " high" : s < 150 ? " low" : ""}`}>{s}</span>
          ))}
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
  const highest = vs?.highest ?? null;
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

      {/* Section 2: Match details — venue, time, preview */}
      <div className="wr-bp-details">
        <div className="wr-bp-detail-venue">{venueLabel}</div>
        <div className="wr-bp-detail-meta">
          {briefing.time}
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
            <span>H2H</span>
          </div>
        )}
        {highest != null && (
          <div className="wr-bp-metric">
            <strong>{highest}</strong>
            <span>HIGHEST</span>
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

  return (
    <div className="wr-bp-edge-wrap">
      <div className="wr-bp-edge-grid">
        {/* Left: match edge card + H2H card stacked */}
        <div className="wr-bp-edge-col">
          <div className="wr-bp-edge-card">
            <div className="wr-br-edge-hd">
              <span className="wr-br-edge-label">Match Edge</span>
              {favoured && favoured !== "even" && (
                <span className="wr-br-edge-badge" style={{ background: `var(--${favouredLower})` }}>
                  {favoured} FAVOURED
                </span>
              )}
              {favoured === "even" && (
                <span className="wr-br-edge-badge even">EVEN CONTEST</span>
              )}
            </div>
            {briefing.tactical_edge && (
              <div className="wr-br-edge-text">{briefing.tactical_edge}</div>
            )}
          </div>

          {h2hNote && (
            <div className="wr-bp-h2h-card">
              <div className="wr-br-edge-hd">
                <span className="wr-br-edge-label">Head to Head</span>
                {h2hTotal > 0 && (
                  <span className="wr-bp-h2h-score">
                    <span style={{ color: `var(--${t1L})` }}>{t1} {t1Wins}</span>
                    <span className="wr-bp-h2h-sep">&ndash;</span>
                    <span style={{ color: `var(--${t2L})` }}>{t2Wins} {t2}</span>
                  </span>
                )}
              </div>
              <div className="wr-bp-h2h-note">{h2hNote}</div>
            </div>
          )}
        </div>

        {/* Right: standings swing — standalone */}
        <div className="wr-bp-edge-aside">
          <div className="wr-br-label">Standings Swing</div>
          {ifTonight && ifTonight.scenarios.length >= 2 ? (
            ifTonight.scenarios.slice(0, 2).map((s, i) => {
              const isT1 = s.result.toLowerCase().includes(t1L);
              const winTeam = isT1 ? t1 : t2;
              const teamVar = isT1 ? t1L : t2L;
              return (
                <div key={i} className="wr-br-stake" style={{ ["--tc" as string]: `var(--${teamVar})` }}>
                  <div className="wr-br-stake-team" style={{ color: `var(--${teamVar})` }}>{winTeam} win</div>
                  <div className="wr-br-stake-impact">{s.impact}</div>
                </div>
              );
            })
          ) : (
            <div className="wr-empty">No standings scenarios available</div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Tab: INTEL (Squads + Matchups) ──

function IntelTab({ briefing }: { briefing: WRBriefing }) {
  return (
    <div className="wr-br">
      <div className="wr-br-section">
        <div className="wr-br-label">Squad News <span className="wr-br-via">{briefing.squad_news.length}</span></div>
        {briefing.squad_news.length > 0 ? (
          briefing.squad_news.map((item, i) => (
            <div key={i} className="wr-br-item">{item}</div>
          ))
        ) : (
          <div className="wr-empty">No squad updates tracked</div>
        )}
      </div>

      {briefing.preview_links && briefing.preview_links.length > 0 && (
        <div className="wr-br-section wr-br-links">
          <div className="wr-br-label">On ESPNcricinfo</div>
          {briefing.preview_links.map((link, i) => (
            <a key={i} href={link.url} target="_blank" rel="noopener noreferrer" className="wr-br-link-card">
              <span className="wr-br-link-title">{link.title}</span>
              <span className="wr-br-link-arrow">&#x2197;</span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Tab: MATCHUPS ──

function MatchupsTab({ briefing }: { briefing: WRBriefing }) {
  return (
    <div className="wr-br">
      <div className="wr-br-section">
        <div className="wr-br-label">Key Matchups <span className="wr-br-via">{briefing.key_matchups.length}</span></div>
        {briefing.key_matchups.length > 0 ? (
          <div className="wr-br-battle-grid">
            {briefing.key_matchups.map((mu, i) =>
              isStructuredMatchup(mu) ? (
                <div key={i} className="wr-br-battle">
                  <span className="wr-br-battle-num">{i + 1}</span>
                  <div className="wr-br-battle-body">
                    <div className="wr-br-battle-players">
                      <div className="wr-br-battle-side">
                        <span className="wr-br-battle-name" style={{ color: `var(--${mu.player1_team.toLowerCase()})` }}>
                          {mu.player1}
                        </span>
                        <span className="wr-br-battle-role">{mu.player1_team} &middot; {mu.player1_role}</span>
                      </div>
                      <span className="wr-br-battle-x">&times;</span>
                      <div className="wr-br-battle-side right">
                        <span className="wr-br-battle-name" style={{ color: `var(--${mu.player2_team.toLowerCase()})` }}>
                          {mu.player2}
                        </span>
                        <span className="wr-br-battle-role">{mu.player2_team} &middot; {mu.player2_role}</span>
                      </div>
                    </div>
                    <div className="wr-br-battle-insight">{mu.insight}</div>
                  </div>
                </div>
              ) : (
                <div key={i} className="wr-br-matchup">
                  <div className="wr-br-mu-name">{mu.matchup}</div>
                  <div className="wr-br-mu-insight">{mu.insight}</div>
                </div>
              ),
            )}
          </div>
        ) : (
          <div className="wr-empty">No matchups available</div>
        )}
      </div>
    </div>
  );
}

// ── Tab: FORM ──

function FormTab({ briefing }: { briefing: WRBriefing }) {
  const [t1, t2] = splitMatch(briefing.match);

  const TeamForm = ({ team }: { team: string }) => {
    const lower = team.toLowerCase();
    const f = getFormEntry(briefing.form, team);
    if (!f) return <div className="wr-empty">No form data</div>;

    const nrr = typeof f.nrr === "number" ? f.nrr : parseFloat(String(f.nrr));
    const mood = nrr > 0 ? "rising" : nrr < -0.5 ? "falling" : "steady";
    const ps = briefing.phase_stats?.[team];

    return (
      <div
        className="wr-bp-form-card"
        style={{
          borderLeftColor: `var(--${lower})`,
          background: `linear-gradient(135deg, color-mix(in srgb, var(--${lower}) 8%, transparent), rgba(12, 14, 19, 0.85))`,
        }}
      >
        <div className="wr-bp-form-hd">
          <span className="wr-bp-form-name" style={{ color: `var(--${lower})` }}>{team}</span>
          <span className={`wr-br-form-mood ${mood}`}>
            {mood === "rising" ? "\u25B2" : mood === "falling" ? "\u25BC" : "\u25B8"}
          </span>
          <span className="wr-br-form-pos">#{f.position}</span>
        </div>
        <div className="wr-bp-form-stats">
          <span className="wr-bp-form-stat"><strong>{f.wins}W {f.losses}L</strong></span>
          <span className="wr-bp-form-stat">
            NRR <strong className={nrr > 0 ? "up" : nrr < 0 ? "down" : ""}>{nrrFmt(nrr)}</strong>
          </span>
        </div>
        {f.last5 && f.last5.length > 0 && (
          <div className="wr-bp-form-run">
            <span className="wr-bp-form-run-label">FORM</span>
            <div className="wr-br-mh-dots">
              {f.last5.map((r, i) => (
                <span key={i} className={`wr-br-fo-dot ${r === "W" ? "w" : r === "NR" ? "nr" : "l"}`} />
              ))}
            </div>
          </div>
        )}
        {ps && (ps.pp_bat_sr || ps.death_bowl_econ) && (
          <div className="wr-bp-phase-grid">
            {/* Column headers: time-based */}
            <span className="wr-bp-pg-corner" />
            <span className="wr-bp-pg-col">Since {ps.since ?? "2025"}</span>
            <span className="wr-bp-pg-col wr-bp-pg-col-szn">
              This season{ps.season?.till_match ? ` (M${ps.season.till_match})` : ""}
            </span>
            {/* Powerplay rows */}
            <span className="wr-bp-pg-row">PP BAT SR</span>
            <span className="wr-bp-pg-val">{ps.pp_bat_sr ?? "—"}</span>
            <span className="wr-bp-pg-val wr-bp-pg-szn-val">{ps.season?.pp_bat_sr ?? "—"}</span>
            <span className="wr-bp-pg-row">PP BOWL ECON</span>
            <span className="wr-bp-pg-val">{ps.pp_bowl_econ ?? "—"}</span>
            <span className="wr-bp-pg-val wr-bp-pg-szn-val">{ps.season?.pp_bowl_econ ?? "—"}</span>
            {/* Death rows */}
            <span className="wr-bp-pg-row">DEATH BAT SR</span>
            <span className="wr-bp-pg-val">{ps.death_bat_sr ?? "—"}</span>
            <span className="wr-bp-pg-val wr-bp-pg-szn-val">{ps.season?.death_bat_sr ?? "—"}</span>
            <span className="wr-bp-pg-row">DEATH BOWL ECON</span>
            <span className="wr-bp-pg-val">{ps.death_bowl_econ ?? "—"}</span>
            <span className="wr-bp-pg-val wr-bp-pg-szn-val">{ps.season?.death_bowl_econ ?? "—"}</span>
          </div>
        )}
        {f.trend && <div className="wr-bp-form-trend">{f.trend}</div>}
      </div>
    );
  };

  return (
    <div className="wr-bp-form-grid">
      <TeamForm team={t1} />
      <TeamForm team={t2} />
    </div>
  );
}

// ── Tab: VENUE ──

function VenueTab({ briefing }: { briefing: WRBriefing }) {
  const vs = briefing.venue_stats;

  if (!vs) {
    return <div className="wr-br"><div className="wr-empty">No venue data available</div></div>;
  }

  return (
    <div className="wr-br wr-br-grid">
      <div className="wr-br-main">
        <div className="wr-br-section">
          <div className="wr-br-label">Venue Stats</div>
          <div className="wr-br-facts wr-br-matchup-summary">
            {vs.avg_1st_inn != null && (
              <div className="wr-br-fact">
                <span className="wr-br-fact-label">AVG 1ST INNS</span>
                <span className="wr-br-fact-value">{vs.avg_1st_inn}</span>
                <span className="wr-br-fact-detail">All-time at venue</span>
              </div>
            )}
            {vs.avg_1st_inn_recent != null && (
              <div className="wr-br-fact">
                <span className="wr-br-fact-label">AVG 1ST INNS (3Y)</span>
                <span className="wr-br-fact-value">{vs.avg_1st_inn_recent}</span>
                <span className="wr-br-fact-detail">Since 2023</span>
              </div>
            )}
            {vs.avg_2nd_inn != null && (
              <div className="wr-br-fact">
                <span className="wr-br-fact-label">AVG 2ND INNS</span>
                <span className="wr-br-fact-value">{vs.avg_2nd_inn}</span>
                <span className="wr-br-fact-detail">Chase baseline</span>
              </div>
            )}
            {vs.avg_2nd_inn_recent != null && (
              <div className="wr-br-fact">
                <span className="wr-br-fact-label">AVG 2ND INNS (3Y)</span>
                <span className="wr-br-fact-value">{vs.avg_2nd_inn_recent}</span>
                <span className="wr-br-fact-detail">Since 2023</span>
              </div>
            )}
            {vs.avg_pp_score != null && (
              <div className="wr-br-fact">
                <span className="wr-br-fact-label">AVG POWERPLAY</span>
                <span className="wr-br-fact-value">{vs.avg_pp_score}</span>
                <span className="wr-br-fact-detail">Since 2023</span>
              </div>
            )}
            {vs.highest != null && (
              <div className="wr-br-fact">
                <span className="wr-br-fact-label">HIGHEST</span>
                <span className="wr-br-fact-value">{vs.highest}</span>
                <span className="wr-br-fact-detail">Venue ceiling</span>
              </div>
            )}
            {vs.lowest != null && (
              <div className="wr-br-fact">
                <span className="wr-br-fact-label">LOWEST</span>
                <span className="wr-br-fact-value">{vs.lowest}</span>
                <span className="wr-br-fact-detail">Venue floor</span>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="wr-br-sidebar">
        <div className="wr-br-section">
          <div className="wr-br-label">Ground Context</div>
          {vs.note && <div className="wr-br-ground-note">{vs.note}</div>}
          <VenueIntel vs={vs} />
          {!vs.note && !vs.defend_180_pct && !vs.last_5_1st_inn?.length && (
            <div className="wr-empty">No ground notes</div>
          )}
        </div>
        {vs.team_records && Object.keys(vs.team_records).length > 0 && (
          <div className="wr-br-section">
            <div className="wr-br-label">At This Venue</div>
            <div className="wr-br-venue-records">
              {Object.entries(vs.team_records).map(([team, rec]) => (
                <div key={team} className="wr-br-venue-record" style={{ borderLeftColor: `var(--${team.toLowerCase()})` }}>
                  <span className="wr-br-venue-record-team" style={{ color: `var(--${team.toLowerCase()})` }}>{team}</span>
                  <span className="wr-br-venue-record-stat">
                    <strong>{rec.wins}W</strong>-{rec.losses}L
                    <span className="wr-br-venue-record-pct">({rec.played > 0 ? Math.round(rec.wins / rec.played * 100) : 0}%)</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
        {vs.player_venue_stats && vs.player_venue_stats.length > 0 && (
          <div className="wr-br-section">
            <div className="wr-br-label">Player Records at Venue</div>
            <div className="wr-br-venue-records">
              {vs.player_venue_stats.map((p) => (
                <div key={`${p.player}-${p.type}`} className="wr-br-venue-record" style={{ borderLeftColor: `var(--${p.team.toLowerCase()})` }}>
                  <span className="wr-br-venue-record-team" style={{ color: `var(--${p.team.toLowerCase()})` }}>
                    {p.player}
                  </span>
                  <span className="wr-br-venue-record-stat">
                    {p.type === "bat"
                      ? <>{p.runs} runs · avg {p.avg} · SR {p.sr}</>
                      : <>{p.wickets} wkts · econ {p.econ}</>}
                    <span className="wr-br-venue-record-pct">{p.matches} inn</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
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
