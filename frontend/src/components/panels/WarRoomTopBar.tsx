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

  return (
    <header className="wr-top">
      <div className="wr-logo">
        <i />
        DUGOUT
      </div>
      <div className="wr-pills">
        {standings?.map((t) => (
          <button
            key={t.franchise_id}
            className={`wr-pill ${selectedTeam === t.franchise_id ? "on" : ""}`}
            style={
              selectedTeam === t.franchise_id
                ? {
                    color: t.primary_color,
                    borderColor: t.primary_color,
                    background: `${t.primary_color}18`,
                    boxShadow: `0 0 8px ${t.primary_color}33`,
                  }
                : undefined
            }
            onClick={() =>
              dispatch({ type: "SELECT_TEAM", payload: t.franchise_id })
            }
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
