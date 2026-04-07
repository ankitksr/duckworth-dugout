import React, { useRef, useEffect } from "react";
import { useWarRoomState } from "../../hooks/useWarRoom";
import type { WRFixture } from "../../types/war-room";
import { teamInvolved, formatMatchDate } from "../helpers";

export function MatchTimeline() {
  const { schedule, selectedTeam } = useWarRoomState();
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!wrapRef.current) return;
    // Scroll to: first live match, else last completed match
    const anchor =
      wrapRef.current.querySelector<HTMLElement>("[data-anchor]");
    if (anchor) {
      anchor.scrollIntoView({ block: "start" });
    }
  }, [schedule, selectedTeam]);

  if (!schedule) return null;

  const involves = (m: WRFixture) => !selectedTeam || teamInvolved(m, selectedTeam);
  const completed = schedule
    .filter((m) => m.status === "completed" && involves(m))
    .sort((a, b) => a.match_number - b.match_number);
  const live = schedule.filter((m) => m.status === "live" && involves(m));
  const upcoming = schedule.filter((m) => m.status === "scheduled" && involves(m));

  // Anchor: first live match, else last completed match
  const anchorMatch = live.length > 0
    ? live[0].match_number
    : completed.length > 0
      ? completed[completed.length - 1].match_number
      : null;

  const renderStub = (m: WRFixture) => (
    <>
      <div className="wr-tmc-stub">
        <div className="wr-tmc-stub-date">{formatMatchDate(m.date)} · {m.time}</div>
        <div className="wr-tmc-stub-city">{m.city || m.venue} · <span className="wr-tmc-stub-mnum">M{m.match_number}</span></div>
      </div>
      <div className="wr-tmc-sep" />
    </>
  );

  const renderCompleted = (m: WRFixture) => {
    const involves = selectedTeam ? teamInvolved(m, selectedTeam) : false;
    const dim = selectedTeam && !involves;
    const hl = selectedTeam && involves;

    const resultShort = (() => {
      if (!m.result) return null;
      if (!m.winner) return m.result; // "No result", "Tied", etc.
      const winShort = m.winner === m.team1
        ? m.team1.toUpperCase()
        : m.team2.toUpperCase();
      const match = m.result.match(/by (\d+)\s+(run|wicket|super over)/i);
      if (match) {
        const unit = match[2].toLowerCase().startsWith("run") ? "runs" : match[2].toLowerCase().startsWith("wicket") ? "wkts" : "SO";
        return `${winShort} +${match[1]} ${unit}`;
      }
      return m.result;
    })();

    const card = (
      <div
        key={m.match_number}
        className={`wr-tmc ${dim ? "dim" : ""} ${hl ? "hl" : ""}`}
        {...(m.match_number === anchorMatch ? { "data-anchor": "" } : {})}
      >
        {renderStub(m)}
        <div className="wr-tmc-left">
          <div>
            <span className="wr-tmc-t" style={{ ["--tc" as string]: `var(--${m.team1})` }}>{m.team1.toUpperCase()}</span>
            <span className="wr-tmc-vs">VS</span>
            <span className="wr-tmc-t" style={{ ["--tc" as string]: `var(--${m.team2})` }}>{m.team2.toUpperCase()}</span>
          </div>
          {m.score1 && (
            <div className="wr-tmc-detail">{m.score1} vs {m.score2 ?? ""}</div>
          )}
          {resultShort && (
            <div className="wr-tmc-result"><span className={m.winner ? "rr-w" : "rr-nr"}>{resultShort}</span></div>
          )}
        </div>
      </div>
    );

    if (m.match_url) {
      return (
        <a key={m.match_number} href={m.match_url} target="_blank" rel="noopener noreferrer" className="wr-tmc-link">
          {card}
        </a>
      );
    }
    return card;
  };

  const renderLive = (m: WRFixture) => {
    const involves = selectedTeam ? teamInvolved(m, selectedTeam) : false;
    const dim = selectedTeam && !involves;

    const card = (
      <div
        key={m.match_number}
        className={`wr-tmc wr-tmc-live ${dim ? "dim" : ""}`}
        {...(m.match_number === anchorMatch ? { "data-anchor": "" } : {})}
      >
        {renderStub(m)}
        <div className="wr-tmc-left">
          <div>
            <span className="wr-tmc-t" style={{ ["--tc" as string]: `var(--${m.team1})` }}>
              {m.team1.toUpperCase()}
            </span>
            <span className="wr-tmc-vs">VS</span>
            <span className="wr-tmc-t" style={{ ["--tc" as string]: `var(--${m.team2})` }}>
              {m.team2.toUpperCase()}
            </span>
            <span className="wr-tmc-live-badge">LIVE</span>
          </div>
          {m.score1 && (
            <div className="wr-tmc-detail">
              {m.team1.toUpperCase()} {m.score1}{m.overs1 ? ` (${m.overs1})` : ""}
            </div>
          )}
          {m.score2 && (
            <div className="wr-tmc-detail">
              {m.team2.toUpperCase()} {m.score2}{m.overs2 ? ` (${m.overs2})` : ""}
            </div>
          )}
          {(m.current_rr || m.live_forecast) && (
            <div className="wr-tmc-detail wr-tmc-forecast">
              {m.current_rr && <span>CRR {m.current_rr.toFixed(1)}</span>}
              {m.live_forecast && <span> · ↗ {m.live_forecast}</span>}
              {m.required_rr && <span> · RRR {m.required_rr.toFixed(1)}</span>}
            </div>
          )}
          {m.status_text && (
            <div className="wr-tmc-detail" style={{ color: "var(--wr-win)" }}>{m.status_text}</div>
          )}
        </div>
      </div>
    );

    if (m.match_url) {
      return (
        <a key={m.match_number} href={m.match_url} target="_blank" rel="noopener noreferrer" className="wr-tmc-link">
          {card}
        </a>
      );
    }
    return card;
  };

  const renderUpcoming = (m: WRFixture) => {
    const involves = selectedTeam ? teamInvolved(m, selectedTeam) : false;
    const dim = selectedTeam && !involves;
    const hl = selectedTeam && involves;

    return (
      <div
        key={m.match_number}
        className={`wr-tmc ${dim ? "dim" : ""} ${hl ? "hl" : ""}`}
      >
        {renderStub(m)}
        <div className="wr-tmc-left">
          <div>
            <span className="wr-tmc-t" style={{ ["--tc" as string]: `var(--${m.team1})` }}>{m.team1.toUpperCase()}</span>
            <span className="wr-tmc-vs">VS</span>
            <span className="wr-tmc-t" style={{ ["--tc" as string]: `var(--${m.team2})` }}>{m.team2.toUpperCase()}</span>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="wr-pnl wr-matches-pnl">
      <div className="wr-ph">
        Matches{" "}
        <sub>
          {selectedTeam
            ? `${selectedTeam.toUpperCase()} MATCHES`
            : `${upcoming.length + live.length} UPCOMING · ${completed.length} PLAYED`}
        </sub>
      </div>
      <div className="wr-matches-wrap" ref={wrapRef}>
        {completed.map((m) => renderCompleted(m))}
        {live.map((m) => renderLive(m))}
        {(upcoming.length > 0 || live.length > 0) && (
          <div className="wr-match-div">
            <div className="wr-match-div-line" />
            <div className="wr-match-div-label">── UPCOMING ──</div>
          </div>
        )}
        {upcoming.map((m) => renderUpcoming(m))}
      </div>
    </div>
  );
}
