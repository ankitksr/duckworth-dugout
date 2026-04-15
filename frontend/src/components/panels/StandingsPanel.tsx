import React from "react";
import { useWarRoomState } from "../../hooks/useWarRoom";
import { nrrDisplay } from "../helpers";

export function StandingsPanel() {
  const { standings, selectedTeam } = useWarRoomState();
  if (!standings) return null;

  return (
    <div className="wr-pnl wr-standings-pnl">
      <div className="wr-ph">
        Standings <sub>IPL 2026</sub>
      </div>
      <div className="wr-standings">
        <div className="wr-st-hdr">
          <span>#</span><span /><span /><span /><span>P</span><span>W</span><span>L</span>
          <span>Pts</span><span style={{ textAlign: "right" }}>NRR</span>
        </div>
        {standings.map((t, i) => {
          const nrr = nrrDisplay(t.nrr);
          return (
            <div key={t.franchise_id}>
              <div
                className={`wr-st-row ${selectedTeam === t.franchise_id ? "sel" : ""}`}
              >
                <span className="wr-st-pos">{t.position}</span>
                <div
                  className="wr-st-bar"
                  style={{ background: t.war_room_color ?? t.primary_color }}
                />
                <span className="wr-st-name">{t.short_name}</span>
                <span />
                <span className="wr-st-val">{t.played}</span>
                <span className="wr-st-val">{t.wins}</span>
                <span className="wr-st-val">{t.losses}</span>
                <span className="wr-st-pts">{t.points}</span>
                <span className={`wr-st-nrr ${nrr.positive ? "pos" : "neg"}`}>
                  {nrr.text}
                </span>
              </div>
              {i === 3 && <div className="wr-st-cut" />}
            </div>
          );
        })}
      </div>
    </div>
  );
}
