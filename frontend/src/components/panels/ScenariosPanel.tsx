import React from "react";
import { useWarRoomState } from "../../hooks/useWarRoom";
import type { WREliminationEntry, WRQualMathEntry } from "../../types/war-room";

export function ScenariosPanel() {
  const { scenarios, standings } = useWarRoomState();
  if (!scenarios) return null;

  const situationBrief = scenarios.situation_brief || scenarios.headline || null;

  // Resolve team franchise ID from short name for color variable
  const teamColor = (shortName: string): string => {
    const st = standings?.find(
      (s) => s.short_name.toLowerCase() === shortName.toLowerCase()
        || s.franchise_id === shortName.toLowerCase(),
    );
    return st ? `var(--${st.franchise_id})` : "var(--wr-t3)";
  };

  return (
    <div className="wr-pnl wr-scenarios-pnl">
      <div className="wr-ph">Scenarios <sub>AFTER M{scenarios.matches_played}</sub></div>
      <div className="wr-scenarios-scroll">

        {/* Situation Brief — World-Brief-style card */}
        {situationBrief && (
          <div className="wr-sc-brief">
            <div className="wr-sc-brief-label">◉ Situation Brief</div>
            <div className="wr-sc-brief-body">{situationBrief}</div>
          </div>
        )}

        {/* Elimination Watch */}
        {scenarios.elimination_watch.length > 0 && (
          <div className="wr-sc-section">
            <div className="wr-sc-label">Elimination Watch</div>
            <div className="wr-sc-cards">
              {scenarios.elimination_watch.map((entry: WREliminationEntry, i) => {
                const tc = teamColor(entry.team);
                const riskLabel = entry.risk === "danger" ? "DANGER"
                  : entry.risk === "safe" ? "SAFE" : "WATCH";
                return (
                  <div
                    key={i}
                    className="wr-sc-card"
                    style={{ ["--tc" as string]: tc }}
                  >
                    <div className="wr-sc-card-hd">
                      <span className="wr-sc-card-team">{entry.team}</span>
                      <span className={`wr-sc-risk wr-sc-risk-${entry.risk}`}>{riskLabel}</span>
                    </div>
                    {entry.key_metric && (
                      <div className="wr-sc-card-metric">{entry.key_metric}</div>
                    )}
                    <div className="wr-sc-card-body">{entry.insight}</div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Qualification Math */}
        {scenarios.qualification_math.length > 0 && (
          <div className="wr-sc-section">
            <div className="wr-sc-label">Qualification Math</div>
            {scenarios.qualification_math.map((item: WRQualMathEntry, i) => (
              <div key={i} className="wr-sc-math">
                <div className="wr-sc-math-fact">{item.fact}</div>
                <div className="wr-sc-math-tag">{item.tag}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
