import React, { useState, useEffect, useMemo } from "react";
import { useWarRoomState } from "../../hooks/useWarRoom";
import type {
  WRFixture, WRNarrative, WRDossier, WRScenarios,
  WRPulseTeam, WRRecordEntry, WRRecords, WRIfTonight,
} from "../../types/war-room";
import { teamInvolved, formatMatchDate } from "../helpers";

type TeamTab = "arc" | "form" | "scout";

function NarrativeSection({ narrative }: { narrative: WRNarrative }) {
  return (
    <div className="wr-si-section wr-si-narrative">
      <div className="wr-si-arc-header">
        <span className="wr-si-arc-title">&ldquo;{narrative.title}&rdquo;</span>
        <span className={`wr-si-mood ${narrative.mood}`}>{narrative.mood_symbol}</span>
      </div>
      <div className="wr-si-arc-body">{narrative.narrative}</div>
      <div className="wr-si-arc-question">{narrative.key_question}</div>
    </div>
  );
}

function CampaignResults({ teamId, matches }: { teamId: string; matches: WRFixture[] }) {
  if (matches.length === 0) return null;
  return (
    <div className="wr-si-section">
      <div className="wr-si-sh">Results</div>
      <div className="wr-campaign">
        {matches.map((m) => {
          const opponent = m.team1 === teamId ? m.team2 : m.team1;
          const won = m.winner === teamId;
          const resultTag = m.winner ? (won ? "W" : "L") : "NR";
          return (
            <div key={m.match_number} className="wr-camp-match">
              <div className="wr-camp-num">M{m.match_number}</div>
              <div className="wr-camp-body">
                <div className="wr-camp-top">
                  <span className="wr-camp-teams">
                    vs <span style={{ color: "var(--wr-t2)" }}>{opponent.toUpperCase()}</span>
                  </span>
                  <span className={`wr-camp-result ${resultTag === "W" ? "w" : "l"}`}>{resultTag}</span>
                </div>
                <div className="wr-camp-detail">
                  {m.score1 ?? ""} vs {m.score2 ?? ""}
                  {m.hero_name && <> &middot; &#x2605; {m.hero_name}</>}
                  {m.hero_stat && <> {m.hero_stat}</>}
                </div>
                <div className="wr-camp-detail">
                  {m.city || m.venue} &middot; {formatMatchDate(m.date)}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ArcTab({
  team, narrative, standing, scenarios, records, schedule, wire,
}: {
  team: string;
  narrative: WRNarrative | null;
  standing: { position: number; points: number; nrr: string; wins: number; losses: number; no_results: number; played: number } | null;
  scenarios: WRScenarios | null;
  records: WRRecords | null;
  schedule: WRFixture[] | null;
  wire: { headline: string; category: string; severity: string; teams: string[]; emoji: string }[];
}) {
  const wins = standing?.wins ?? 0;
  const losses = standing?.losses ?? 0;
  const nrs = standing?.no_results ?? 0;
  const played = standing?.played ?? 0;
  const remaining = 14 - played;
  const winsNeeded = Math.max(0, 8 - wins);

  const pathText = remaining <= 0
    ? "Season complete"
    : winsNeeded <= 0
      ? `On track \u2014 ${remaining} to play`
      : `Need ${winsNeeded}W from ${remaining} remaining`;

  const teamElim = scenarios?.elimination_watch?.find(
    (e) => e.team.toUpperCase() === team.toUpperCase()
  );

  const ifTonight = useMemo(() => {
    if (!scenarios?.if_tonight?.length || !schedule) return null;
    const todayScheduled = schedule.filter(
      (m) => (m.status === "scheduled" || m.status === "live") && teamInvolved(m, team)
    );
    if (todayScheduled.length === 0) return null;
    return (
      scenarios.if_tonight.find((it) =>
        it.match.toUpperCase().includes(team.toUpperCase())
      ) ?? null
    );
  }, [scenarios?.if_tonight, schedule, team]);

  const teamRecords = useMemo(() => {
    if (!records) return [];
    const items: { label: string; entry: WRRecordEntry }[] = [];
    (records.imminent ?? []).forEach((r) => {
      if (r.team?.toUpperCase() === team.toUpperCase())
        items.push({ label: "IMMINENT", entry: r });
    });
    (records.on_track ?? []).forEach((r) => {
      if (r.team?.toUpperCase() === team.toUpperCase())
        items.push({ label: "ON TRACK", entry: r });
    });
    return items;
  }, [records, team]);

  // Team-filtered wire dispatches (max 3)
  const teamWire = useMemo(() => {
    return wire
      .filter((w) => w.teams.includes(team))
      .slice(0, 3);
  }, [wire, team]);

  // Last 5 form dots (computed from schedule)
  const last5 = useMemo(() => {
    if (!schedule) return [];
    return schedule
      .filter((m) => m.status === "completed" && teamInvolved(m, team))
      .sort((a, b) => a.match_number - b.match_number)
      .slice(-5)
      .map((m) => (m.winner === team ? "w" : m.winner ? "l" : "nr"));
  }, [schedule, team]);

  return (
    <>
      {/* ── Hero: buffer + title/vitals (full width) ── */}
      <div className="wr-ti-hero">
        {narrative && (
          <>
            <div className="wr-ti-hero-hd">
              <span className="wr-ti-hero-mood">{narrative.mood_symbol}</span>
              <span className="wr-ti-hero-title">&ldquo;{narrative.title}&rdquo;</span>
            </div>
            {standing && (
              <div className="wr-ti-hero-vitals">
                <span className="wr-ti-hv">#{standing.position}</span>
                <span className="wr-ti-hv-sep">&middot;</span>
                <span className="wr-ti-hv">{standing.points} pts</span>
                <span className="wr-ti-hv-sep">&middot;</span>
                <span className="wr-ti-hv">{standing.nrr}</span>
                <span className="wr-ti-hv-sep">&middot;</span>
                <span className="wr-ti-hv">
                  {wins}W-{losses}L{nrs > 0 ? `-${nrs}NR` : ""}
                </span>
                <span className="wr-ti-hv-dots">
                  {last5.map((r, i) => (
                    <span key={i} className={`wr-ti-dot ${r}`} />
                  ))}
                </span>
              </div>
            )}
            {narrative.buffer && (
              <div className="wr-ti-buffer-inline">
                <span className="wr-ti-buffer-tag">{narrative.buffer_tag ?? "POSITION"}</span>
                <p className="wr-ti-buffer-body">{narrative.buffer}</p>
              </div>
            )}
          </>
        )}
      </div>

      {/* ── Arc + Next Test: dual-column ── */}
      {narrative && (
        <div className="wr-ti-cols">
          <div className="wr-ti-col">
            <div className="wr-ti-sh">Season Arc</div>
            {narrative.arc_bullets && narrative.arc_bullets.length > 0 ? (
              <div className="wr-ti-hero-bullets">
                {narrative.arc_bullets.map((bullet, i) => (
                  <p key={i} className="wr-ti-hero-bullet">{bullet}</p>
                ))}
              </div>
            ) : (
              <p className="wr-ti-hero-body">{narrative.narrative}</p>
            )}
            <p className="wr-ti-hero-q">{narrative.key_question}</p>
          </div>

          {narrative.next_test && (
            <div className="wr-ti-col">
              <div className="wr-ti-sh">Next Test</div>
              <div className="wr-ti-next-card">
                <div className="wr-ti-next-matchup">
                  <span className="wr-ti-next-vs">
                    {team.toUpperCase()} vs {narrative.next_test.opponent.toUpperCase()}
                  </span>
                  {narrative.next_test.match_number > 0 && (
                    <span className="wr-ti-next-mn">M{narrative.next_test.match_number}</span>
                  )}
                </div>
                <p className="wr-ti-next-ctx">{narrative.next_test.context}</p>
              </div>
              <div className="wr-ti-next-card">
                <div className="wr-ti-next-matchup">
                  <span className="wr-ti-next-vs">Playoff Path</span>
                </div>
                <p className="wr-ti-next-ctx">{narrative.next_test.playoff_path}</p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Two-column grid below hero ── */}
      <div className="wr-ti-grid">
        {/* Left: Playoff Path + If Tonight */}
        <div className="wr-ti-main">
          {standing && (
            <div className="wr-ti-section">
              <div className="wr-ti-sh">Playoff Path</div>
              <div className="wr-ti-bar">
                {Array.from({ length: 14 }, (_, i) => {
                  const cls = i < wins
                    ? "w"
                    : i < wins + nrs
                      ? "nr"
                      : i < wins + nrs + losses
                        ? "l"
                        : "rem";
                  return <span key={i} className={`wr-ti-bar-slot ${cls}`} />;
                })}
              </div>
              <div className="wr-ti-path-txt">{pathText}</div>
            </div>
          )}

          {teamElim && (
            <div className="wr-ti-section">
              <div className="wr-ti-sh">Elimination Watch</div>
              <div className={`wr-ti-elim ${teamElim.risk}`}>
                <div className="wr-ti-elim-hd">
                  <span className={`wr-ti-elim-badge ${teamElim.risk}`}>
                    {teamElim.risk.toUpperCase()}
                  </span>
                  <span className="wr-ti-elim-metric">{teamElim.key_metric}</span>
                </div>
                <p className="wr-ti-elim-body">{teamElim.insight}</p>
              </div>
            </div>
          )}

          {ifTonight && (
            <div className="wr-ti-section">
              <div className="wr-ti-sh">If Tonight</div>
              <div className="wr-ti-tonight">
                <div className="wr-ti-tonight-match">{ifTonight.match}</div>
                {ifTonight.scenarios.map((s, i) => (
                  <div key={i} className="wr-ti-tonight-row">
                    <span className="wr-ti-tonight-result">{s.result}</span>
                    <span className="wr-ti-tonight-impact">{s.impact}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Right: Wire Dispatches + Milestones */}
        <div className="wr-ti-side">
          {teamWire.length > 0 && (
            <div className="wr-ti-section">
              <div className="wr-ti-sh">Intelligence</div>
              <div className="wr-ti-dispatches">
                {teamWire.map((w, i) => (
                  <div key={i} className={`wr-ti-dispatch ${w.severity}`}>
                    <span className="wr-ti-dispatch-emoji">{w.emoji}</span>
                    <div className="wr-ti-dispatch-body">
                      <span className="wr-ti-dispatch-hl">{w.headline}</span>
                      <span className="wr-ti-dispatch-cat">{w.category.replace(/_/g, " ")}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {teamRecords.length > 0 && (
            <div className="wr-ti-section">
              <div className="wr-ti-sh">Milestones</div>
              <div className="wr-ti-milestones">
                {teamRecords.map((r, i) => (
                  <div key={i} className="wr-ti-milestone">
                    <div className="wr-ti-ms-hd">
                      <span className="wr-ti-ms-name">{r.entry.player}</span>
                      <span className={`wr-ti-ms-badge ${r.label === "IMMINENT" ? "hot" : ""}`}>
                        {r.label}
                      </span>
                    </div>
                    {r.entry.current && r.entry.target && (
                      <div className="wr-ti-ms-progress">
                        {r.entry.current} &#x2192; {r.entry.target}
                      </div>
                    )}
                    <div className="wr-ti-ms-note">{r.entry.note}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function FormTab({
  team, teamMatches, schedule, teamPulse,
}: {
  team: string;
  teamMatches: WRFixture[];
  schedule: WRFixture[] | null;
  teamPulse: WRPulseTeam | null;
}) {
  const upcoming = useMemo(() => {
    if (!schedule) return [];
    return schedule
      .filter((m) => m.status === "scheduled" && teamInvolved(m, team))
      .sort((a, b) => a.match_number - b.match_number)
      .slice(0, 3);
  }, [schedule, team]);

  return (
    <div className="wr-ti-grid">
      {/* ── Left: Season Results ── */}
      <div className="wr-ti-main">
        <div className="wr-ti-section">
          <div className="wr-ti-sh">Season Results</div>
          {teamMatches.length === 0 ? (
            <div className="wr-ti-empty">No completed matches yet</div>
          ) : (
            <div className="wr-ti-results">
              {teamMatches.map((m) => {
                const opp = m.team1 === team ? m.team2 : m.team1;
                const won = m.winner === team;
                const res = m.winner ? (won ? "W" : "L") : "NR";
                // Score orientation: selected team's score first
                const myScore = m.team1 === team ? m.score1 : m.score2;
                const oppScore = m.team1 === team ? m.score2 : m.score1;
                const scoreStr = myScore && oppScore ? `${myScore} \u2013 ${oppScore}` : "";

                return (
                  <a
                    key={m.match_number}
                    className={`wr-ti-result ${res.toLowerCase()}`}
                    href={m.match_url ?? undefined}
                    target={m.match_url ? "_blank" : undefined}
                    rel={m.match_url ? "noopener noreferrer" : undefined}
                  >
                    <span className="wr-ti-r-num">M{m.match_number}</span>
                    <span className="wr-ti-r-opp">vs {opp.toUpperCase()}</span>
                    <span className="wr-ti-r-score">{scoreStr}</span>
                    <span className={`wr-ti-r-res ${res.toLowerCase()}`}>{res}</span>
                    <span className="wr-ti-r-hero">
                      {m.hero_name
                        ? `\u2605 ${m.hero_name}${m.hero_stat ? ` \u00b7 ${m.hero_stat}` : ""}`
                        : ""}
                    </span>
                    {m.note && (
                      <span className="wr-ti-r-note">{m.note}</span>
                    )}
                  </a>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* ── Right: Upcoming + Rank Journey ── */}
      <div className="wr-ti-side">
        <div className="wr-ti-section">
          <div className="wr-ti-sh">Upcoming</div>
          {upcoming.length === 0 ? (
            <div className="wr-ti-empty">No upcoming fixtures</div>
          ) : (
            <div className="wr-ti-upcoming">
              {upcoming.map((m) => {
                const opp = m.team1 === team ? m.team2 : m.team1;
                return (
                  <div key={m.match_number} className="wr-ti-upc-row">
                    <span className="wr-ti-upc-date">{formatMatchDate(m.date)}</span>
                    <span className="wr-ti-upc-opp">vs {opp.toUpperCase()}</span>
                    <span className="wr-ti-upc-venue">{m.city || m.venue}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {teamPulse && teamPulse.snapshots.length > 0 && (
          <div className="wr-ti-section">
            <div className="wr-ti-sh">Rank Journey</div>
            <div className="wr-ti-rank-seq">
              {teamPulse.snapshots.map((s, i) => {
                const prev = i > 0 ? teamPulse.snapshots[i - 1].rank : s.rank;
                const dir = s.rank < prev ? "up" : s.rank > prev ? "down" : "same";
                return (
                  <div key={i} className={`wr-ti-rank-badge ${dir}`} title={`M${s.match} · ${s.result}`}>
                    #{s.rank}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function TeamScoutTab({ dossier }: { dossier: WRDossier }) {
  const lvlClass = (n: number) =>
    n >= 7 ? "high" : n >= 4 ? "mid" : "low";
  const lvlLabel = (n: number) =>
    n >= 7 ? "HIGH" : n >= 4 ? "MED" : "LOW";

  return (
    <div className="wr-ti-grid">
      {/* ── Left: Threat levels + Weaknesses ── */}
      <div className="wr-ti-main">
        <div className="wr-dos-opp-chip">SCOUTING {dossier.opponent}</div>
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
      </div>

      {/* ── Right: How to Win ── */}
      <div className="wr-ti-side">
        {dossier.how_to_win.length > 0 && (
          <div className="wr-dos-win" style={{ paddingTop: 10 }}>
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
    </div>
  );
}

export function TeamIntelPanel() {
  const {
    selectedTeam, standings, schedule, narratives,
    scenarios, records, dossiers, pulse, wire,
  } = useWarRoomState();
  const [activeTab, setActiveTab] = useState<TeamTab>("arc");

  // Reset to ARC when team changes
  useEffect(() => { setActiveTab("arc"); }, [selectedTeam]);

  const teamNarrative = useMemo(() => {
    if (!selectedTeam) return null;
    return narratives.find((n) => n.franchise_id === selectedTeam) ?? null;
  }, [selectedTeam, narratives]);

  const standing = selectedTeam
    ? standings?.find((s) => s.franchise_id === selectedTeam) ?? null
    : null;

  const teamMatches = useMemo(() => {
    if (!selectedTeam || !schedule) return [];
    return schedule
      .filter((m) => m.status === "completed" && teamInvolved(m, selectedTeam))
      .sort((a, b) => a.match_number - b.match_number);
  }, [selectedTeam, schedule]);

  const teamPulse = useMemo(() => {
    if (!selectedTeam || !pulse) return null;
    return pulse.find((p) => p.fid === selectedTeam) ?? null;
  }, [selectedTeam, pulse]);

  const teamDossier = useMemo(() => {
    if (!selectedTeam || !dossiers?.length) return null;
    return dossiers.find(
      (d) => d.opponent.toUpperCase() === selectedTeam.toUpperCase()
    ) ?? null;
  }, [selectedTeam, dossiers]);

  if (!selectedTeam) return null;

  const tc = `var(--${selectedTeam})`;

  const tabs: { key: TeamTab; label: string }[] = [
    { key: "arc", label: "ARC" },
    { key: "form", label: "FORM" },
    ...(teamDossier ? [{ key: "scout" as TeamTab, label: "SCOUT" }] : []),
  ];

  return (
    <div className="wr-pnl wr-team-intel-pnl" style={{ ["--tc" as string]: tc }}>
      {/* ── Standard panel header ── */}
      <div className="wr-ph">
        Team File <sub>{selectedTeam.toUpperCase()}</sub>
      </div>

      {/* ── Content tabs ── */}
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

      {/* ── Scrollable tab content ── */}
      <div className="wr-team-intel-scroll">
        {activeTab === "arc" && (
          <ArcTab
            team={selectedTeam}
            narrative={teamNarrative}
            standing={standing}
            scenarios={scenarios}
            records={records}
            schedule={schedule}
            wire={wire}
          />
        )}
        {activeTab === "form" && (
          <FormTab
            team={selectedTeam}
            teamMatches={teamMatches}
            schedule={schedule}
            teamPulse={teamPulse}
          />
        )}
        {activeTab === "scout" && teamDossier && (
          <TeamScoutTab dossier={teamDossier} />
        )}
      </div>
    </div>
  );
}
