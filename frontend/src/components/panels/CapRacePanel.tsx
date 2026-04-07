import React from "react";
import { useWarRoomState, useWarRoomDispatch } from "../../hooks/useWarRoom";
import type { WRCapEntry } from "../../types/war-room";
import { timeAgo } from "../helpers";

export function CapRacePanel() {
  const { caps, capTab, selectedTeam, meta } = useWarRoomState();
  const dispatch = useWarRoomDispatch();
  if (!caps) return null;

  const tabs: { key: "orange" | "purple" | "sr" | "econ" | "mvp"; label: string; color: string; source: string }[] = [
    { key: "orange", label: "Orange", color: "#ff8c00", source: "Runs" },
    { key: "purple", label: "Purple", color: "#9b59b6", source: "Wickets" },
    { key: "mvp", label: "MVP", color: "#f5c518", source: "IPL MVP Points" },
    { key: "sr", label: "SR", color: "#4488ff", source: "Min 30 balls" },
    { key: "econ", label: "Econ", color: "#00e676", source: "Min 2 overs" },
  ];

  const capMap: Record<string, WRCapEntry[]> = {
    orange: caps.orange_cap,
    purple: caps.purple_cap,
    sr: caps.best_sr ?? [],
    econ: caps.best_econ ?? [],
    mvp: caps.mvp ?? [],
  };
  const entries: WRCapEntry[] = capMap[capTab] ?? [];
  const valid = entries.filter((e) => e.team !== "").slice(0, 5);
  const activeTab = tabs.find((t) => t.key === capTab);
  const activeColor = activeTab?.color ?? "#fff";

  const capSourceMap: Record<string, string> = { orange: "orange", purple: "purple", mvp: "mvp", sr: "sr", econ: "econ" };
  const activeSource = caps.sources?.[capSourceMap[capTab] ?? ""];
  const sourceLabel = activeSource?.via
    ? `via ${activeSource.via}`
    : activeTab?.source ?? "";
  const sourceTime = activeSource?.updated
    ? timeAgo(activeSource.updated)
    : caps.updated ? timeAgo(caps.updated) : null;

  return (
    <div className="wr-pnl wr-caps-pnl">
      <div className="wr-ph">
        Cap Race <sub>LEADERBOARDS</sub>
      </div>
      <div className="wr-cap-tabs">
        {tabs.map((t) => (
          <button
            key={t.key}
            className={`wr-cap-tab ${capTab === t.key ? "on" : ""}`}
            onClick={() => dispatch({ type: "SET_CAP_TAB", payload: t.key })}
          >
            <span className="wr-cap-dot" style={{ background: t.color }} />
            {t.label}
          </button>
        ))}
      </div>
      <div className="wr-cap-body">
        {valid.length === 0 && (
          <div className="wr-empty">No data yet — awaiting first results</div>
        )}
        {valid.map((e, i) => (
          <div
            key={i}
            className={`wr-cap-row ${i === 0 ? "leader" : ""}`}
            style={{
              opacity: selectedTeam && selectedTeam !== e.team ? 0.3 : 1,
              ...(i === 0 ? { "--cap-accent": activeColor } as React.CSSProperties : {}),
            }}
          >
            <span className="wr-cap-rank">{e.rank}</span>
            <span>
              {e.player}
              <span className="wr-cap-team">{e.team_short}</span>
            </span>
            <span
              className="wr-cap-val"
              style={{ color: i === 0 ? activeColor : undefined }}
            >
              {e.stat}
              {e.innings != null && (
                <span className="wr-cap-inn">{e.innings} inn</span>
              )}
            </span>
          </div>
        ))}
      </div>
      {valid.length > 0 && (
        <div className="wr-cap-footer">
          {sourceLabel}
          {sourceTime && <> · {sourceTime}</>}
        </div>
      )}
    </div>
  );
}
