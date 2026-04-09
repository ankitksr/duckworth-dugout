import React, { useState, useMemo } from "react";
import { useWarRoomState } from "../../hooks/useWarRoom";
import type { WRIntelItem } from "../../types/war-room";
import { timeAgo } from "../helpers";

export function IntelLogPanel() {
  const { intelLog, selectedTeam } = useWarRoomState();
  const [feedFilter, setFeedFilter] = useState<string | null>(null);
  if (!intelLog) return null;

  // Derive unique sources, pinned order: ESPNcricinfo, r/Cricket, then rest alpha
  const sources = useMemo(() => {
    const pinned = ["espncricinfo", "reddit"];
    const tabLabel: Record<string, string> = { reddit: "r/Cricket" };
    const seen = new Map<string, string>();
    for (const item of intelLog) {
      if (item.source && !seen.has(item.source)) {
        seen.set(item.source, tabLabel[item.source] ?? item.source_name);
      }
    }
    const all = Array.from(seen.entries()).map(([key, name]) => ({ key, name }));
    return all.sort((a, b) => {
      const ai = pinned.indexOf(a.key);
      const bi = pinned.indexOf(b.key);
      if (ai !== -1 && bi !== -1) return ai - bi;
      if (ai !== -1) return -1;
      if (bi !== -1) return 1;
      return a.name.localeCompare(b.name);
    });
  }, [intelLog]);

  const filtered = feedFilter
    ? intelLog.filter((item) => item.source === feedFilter)
    : intelLog;

  return (
    <div className="wr-pnl wr-log-pnl">
      <div className="wr-ph">
        Intel Feed <sub>{filtered.length}</sub>
      </div>
      <div className="wr-log-filters">
        <button
          className={`wr-log-filter ${feedFilter === null ? "on" : ""}`}
          onClick={() => setFeedFilter(null)}
        >All</button>
        {sources.map((s) => (
          <button
            key={s.key}
            className={`wr-log-filter ${feedFilter === s.key ? "on" : ""}`}
            onClick={() => setFeedFilter(feedFilter === s.key ? null : s.key)}
          >{s.name}</button>
        ))}
      </div>
      <div className="wr-log-wrap">
        <div className="wr-log-scroll">
          {filtered.slice(0, 30).map((item: WRIntelItem) => {
            const involves =
              selectedTeam && item.teams.includes(selectedTeam);
            const dim = selectedTeam && !involves;
            return (
              <a
                key={item.id}
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className={`wr-log-item ${involves ? "hl" : ""}`}
                style={{ opacity: dim ? 0.4 : 1 }}
              >
                <div className="wr-log-thumb">
                  {item.image_url ? (
                    <img src={item.image_url} alt="" loading="lazy" />
                  ) : (
                    <span className="wr-log-thumb-ph">
                      {item.source_name.charAt(0)}
                    </span>
                  )}
                </div>
                <div className="wr-log-body">
                  <div className="wr-log-meta">
                    <span className="wr-log-tag">{item.source_name}</span>
                    {item.teams.length <= 3 && item.teams.map((t) => (
                      <span key={t} className="wr-log-team" style={{ color: `var(--${t})` }}>{t.toUpperCase()}</span>
                    ))}
                    <span className="wr-log-time">{timeAgo(item.published)}</span>
                  </div>
                  <div className="wr-log-headline">{item.title}</div>
                </div>
              </a>
            );
          })}
        </div>
      </div>
    </div>
  );
}
