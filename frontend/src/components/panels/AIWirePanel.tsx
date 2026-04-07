import React, { useState, useMemo, useEffect } from "react";
import { useWarRoomState } from "../../hooks/useWarRoom";
import { timeAgo } from "../helpers";

export function AIWirePanel() {
  const { wire, selectedTeam, standings } = useWarRoomState();
  const [expanded, setExpanded] = useState<number | null>(null);

  // Resolve short names for team chips
  const teamShort = useMemo(() => {
    if (!standings) return {};
    const map: Record<string, { short: string; color: string }> = {};
    for (const s of standings) {
      map[s.franchise_id] = { short: s.short_name, color: s.primary_color };
    }
    return map;
  }, [standings]);

  // Float team-relevant entries to top when a team is selected
  const sorted = useMemo(() => {
    if (!selectedTeam) return wire;
    return [...wire].sort((a, b) => {
      const aInv = a.teams?.includes(selectedTeam) ? 0 : 1;
      const bInv = b.teams?.includes(selectedTeam) ? 0 : 1;
      return aInv - bInv;
    });
  }, [wire, selectedTeam]);

  // Reset expanded card when team selection changes
  useEffect(() => { setExpanded(null); }, [selectedTeam]);

  if (!wire || wire.length === 0) {
    return (
      <div className="wr-pnl wr-wire-pnl">
        <div className="wr-ph">AI Wire <sub>LLM INSIGHTS</sub></div>
        <div className="wr-wire-scroll">
          <div className="wr-empty">No insights yet — awaiting first analysis</div>
        </div>
      </div>
    );
  }

  return (
    <div className="wr-pnl wr-wire-pnl">
      <div className="wr-ph">AI Wire <sub>LLM INSIGHTS</sub></div>
      <div className="wr-wire-scroll">
        {sorted.map((item, i) => {
          const involves = selectedTeam
            ? item.teams?.includes(selectedTeam)
            : false;
          const dim = selectedTeam && !involves;
          const sev = item.severity ?? "signal";
          const catLabel = (item.category ?? "").replace(/_/g, " ");
          const isOpen = expanded === i;

          return (
            <div
              key={i}
              className={`wr-wire-card wr-wire-${sev}${involves ? " hl" : ""}${isOpen ? " open" : ""}`}
              style={{ opacity: dim ? 0.35 : 1, cursor: "pointer" }}
              onClick={() => setExpanded(isOpen ? null : i)}
            >
              <div className="wr-wire-top">
                <span className="wr-wire-emoji">{item.emoji}</span>
                <span className="wr-wire-cat">{catLabel}</span>
                {item.teams?.map((tid) => {
                  const info = teamShort[tid];
                  if (!info) return null;
                  return (
                    <span
                      key={tid}
                      className="wr-wire-team"
                      style={{ ["--tc" as string]: info.color }}
                    >
                      {info.short}
                    </span>
                  );
                })}
                {sev !== "signal" && (
                  <span className={`wr-wire-sev wr-wire-sev-${sev}`}>
                    {sev === "alarm" ? "ALARM" : "ALERT"}
                  </span>
                )}
              </div>
              <div className="wr-wire-headline">{item.headline}</div>
              <div className="wr-wire-teaser">{item.text}</div>
              <div className="wr-wire-expand">
                <div className="wr-wire-body">{item.text}</div>
                <div className="wr-wire-time">{timeAgo(item.generated_at)}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
