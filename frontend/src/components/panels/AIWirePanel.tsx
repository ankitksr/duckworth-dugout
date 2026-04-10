import React, { useState, useMemo, useEffect } from "react";
import { useWarRoomState } from "../../hooks/useWarRoom";
import { isFresh, timeAgo } from "../helpers";
import type { WRWireSource } from "../../types/war-room";

const SOURCE_LABELS: Record<WRWireSource, string> = {
  situation: "SITUATION",
  scout: "SCOUT",
  newsdesk: "NEWS",
  preview: "PREVIEW",
  take: "THE TAKE",
  wire: "WIRE",
};

// Desks shown in the filter bar (wire/legacy items stay in ALL only)
const FILTER_SOURCES: WRWireSource[] = [
  "situation",
  "newsdesk",
  "preview",
  "scout",
  "take",
];

type Filter = WRWireSource | "all";

export function AIWirePanel() {
  const { wire, selectedTeam, standings } = useWarRoomState();
  const [expanded, setExpanded] = useState<number | null>(null);
  const [sourceFilter, setSourceFilter] = useState<Filter>("all");

  // Resolve short names for team chips
  const teamShort = useMemo(() => {
    if (!standings) return {};
    const map: Record<string, { short: string; color: string }> = {};
    for (const s of standings) {
      map[s.franchise_id] = { short: s.short_name, color: s.primary_color };
    }
    return map;
  }, [standings]);

  // Apply source filter, then float team-relevant entries to the top
  const sorted = useMemo(() => {
    let items = wire ?? [];
    if (sourceFilter !== "all") {
      items = items.filter((i) => (i.source ?? "wire") === sourceFilter);
    }
    if (!selectedTeam) return items;
    return [...items].sort((a, b) => {
      const aInv = a.teams?.includes(selectedTeam) ? 0 : 1;
      const bInv = b.teams?.includes(selectedTeam) ? 0 : 1;
      return aInv - bInv;
    });
  }, [wire, selectedTeam, sourceFilter]);

  // Reset expanded card when filters change
  useEffect(() => {
    setExpanded(null);
  }, [selectedTeam, sourceFilter]);

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
      <div className="wr-wire-filters">
        <button
          className={`wr-wire-filter${sourceFilter === "all" ? " active" : ""}`}
          onClick={() => setSourceFilter("all")}
        >
          ALL
        </button>
        {FILTER_SOURCES.map((src) => (
          <button
            key={src}
            className={`wr-wire-filter wr-wire-filter-${src}${sourceFilter === src ? " active" : ""}`}
            onClick={() => setSourceFilter(src)}
          >
            {SOURCE_LABELS[src]}
          </button>
        ))}
      </div>
      <div className="wr-wire-scroll">
        {sorted.length === 0 && (
          <div className="wr-empty">No dispatches match this filter</div>
        )}
        {sorted.map((item, i) => {
          const involves = selectedTeam
            ? item.teams?.includes(selectedTeam)
            : false;
          const dim = selectedTeam && !involves;
          const sev = item.severity ?? "signal";
          const catLabel = (item.category ?? "").replace(/_/g, " ");
          const isOpen = expanded === i;
          const source = (item.source ?? "wire") as WRWireSource;
          const sourceLabel = SOURCE_LABELS[source] || source.toUpperCase();
          const fresh = isFresh(item.generated_at);
          const teams = item.teams ?? [];
          const visibleTeams = teams.slice(0, 2);
          const overflow = teams.length - visibleTeams.length;

          return (
            <div
              key={i}
              className={`wr-wire-card wr-wire-${sev} wr-wire-src-${source}${involves ? " hl" : ""}${isOpen ? " open" : ""}${fresh ? " fresh" : ""}`}
              style={{ opacity: dim ? 0.35 : 1, cursor: "pointer" }}
              onClick={() => setExpanded(isOpen ? null : i)}
            >
              <div className="wr-wire-top">
                <span className="wr-wire-emoji">{item.emoji}</span>
                <span className={`wr-wire-source wr-wire-source-${source}`}>
                  {sourceLabel}
                </span>
                <span className="wr-wire-teams">
                  {visibleTeams.map((tid) => {
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
                  {overflow > 0 && (
                    <span className="wr-wire-team wr-wire-team-overflow">
                      +{overflow}
                    </span>
                  )}
                </span>
                <span className="wr-wire-meta-right">
                  {fresh && (
                    <span className="wr-wire-fresh-dot" title="New (< 2h)" />
                  )}
                  <span className="wr-wire-time">{timeAgo(item.generated_at)}</span>
                </span>
              </div>
              {sev === "alarm" && (
                <div className="wr-wire-deck">Urgent</div>
              )}
              <div className="wr-wire-hl-row">
                <div className="wr-wire-headline">{item.headline}</div>
                <span className={`wr-wire-chevron${isOpen ? " open" : ""}`}>
                  &#x25B8;
                </span>
              </div>
              {isOpen && (
                <div className="wr-wire-expand" style={{ display: "block" }}>
                  <div className="wr-wire-body">{item.text}</div>
                  {catLabel && <div className="wr-wire-cat">{catLabel}</div>}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
