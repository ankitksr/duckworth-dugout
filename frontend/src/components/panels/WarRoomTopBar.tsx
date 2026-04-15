import React, { useState, useEffect } from "react";
import { useWarRoomState, useWarRoomDispatch } from "../../hooks/useWarRoom";
import { istClock } from "../helpers";

export function WarRoomTopBar() {
  const { standings, ticker, schedule } = useWarRoomState();
  const { selectedTeam } = useWarRoomState();
  const dispatch = useWarRoomDispatch();

  const [clock, setClock] = useState(istClock());

  useEffect(() => {
    const id = setInterval(() => setClock(istClock()), 1000);
    return () => clearInterval(id);
  }, []);

  const hasLive = schedule?.some((m) => m.status === "live") ?? false;

  // On mobile, the briefing/team-intel panel sits above the fold. When the
  // user taps a pill from a scrolled position, the swap happens off-screen
  // and there's no visual feedback. After dispatch, scroll the now-mounted
  // panel into view so the user actually lands on the team they selected.
  function handleSelectTeam(franchiseId: string) {
    dispatch({ type: "SELECT_TEAM", payload: franchiseId });
    if (typeof window === "undefined") return;
    if (!window.matchMedia("(max-width: 768px)").matches) return;

    requestAnimationFrame(() => {
      // Selecting the same pill toggles back to BriefingPanel — scroll to
      // whichever panel is now mounted in the center slot.
      const target = document.querySelector(
        ".wr-team-intel-pnl, .wr-briefing-pnl",
      ) as HTMLElement | null;
      target?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }

  return (
    <header className="wr-top">
      <div className="wr-logo">
        <i />
        <span className="wr-logo-brand">DUGOUT</span>
        <span className="wr-logo-sep">·</span>
        <span className="wr-logo-desc wr-logo-desc-full">IPL MONITOR</span>
        <span className="wr-logo-desc wr-logo-desc-short">IPL</span>
      </div>
      <div className="wr-pills">
        {standings?.map((t) => (
          <button
            key={t.franchise_id}
            className={`wr-pill ${selectedTeam === t.franchise_id ? "on" : ""}`}
            style={
              selectedTeam === t.franchise_id
                ? (() => {
                    const c = t.war_room_color ?? t.primary_color;
                    return {
                      color: c,
                      borderColor: c,
                      background: `${c}18`,
                      boxShadow: `0 0 8px ${c}33`,
                    };
                  })()
                : undefined
            }
            onClick={() => handleSelectTeam(t.franchise_id)}
          >
            {t.short_name}
          </button>
        ))}
      </div>
      <div className="wr-tkr">
        <div className="wr-tkr-scroll">
          {(ticker ?? []).map((item, i) => (
            <span key={i}>
              <span className={`wr-tkr-tag wr-tkr-${item.category.toLowerCase()}`}>
                {item.category}
              </span>
              {item.text}
            </span>
          ))}
          {/* Duplicate for seamless loop */}
          {(ticker ?? []).map((item, i) => (
            <span key={`d${i}`}>
              <span className={`wr-tkr-tag wr-tkr-${item.category.toLowerCase()}`}>
                {item.category}
              </span>
              {item.text}
            </span>
          ))}
        </div>
      </div>
      <div className="wr-top-r">
        <span className="wr-clock">{clock}</span>
        {hasLive && (
          <span className="wr-live-badge">
            <i className="wr-live-dot" />
            LIVE
          </span>
        )}
      </div>
    </header>
  );
}
