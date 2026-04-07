import React, { useState, useEffect, useMemo } from "react";
import { useWarRoomState } from "../../hooks/useWarRoom";
import type {
  WRBriefing, WRDossier, WRVenueStats, WRMatchup, WRScenarios,
} from "../../types/war-room";
import { getFormEntry, isStructuredMatchup } from "../helpers";

type BriefingTab = "matchup" | "intel" | "ground" | "scout";

function MatchHeader({ briefing }: { briefing: WRBriefing }) {
  const parts = briefing.match.split(/\s+vs\s+/i);
  const t1 = parts[0]?.trim() ?? "";
  const t2 = parts[1]?.trim() ?? "";
  const t1Lower = t1.toLowerCase();
  const t2Lower = t2.toLowerCase();

  const f1 = getFormEntry(briefing.form, t1);
  const f2 = getFormEntry(briefing.form, t2);

  const vs = briefing.venue_stats;
  const h2h = briefing.h2h as { total?: number; note?: string; [k: string]: unknown } | null;
  const t1Wins = h2h ? (h2h[`${t1}_wins`] as number ?? 0) : 0;
  const t2Wins = h2h ? (h2h[`${t2}_wins`] as number ?? 0) : 0;
  const h2hTotal = h2h?.total ?? (t1Wins + t2Wins);

  const parScore = vs?.avg_1st_inn_recent ?? vs?.avg_1st_inn ?? briefing.venue_profile?.avg_score ?? null;
  const hasRecent = vs?.avg_1st_inn_recent != null && vs?.avg_1st_inn != null
    && Math.abs((vs.avg_1st_inn_recent ?? 0) - (vs.avg_1st_inn ?? 0)) >= 10;
  const chaseWin = vs?.chase_win_pct ?? null;
  const tossField = vs?.toss_field_pct ?? null;

  const venueName = vs?.name ?? briefing.venue_profile?.name ?? "";
  const city = vs?.city ?? "";
  const venueLabel = city && venueName ? `${venueName}, ${city}` : venueName || city;

  return (
    <div className="wr-br-mh">
      {/* Left: Team 1 */}
      <div className="wr-br-mh-team">
        <span className="wr-br-mh-name" style={{ color: `var(--${t1Lower})` }}>{t1}</span>
        {f1 && (
          <span className="wr-br-mh-record">{f1.wins}W {f1.losses}L &middot; {typeof f1.nrr === "string" ? f1.nrr : (f1.nrr > 0 ? "+" : "") + f1.nrr}</span>
        )}
        {f1?.last5 && f1.last5.length > 0 && (
          <div className="wr-br-mh-dots">
            {f1.last5.map((r, i) => (
              <span key={i} className={`wr-br-fo-dot ${r === "W" ? "w" : "l"}`} />
            ))}
          </div>
        )}
      </div>

      {/* Center: Venue stats */}
      <div className="wr-br-mh-center">
        <div className="wr-br-mh-stats">
          {parScore != null && (
            <div className="wr-br-mh-stat">
              <span className="wr-br-mh-stat-val">
                {parScore}{hasRecent && <span className="wr-br-stat-trend">*</span>}
              </span>
              <span className="wr-br-mh-stat-lbl">PAR</span>
            </div>
          )}
          {chaseWin != null && (
            <div className="wr-br-mh-stat">
              <span className="wr-br-mh-stat-val">{chaseWin}%</span>
              <span className="wr-br-mh-stat-lbl">CHASE</span>
            </div>
          )}
          {h2hTotal > 0 && (
            <div className="wr-br-mh-stat">
              <span className="wr-br-mh-stat-val">{t1Wins}&ndash;{t2Wins}</span>
              <span className="wr-br-mh-stat-lbl">H2H</span>
            </div>
          )}
          {tossField != null && (
            <div className="wr-br-mh-stat">
              <span className="wr-br-mh-stat-val">{tossField}%</span>
              <span className="wr-br-mh-stat-lbl">TOSS→FIELD</span>
            </div>
          )}
        </div>
        <div className="wr-br-mh-venue">
          {venueLabel}
          {briefing.time && <> &middot; {briefing.time}</>}
          {briefing.match_number != null && <> &middot; M{briefing.match_number}</>}
        </div>
      </div>

      {/* Right: Team 2 */}
      <div className="wr-br-mh-team right">
        <span className="wr-br-mh-name" style={{ color: `var(--${t2Lower})` }}>{t2}</span>
        {f2 && (
          <span className="wr-br-mh-record">{f2.wins}W {f2.losses}L &middot; {typeof f2.nrr === "string" ? f2.nrr : (f2.nrr > 0 ? "+" : "") + f2.nrr}</span>
        )}
        {f2?.last5 && f2.last5.length > 0 && (
          <div className="wr-br-mh-dots">
            {f2.last5.map((r, i) => (
              <span key={i} className={`wr-br-fo-dot ${r === "W" ? "w" : "l"}`} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function VenueIntel({ vs }: { vs: WRVenueStats }) {
  const d180 = vs.defend_180_pct;
  const dUnder = vs.defend_under_160_pct;
  const last5 = vs.last_5_1st_inn;

  if (d180 == null && !last5?.length) return null;

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
    </div>
  );
}

function MatchupTab({ briefing, ifTonight }: {
  briefing: WRBriefing;
  ifTonight: WRScenarios["if_tonight"][0] | null;
}) {
  const parts = briefing.match.split(/\s+vs\s+/i);
  const t1 = parts[0]?.trim() ?? "";
  const t2 = parts[1]?.trim() ?? "";
  const t1Lower = t1.toLowerCase();
  const t2Lower = t2.toLowerCase();

  const favoured = briefing.favoured;
  const favouredLower = favoured?.toLowerCase() ?? "";

  return (
    <div className="wr-br wr-br-grid">
      {/* ── Left: Tactical Edge + Tonight's Stakes ── */}
      <div className="wr-br-main">
        {briefing.tactical_edge && (
          <div
            className="wr-br-edge"
            style={favoured && favoured !== "even"
              ? { borderLeftColor: `var(--${favouredLower})` }
              : undefined
            }
          >
            <div className="wr-br-edge-hd">
              <span className="wr-br-edge-label">Tactical Edge</span>
              {favoured && favoured !== "even" && (
                <span className="wr-br-edge-badge" style={{ background: `var(--${favouredLower})` }}>
                  {favoured} FAVOURED
                </span>
              )}
              {favoured === "even" && (
                <span className="wr-br-edge-badge even">EVEN CONTEST</span>
              )}
            </div>
            <div className="wr-br-edge-text">{briefing.tactical_edge}</div>
          </div>
        )}

        {ifTonight && ifTonight.scenarios.length >= 2 && (
          <div className="wr-br-section">
            <div className="wr-br-whatif-label">Tonight&rsquo;s Stakes</div>
            {ifTonight.scenarios.map((s, i) => {
              const isT1 = s.result.toLowerCase().includes(t1Lower);
              const winTeam = isT1 ? t1 : t2;
              const teamVar = isT1 ? t1Lower : t2Lower;
              return (
                <div key={i} className="wr-br-stake" style={{ ["--tc" as string]: `var(--${teamVar})` }}>
                  <div className="wr-br-stake-team" style={{ color: `var(--${teamVar})` }}>{winTeam} win</div>
                  <div className="wr-br-stake-impact">{s.impact}</div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Right: Key Matchups — Battle Cards ── */}
      <div className="wr-br-sidebar">
        {briefing.key_matchups.length > 0 && (
          <div className="wr-br-section">
            <div className="wr-br-label">Key Matchups</div>
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
              )
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function IntelTab({ briefing, previewLinks = [] }: {
  briefing: WRBriefing;
  previewLinks?: { title: string; url: string }[];
}) {
  const parts = briefing.match.split(/\s+vs\s+/i);
  const t1 = parts[0]?.trim() ?? "";
  const t2 = parts[1]?.trim() ?? "";
  const t1Lower = t1.toLowerCase();
  const t2Lower = t2.toLowerCase();

  const f1 = getFormEntry(briefing.form, t1);
  const f2 = getFormEntry(briefing.form, t2);

  return (
    <div className="wr-br wr-br-grid">
      {/* ── Left: Squad Intel ── */}
      <div className="wr-br-main">
        {briefing.squad_news.length > 0 && (
          <div className="wr-br-section">
            <div className="wr-br-label">Squad Intel <span className="wr-br-via">RSS</span></div>
            {briefing.squad_news.map((item, i) => (
              <div key={i} className="wr-br-item">{item}</div>
            ))}
          </div>
        )}
      </div>

      {/* ── Right: Form & Momentum + ESPNcricinfo ── */}
      <div className="wr-br-sidebar">
        {(f1 || f2) && (
          <div className="wr-br-section">
            <div className="wr-br-label">Form &amp; Momentum</div>
            {[{ team: t1, form: f1, lower: t1Lower }, { team: t2, form: f2, lower: t2Lower }]
              .filter((x) => x.form)
              .map(({ team, form: f, lower }) => {
                const nrr = typeof f!.nrr === "number" ? f!.nrr : parseFloat(String(f!.nrr));
                const mood = nrr > 0 ? "rising" : nrr < -0.5 ? "falling" : "steady";
                return (
                  <div key={team} className={`wr-br-form-card ${mood}`}>
                    <div className="wr-br-form-hd">
                      <span className="wr-br-form-team" style={{ color: `var(--${lower})` }}>{team}</span>
                      <span className={`wr-br-form-mood ${mood}`}>
                        {mood === "rising" ? "▲" : mood === "falling" ? "▼" : "▸"}
                      </span>
                      <span className="wr-br-form-pos">#{f!.position}</span>
                    </div>
                    {f!.trend && <div className="wr-br-form-trend">{f!.trend}</div>}
                  </div>
                );
              })}
          </div>
        )}

        {previewLinks.length > 0 && (
          <div className="wr-br-section wr-br-links">
            <div className="wr-br-label">On ESPNcricinfo</div>
            {previewLinks.map((link, i) => (
              <a key={i} href={link.url} target="_blank" rel="noopener noreferrer" className="wr-br-link-card">
                <span className="wr-br-link-title">{link.title}</span>
                <span className="wr-br-link-arrow">&#x2197;</span>
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function GroundTab({ briefing }: { briefing: WRBriefing }) {
  const vs = briefing.venue_stats;
  const h2h = briefing.h2h as { note?: string; [k: string]: unknown } | null;

  if (!vs) {
    return <div className="wr-br"><div className="wr-empty">No venue data available</div></div>;
  }

  // Pitch character: batting paradise / balanced / bowler-friendly
  const avg = vs.avg_1st_inn_recent ?? vs.avg_1st_inn ?? 0;
  const pitchChar = avg >= 185 ? "Batting Paradise" : avg >= 160 ? "Balanced" : "Bowler-Friendly";
  const pitchColor = avg >= 185 ? "var(--wr-win)" : avg >= 160 ? "var(--wr-brand)" : "var(--wr-loss)";

  return (
    <div className="wr-br wr-br-grid wr-ground-tab">
      {/* ── Left: Venue identity + scoring ── */}
      <div className="wr-br-main">
        {/* Venue header card */}
        <div className="wr-gnd-header">
          <div className="wr-gnd-name">{vs.name}</div>
          <div className="wr-gnd-city">{vs.city}</div>
          <div className="wr-gnd-char" style={{ color: pitchColor }}>{pitchChar}</div>
          <div className="wr-gnd-matches">{vs.matches ?? 0} IPL matches</div>
        </div>

        {/* Key venue numbers */}
        <div className="wr-gnd-stats">
          {vs.avg_1st_inn != null && (
            <div className="wr-gnd-stat">
              <span className="wr-gnd-stat-val">{vs.avg_1st_inn}</span>
              <span className="wr-gnd-stat-lbl">AVG 1ST INN</span>
            </div>
          )}
          {vs.avg_2nd_inn != null && (
            <div className="wr-gnd-stat">
              <span className="wr-gnd-stat-val">{vs.avg_2nd_inn}</span>
              <span className="wr-gnd-stat-lbl">AVG 2ND INN</span>
            </div>
          )}
          {vs.highest != null && (
            <div className="wr-gnd-stat">
              <span className="wr-gnd-stat-val">{vs.highest}</span>
              <span className="wr-gnd-stat-lbl">HIGHEST</span>
            </div>
          )}
          {vs.lowest != null && (
            <div className="wr-gnd-stat">
              <span className="wr-gnd-stat-val">{vs.lowest}</span>
              <span className="wr-gnd-stat-lbl">LOWEST</span>
            </div>
          )}
        </div>

        {/* Defend thresholds + last 5 */}
        <div className="wr-br-section">
          <div className="wr-br-label">Scoring Profile</div>
          <VenueIntel vs={vs} />
        </div>
      </div>

      {/* ── Right: Pitch report + H2H ── */}
      <div className="wr-br-sidebar">
        {vs.note && (
          <div className="wr-br-section">
            <div className="wr-br-label">Pitch Report</div>
            <div className="wr-br-ground-note">{vs.note}</div>
          </div>
        )}

        {h2h?.note && (
          <div className="wr-br-section">
            <div className="wr-br-label">Head to Head</div>
            <div className="wr-br-ground-note">{h2h.note}</div>
          </div>
        )}
      </div>
    </div>
  );
}

function ScoutTab({ dossiers }: { dossiers: WRDossier[] }) {
  const lvlClass = (n: number) =>
    n >= 7 ? "high" : n >= 4 ? "mid" : "low";
  const lvlLabel = (n: number) =>
    n >= 7 ? "HIGH" : n >= 4 ? "MED" : "LOW";

  const TeamDossier = ({ dossier }: { dossier: WRDossier }) => (
    <div className="wr-dos-team-col">
      <div className="wr-dos-opp-chip">SCOUTING {dossier.opponent}</div>

      {/* Threat levels — unit-level only */}
      <div className="wr-dos-threat-summary">
        <div className="wr-dos-dept-row">
          <span className="wr-dos-dept">BATTING</span>
          <span className={`wr-dos-lvl ${lvlClass(dossier.batting_threat)}`}>
            {lvlLabel(dossier.batting_threat)} &middot; {dossier.batting_threat}/10
          </span>
        </div>
        <div className="wr-dos-dept-row">
          <span className="wr-dos-dept">BOWLING</span>
          <span className={`wr-dos-lvl ${lvlClass(dossier.bowling_threat)}`}>
            {lvlLabel(dossier.bowling_threat)} &middot; {dossier.bowling_threat}/10
          </span>
        </div>
      </div>

      {dossier.weaknesses && dossier.weaknesses.length > 0 && (
        <div className="wr-dos-weak">
          <div className="wr-dos-weak-hd">Weaknesses</div>
          {dossier.weaknesses.map((w, i) => (
            <div key={i} className="wr-dos-weak-item">{w}</div>
          ))}
        </div>
      )}

      {dossier.how_to_win.length > 0 && (
        <div className="wr-dos-win">
          <div className="wr-dos-win-hd">How to Win</div>
          {dossier.how_to_win.slice(0, 3).map((h, i) => (
            <div key={i} className="wr-dos-win-item">
              <span className="wr-dos-win-num">{i + 1}</span>
              <span>{h}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  if (!dossiers.length) {
    return <div className="wr-br"><div className="wr-empty">No scouting data available</div></div>;
  }

  return (
    <div className="wr-br wr-br-grid wr-scout-grid">
      {dossiers.map((d) => (
        <TeamDossier key={d.opponent} dossier={d} />
      ))}
    </div>
  );
}

export function BriefingPanel() {
  const { briefings, scenarios, dossiers } = useWarRoomState();
  const [activeIdx, setActiveIdx] = useState(0);
  const [contentTab, setContentTab] = useState<BriefingTab>("matchup");

  const safeIdx = briefings && briefings.length > 0
    ? Math.min(activeIdx, briefings.length - 1)
    : 0;
  const briefing = briefings?.[safeIdx] ?? null;

  // Reset content tab when match tab changes
  useEffect(() => { setContentTab("matchup"); }, [safeIdx]);

  // Parse team shorts from "DC vs MI" → ["DC", "MI"]
  const [team1Short, team2Short] = useMemo((): [string, string] => {
    if (!briefing?.match) return ["", ""];
    const parts = briefing.match.split(/\s+vs\s+/i).map((t) => t.trim());
    return [parts[0] ?? "", parts[1] ?? ""];
  }, [briefing?.match]);

  const dossierT1 = useMemo(() => {
    if (!dossiers?.length || !team2Short) return null;
    return dossiers.find((d) => d.opponent.toUpperCase() === team2Short.toUpperCase()) ?? null;
  }, [dossiers, team2Short]);

  const dossierT2 = useMemo(() => {
    if (!dossiers?.length || !team1Short) return null;
    return dossiers.find((d) => d.opponent.toUpperCase() === team1Short.toUpperCase()) ?? null;
  }, [dossiers, team1Short]);

  const ifTonight = useMemo(() => {
    if (!scenarios?.if_tonight?.length || !briefing) return null;
    const teams = briefing.match.split(/\s+vs\s+/i).map((t) => t.trim().toUpperCase());
    return (
      scenarios.if_tonight.find((it) =>
        teams.some((t) => it.match.toUpperCase().includes(t))
      ) ?? scenarios.if_tonight[0]
    );
  }, [briefing?.match, scenarios?.if_tonight]);

  const matchDossiers = useMemo(() => {
    const arr: WRDossier[] = [];
    if (dossierT1) arr.push(dossierT1);
    if (dossierT2) arr.push(dossierT2);
    return arr;
  }, [dossierT1, dossierT2]);

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

  const previewLinks = briefing.preview_links ?? [];
  const tabs: { key: BriefingTab; label: string }[] = [
    { key: "matchup", label: "MATCHUP" },
    { key: "intel", label: "INTEL" },
    { key: "ground", label: "GROUND" },
    ...(matchDossiers.length > 0 ? [{ key: "scout" as BriefingTab, label: "SCOUT" }] : []),
  ];

  return (
    <div className="wr-pnl wr-briefing-pnl">
      {/* ── Panel header — with double-header match pills inline ── */}
      <div className="wr-ph">
        Briefing <sub>PRE-MATCH</sub>
        {briefings.length > 1 && (
          <span className="wr-br-match-pills">
            {briefings.map((b, i) => (
              <button
                key={i}
                className={`wr-br-match-pill ${safeIdx === i ? "on" : ""}`}
                onClick={() => setActiveIdx(i)}
              >
                {b.match}
              </button>
            ))}
          </span>
        )}
      </div>

      {/* ── Combined match header: teams + stats in one row ── */}
      <MatchHeader briefing={briefing} />

      {/* ── Three content tabs: MATCHUP / INTEL / SCOUT ── */}
      <div className="wr-briefing-content-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={`wr-bct${contentTab === tab.key ? " on" : ""}`}
            onClick={() => setContentTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── Scrollable content ── */}
      <div className="wr-briefing-scroll">
        {contentTab === "matchup" && (
          <MatchupTab briefing={briefing} ifTonight={ifTonight} />
        )}
        {contentTab === "intel" && (
          <IntelTab briefing={briefing} previewLinks={previewLinks} />
        )}
        {contentTab === "ground" && (
          <GroundTab briefing={briefing} />
        )}
        {contentTab === "scout" && (
          <ScoutTab dossiers={matchDossiers} />
        )}
      </div>
    </div>
  );
}
