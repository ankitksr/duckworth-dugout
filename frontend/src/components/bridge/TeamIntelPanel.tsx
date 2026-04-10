import React, { useState, useEffect, useMemo } from "react";
import { useWarRoomState } from "../../hooks/useWarRoom";
import type {
  WRFixture,
  WRNarrative,
  WRDossier,
  WRScenarios,
  WRStanding,
  WRRosterPlayer,
  WRAvailability,
  WRAvailabilityEntry,
} from "../../types/war-room";
import { teamInvolved, formatMatchDate } from "../helpers";

type TeamTab = "arc" | "form" | "squad" | "scout";

// ── Persistent Hero (visible across all tabs) ──

function TeamHero({
  team,
  narrative,
  standing,
  schedule,
  availability,
}: {
  team: string;
  narrative: WRNarrative | null;
  standing: WRStanding | null;
  schedule: WRFixture[] | null;
  availability: WRAvailability | null;
}) {
  const wins = standing?.wins ?? 0;
  const losses = standing?.losses ?? 0;
  const nrs = standing?.no_results ?? 0;

  // Last 5 form dots
  const last5 = useMemo(() => {
    if (!schedule) return [];
    return schedule
      .filter((m) => m.status === "completed" && teamInvolved(m, team))
      .sort((a, b) => a.match_number - b.match_number)
      .slice(-5)
      .map((m) => (m.winner === team ? "w" : m.winner ? "l" : "nr"));
  }, [schedule, team]);

  // Last completed fixture for "Last: ..." line
  const lastFixture = useMemo(() => {
    if (!schedule) return null;
    const completed = schedule
      .filter((m) => m.status === "completed" && teamInvolved(m, team))
      .sort((a, b) => a.match_number - b.match_number);
    return completed.length > 0 ? completed[completed.length - 1] : null;
  }, [schedule, team]);

  // Injury counts (drives the hero chip)
  const teamInjuries = useMemo(() => {
    const list = availability?.by_team?.[team] ?? [];
    return {
      out: list.filter((p) => p.status === "out").length,
      doubtful: list.filter((p) => p.status === "doubtful").length,
    };
  }, [availability, team]);

  let lastLine: string | null = null;
  if (lastFixture) {
    const opp = lastFixture.team1 === team ? lastFixture.team2 : lastFixture.team1;
    const oppU = opp.toUpperCase();
    if (lastFixture.winner === team) lastLine = `beat ${oppU}`;
    else if (lastFixture.winner) lastLine = `lost to ${oppU}`;
    else lastLine = `NR vs ${oppU}`;
  }

  const nextOpp = narrative?.next_test?.opponent?.toUpperCase() ?? null;
  const totalInjuries = teamInjuries.out + teamInjuries.doubtful;
  const hasBuffer = !!narrative?.buffer;

  return (
    <div className={`wr-ti-hero${hasBuffer ? " has-buffer" : ""}`}>
      {/* IDENTITY column */}
      <div className="wr-ti-hero-col wr-ti-hc-identity">
        {narrative && (
          <div className="wr-ti-hero-hd">
            <span className="wr-ti-hero-mood">{narrative.mood_symbol}</span>
            <span className="wr-ti-hero-title">
              &ldquo;{narrative.title}&rdquo;
            </span>
          </div>
        )}
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
            {last5.length > 0 && (
              <span className="wr-ti-hv-dots">
                {last5.map((r, i) => (
                  <span key={i} className={`wr-ti-dot ${r}`} />
                ))}
              </span>
            )}
          </div>
        )}
      </div>

      {/* CONTEXT column */}
      <div className="wr-ti-hero-col wr-ti-hc-context">
        {nextOpp && (
          <div className="wr-ti-hero-line">
            <span className="wr-ti-hero-lbl">Next</span>
            <span className="wr-ti-hero-val">vs {nextOpp}</span>
          </div>
        )}
        {lastLine && (
          <div className="wr-ti-hero-line">
            <span className="wr-ti-hero-lbl">Last</span>
            <span className="wr-ti-hero-val">{lastLine}</span>
          </div>
        )}
        {totalInjuries > 0 && (
          <span
            className={`wr-ti-hv-injury ${teamInjuries.out > 0 ? "out" : "doubt"}`}
          >
            {teamInjuries.out > 0 && (
              <>&#9888; {teamInjuries.out} OUT</>
            )}
            {teamInjuries.out > 0 && teamInjuries.doubtful > 0 && " \u00b7 "}
            {teamInjuries.doubtful > 0 && `${teamInjuries.doubtful} DOUBT`}
          </span>
        )}
      </div>

      {/* STRATEGIC column — only when narrative.buffer is present */}
      {hasBuffer && narrative && (
        <div className="wr-ti-hero-col wr-ti-hc-strategic">
          <span className="wr-ti-buffer-tag">
            {narrative.buffer_tag ?? "POSITION"}
          </span>
          <p className="wr-ti-buffer-body">{narrative.buffer}</p>
        </div>
      )}
    </div>
  );
}

// ── ARC Tab (identity + qualification context) ──

function ArcTab({
  team,
  narrative,
  scenarios,
}: {
  team: string;
  narrative: WRNarrative | null;
  scenarios: WRScenarios | null;
}) {
  const teamElim = scenarios?.elimination_watch?.find(
    (e) => e.team.toUpperCase() === team.toUpperCase(),
  );

  return (
    <>
      {/* Arc + Next Test: dual-column */}
      {narrative && (
        <div className="wr-ti-cols">
          <div className="wr-ti-col">
            <div className="wr-ti-sh">Season Arc</div>
            {narrative.arc_bullets && narrative.arc_bullets.length > 0 ? (
              <div className="wr-ti-hero-bullets">
                {narrative.arc_bullets.map((bullet, i) => (
                  <p key={i} className="wr-ti-hero-bullet">
                    {bullet}
                  </p>
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
                    {team.toUpperCase()} vs{" "}
                    {narrative.next_test.opponent.toUpperCase()}
                  </span>
                  {narrative.next_test.match_number > 0 && (
                    <span className="wr-ti-next-mn">
                      M{narrative.next_test.match_number}
                    </span>
                  )}
                </div>
                <p className="wr-ti-next-ctx">{narrative.next_test.context}</p>
              </div>
              <div className="wr-ti-next-card">
                <div className="wr-ti-next-matchup">
                  <span className="wr-ti-next-vs">Playoff Path</span>
                </div>
                <p className="wr-ti-next-ctx">
                  {narrative.next_test.playoff_path}
                </p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Elimination Watch (full width) */}
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
    </>
  );
}

// ── FORM Tab (results, upcoming, playoff path) ──

function FormTab({
  team,
  teamMatches,
  schedule,
  standing,
}: {
  team: string;
  teamMatches: WRFixture[];
  schedule: WRFixture[] | null;
  standing: WRStanding | null;
}) {
  const upcoming = useMemo(() => {
    if (!schedule) return [];
    return schedule
      .filter((m) => m.status === "scheduled" && teamInvolved(m, team))
      .sort((a, b) => a.match_number - b.match_number)
      .slice(0, 3);
  }, [schedule, team]);

  const wins = standing?.wins ?? 0;
  const losses = standing?.losses ?? 0;
  const nrs = standing?.no_results ?? 0;
  const played = standing?.played ?? 0;
  const remaining = 14 - played;
  const winsNeeded = Math.max(0, 8 - wins);
  const pathText =
    remaining <= 0
      ? "Season complete"
      : winsNeeded <= 0
        ? `On track \u2014 ${remaining} to play`
        : `Need ${winsNeeded}W from ${remaining} remaining`;

  return (
    <div className="wr-ti-grid">
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
                const myScore = m.team1 === team ? m.score1 : m.score2;
                const oppScore = m.team1 === team ? m.score2 : m.score1;
                const scoreStr =
                  myScore && oppScore ? `${myScore} \u2013 ${oppScore}` : "";

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
                    {m.note && <span className="wr-ti-r-note">{m.note}</span>}
                  </a>
                );
              })}
            </div>
          )}
        </div>
      </div>

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

        {standing && (
          <div className="wr-ti-section">
            <div className="wr-ti-sh">Playoff Path</div>
            <div className="wr-ti-bar">
              {Array.from({ length: 14 }, (_, i) => {
                const cls =
                  i < wins
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
      </div>
    </div>
  );
}

// ── SQUAD Tab (full roster + injury watch) ──

function SquadTab({
  roster,
  availability,
}: {
  roster: WRRosterPlayer[];
  availability: WRAvailabilityEntry[];
}) {
  const injuryByName = useMemo(() => {
    const map = new Map<string, WRAvailabilityEntry>();
    availability.forEach((a) => map.set(a.player, a));
    return map;
  }, [availability]);

  const captain = roster.find((p) => p.is_captain);
  const overseasCount = roster.filter((p) => p.is_overseas).length;
  const injured = availability.filter((a) => a.status !== "available");

  const captainShort = captain
    ? captain.player.split(" ").slice(-1)[0]
    : "";

  return (
    <div className="wr-ti-grid">
      {/* LEFT — full roster sorted by price desc */}
      <div className="wr-ti-main">
        <div className="wr-ti-section">
          <div className="wr-ti-sh">
            Squad
            <span className="wr-ti-squad-meta">
              {roster.length} players &middot; {overseasCount} overseas
              {captainShort && <> &middot; capt {captainShort}</>}
            </span>
          </div>
          <div className="wr-ti-squad-list">
            {roster.map((p) => {
              const inj = injuryByName.get(p.player);
              const cls = [
                "wr-ti-sq-row",
                p.is_captain ? "captain" : "",
                p.is_overseas && !p.is_captain ? "overseas" : "",
                inj?.status === "out" ? "out" : "",
                inj?.status === "doubtful" ? "doubt" : "",
              ]
                .filter(Boolean)
                .join(" ");
              const priceCr = p.price_inr
                ? `\u20B9${(p.price_inr / 1e7).toFixed(1)}Cr`
                : "\u2014";
              const acq =
                p.acquisition_type === "retained"
                  ? "ret"
                  : p.acquisition_type === "rtm"
                    ? "rtm"
                    : p.acquisition_type === "auction"
                      ? "auc"
                      : "";
              return (
                <div key={p.player} className={cls}>
                  <span className="wr-ti-sq-badge">
                    {p.is_captain ? "C" : p.is_overseas ? "\u2605" : ""}
                  </span>
                  <span className="wr-ti-sq-name">{p.player}</span>
                  <span className="wr-ti-sq-price">{priceCr}</span>
                  <span className="wr-ti-sq-acq">{acq}</span>
                  <span className="wr-ti-sq-apps">
                    {p.appearances > 0 ? `${p.appearances}m` : "\u2014"}
                  </span>
                  {inj && inj.status !== "available" && (
                    <span className={`wr-ti-sq-inj-badge ${inj.status}`}>
                      {inj.status === "out" ? "OUT" : "DOUBT"}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* RIGHT — injury watch detail */}
      <div className="wr-ti-side">
        <div className="wr-ti-section">
          <div className="wr-ti-sh">Injury Watch</div>
          {injured.length === 0 ? (
            <div className="wr-ti-empty">All players available</div>
          ) : (
            <div className="wr-ti-sq-injuries">
              {injured.map((inj) => (
                <div key={inj.player} className={`wr-ti-sq-inj ${inj.status}`}>
                  <div className="wr-ti-sq-inj-hd">
                    <span className={`wr-ti-sq-inj-tag ${inj.status}`}>
                      {inj.status.toUpperCase()}
                    </span>
                    <span className="wr-ti-sq-inj-name">{inj.player}</span>
                  </div>
                  {inj.reason && (
                    <div className="wr-ti-sq-inj-reason">{inj.reason}</div>
                  )}
                  {inj.expected_return && (
                    <div className="wr-ti-sq-inj-eta">
                      exp: {inj.expected_return}
                    </div>
                  )}
                  {inj.quote && (
                    <div className="wr-ti-sq-inj-quote">
                      &ldquo;{inj.quote}&rdquo;
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── SCOUT Tab (opposition dossier — unchanged) ──

function TeamScoutTab({ dossier }: { dossier: WRDossier }) {
  const lvlClass = (n: number) => (n >= 7 ? "high" : n >= 4 ? "mid" : "low");
  const lvlLabel = (n: number) => (n >= 7 ? "HIGH" : n >= 4 ? "MED" : "LOW");

  return (
    <div className="wr-ti-grid">
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
              <div key={i} className="wr-dos-weak-item">
                {w}
              </div>
            ))}
          </div>
        )}
      </div>

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

// ── Main Panel ──

export function TeamIntelPanel() {
  const {
    selectedTeam,
    standings,
    schedule,
    narratives,
    scenarios,
    dossiers,
    roster,
    availability,
  } = useWarRoomState();
  const [activeTab, setActiveTab] = useState<TeamTab>("arc");

  // Reset to ARC when team changes
  useEffect(() => {
    setActiveTab("arc");
  }, [selectedTeam]);

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

  const teamDossier = useMemo(() => {
    if (!selectedTeam || !dossiers?.length) return null;
    return (
      dossiers.find(
        (d) => d.opponent.toUpperCase() === selectedTeam.toUpperCase(),
      ) ?? null
    );
  }, [selectedTeam, dossiers]);

  const teamRoster = useMemo(() => {
    if (!selectedTeam || !roster?.by_team?.[selectedTeam]) return null;
    return [...roster.by_team[selectedTeam]].sort(
      (a, b) => (b.price_inr ?? 0) - (a.price_inr ?? 0),
    );
  }, [selectedTeam, roster]);

  const teamAvailability = useMemo(() => {
    if (!selectedTeam || !availability?.by_team?.[selectedTeam]) return [];
    return availability.by_team[selectedTeam];
  }, [selectedTeam, availability]);

  if (!selectedTeam) return null;

  const tc = `var(--${selectedTeam})`;

  type TabSpec = { key: TeamTab; label: string; hasData?: boolean };
  const tabs: TabSpec[] = [
    { key: "arc", label: "ARC" },
    { key: "form", label: "FORM" },
    ...(teamRoster
      ? [{ key: "squad" as TeamTab, label: "SQUAD", hasData: true }]
      : []),
    ...(teamDossier
      ? [{ key: "scout" as TeamTab, label: "SCOUT", hasData: true }]
      : []),
  ];

  return (
    <div
      className="wr-pnl wr-team-intel-pnl"
      style={{ ["--tc" as string]: tc }}
    >
      {/* Standard panel header */}
      <div className="wr-ph">
        Team File <sub>{selectedTeam.toUpperCase()}</sub>
      </div>

      {/* Persistent hero — visible across all tabs.
          key={selectedTeam} forces remount on team change so the
          staggered reveal keyframes (.wr-ti-hero-col) re-run. */}
      <TeamHero
        key={selectedTeam}
        team={selectedTeam}
        narrative={teamNarrative}
        standing={standing}
        schedule={schedule}
        availability={availability}
      />

      {/* Tab bar */}
      <div className="wr-briefing-content-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={`wr-bct${activeTab === tab.key ? " on" : ""}${
              tab.hasData ? " has-data" : ""
            }`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Scrollable tab content */}
      <div className="wr-team-intel-scroll">
        {activeTab === "arc" && (
          <ArcTab
            team={selectedTeam}
            narrative={teamNarrative}
            scenarios={scenarios}
          />
        )}
        {activeTab === "form" && (
          <FormTab
            team={selectedTeam}
            teamMatches={teamMatches}
            schedule={schedule}
            standing={standing}
          />
        )}
        {activeTab === "squad" && teamRoster && (
          <SquadTab roster={teamRoster} availability={teamAvailability} />
        )}
        {activeTab === "scout" && teamDossier && (
          <TeamScoutTab dossier={teamDossier} />
        )}
      </div>
    </div>
  );
}
