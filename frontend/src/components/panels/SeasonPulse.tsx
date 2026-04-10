import React, { useRef, useState, useCallback, useEffect, useMemo } from "react";
import { useWarRoomState, useWarRoomDispatch } from "../../hooks/useWarRoom";
import { pointsToSmoothPath } from "../../lib/svg-smooth";
import { nrrDisplay } from "../helpers";

export function SeasonPulse() {
  const { pulse, selectedTeam } = useWarRoomState();
  const dispatch = useWarRoomDispatch();
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ w: 0, h: 0 });

  const measure = useCallback(() => {
    if (containerRef.current) {
      setDims({
        w: containerRef.current.offsetWidth,
        h: containerRef.current.offsetHeight,
      });
    }
  }, []);

  // ResizeObserver instead of window.resize: the canvas needs to
  // re-measure whenever its container changes size, not just when the
  // viewport does. On mobile the panel starts inside a collapsed wrapper,
  // so the canvas mounts at 0×0 and stays empty until the user expands —
  // window.resize never fires for that, but ResizeObserver does.
  useEffect(() => {
    measure();
    if (typeof ResizeObserver === "undefined" || !containerRef.current) {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const ro = new ResizeObserver(() => measure());
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, [measure]);

  const { w: W, h: H } = dims;
  const ready = !!(pulse?.length && W && H);
  const totalTeams = pulse?.length ?? 10;

  // Layout constants (safe even when not ready)
  const pL = 24, pR = 80, pT = 14, pB = 18;
  const chartW = Math.max(1, W - pL - pR);
  const chartH = Math.max(1, H - pT - pB);

  const maxMatches = ready ? Math.max(1, ...pulse!.map((t) => t.snapshots.length)) : 1;
  const xCols = Math.max(maxMatches + 1, 5);
  const x = (col: number) => pL + (col / xCols) * chartW;

  const minGap = Math.max(14, chartH / (totalTeams * 2.2));
  const centerY = pT + chartH / 2;

  type TeamState = { fid: string; points: number; nrr: number; rank: number };

  const maxMatchNum = ready
    ? Math.max(1, ...pulse!.flatMap((t) => t.snapshots.map((s) => s.match)))
    : 1;

  // For each match number, collect state of all teams that have played.
  // Final column uses team-level current_rank (matches standings) for ordering.
  const statesAtMatch = useMemo(() => {
    if (!ready) return new Map<number, TeamState[]>();
    const result: Map<number, TeamState[]> = new Map();

    // Find each team's max match number
    const teamMaxMatch = new Map<string, number>();
    for (const t of pulse!) {
      const max = t.snapshots.length > 0 ? Math.max(...t.snapshots.map((s) => s.match)) : 0;
      teamMaxMatch.set(t.fid, max);
    }

    for (let m = 1; m <= maxMatchNum; m++) {
      const states: TeamState[] = [];
      for (const t of pulse!) {
        const snap = [...t.snapshots].reverse().find((s) => s.match <= m);
        if (snap) {
          // At the team's final snapshot, use current_rank for ordering
          const atEnd = snap.match === teamMaxMatch.get(t.fid);
          states.push({
            fid: t.fid,
            points: snap.points,
            nrr: snap.nrr ?? 0,
            rank: atEnd ? t.current_rank : snap.rank,
          });
        }
      }
      states.sort((a, b) => a.rank - b.rank);
      result.set(m, states);
    }
    return result;
  }, [pulse, maxMatchNum, ready]);

  // Layout Y positions: points bands with NRR spread within, minimum gap enforced
  function layoutY(states: TeamState[]): Map<string, number> {
    if (states.length === 0) return new Map();

    // Group by points
    const groups: Map<number, TeamState[]> = new Map();
    for (const s of states) {
      const g = groups.get(s.points) ?? [];
      g.push(s);
      groups.set(s.points, g);
    }
    const sortedPts = [...groups.keys()].sort((a, b) => b - a); // highest first

    // Allocate vertical space proportional to points gaps + base spacing
    const totalSlots = states.length;
    const usableH = chartH - minGap; // leave some margin
    const totalMinH = totalSlots * minGap;

    // Assign initial Y positions: distribute groups evenly, spread within by NRR
    const yMap = new Map<string, number>();
    let cursor = pT + minGap / 2;

    for (let gi = 0; gi < sortedPts.length; gi++) {
      const pts = sortedPts[gi];
      const group = groups.get(pts)!;
      // Sort within group by rank (matches standings order)
      group.sort((a, b) => a.rank - b.rank);

      if (group.length === 1) {
        yMap.set(group[0].fid, cursor);
        cursor += minGap;
      } else {
        // Spread within group: NRR range determines spread, but at least minGap between each
        const nrrRange = Math.max(0, group[0].nrr - group[group.length - 1].nrr);
        // Extra spread proportional to NRR range (capped at 2x minGap per team)
        const nrrBonus = Math.min(nrrRange * 3, minGap * 1.5);
        const groupSpan = (group.length - 1) * minGap + nrrBonus * (group.length - 1) / Math.max(1, group.length - 1);

        for (let ti = 0; ti < group.length; ti++) {
          const frac = group.length > 1 ? ti / (group.length - 1) : 0;
          yMap.set(group[ti].fid, cursor + frac * groupSpan);
        }
        cursor += groupSpan + minGap;
      }

      // Add gap between points groups (proportional to points difference)
      if (gi < sortedPts.length - 1) {
        const ptsDiff = sortedPts[gi] - sortedPts[gi + 1];
        cursor += ptsDiff * minGap * 0.3;
      }
    }

    // Always stretch to fill the full chart height
    const allY = [...yMap.values()];
    const rawMin = Math.min(...allY);
    const rawMax = Math.max(...allY);
    const span = rawMax - rawMin;
    const pad = minGap * 0.4;
    if (span > 0) {
      const scale = (chartH - pad * 2) / span;
      for (const [fid, y] of yMap) {
        yMap.set(fid, pT + pad + (y - rawMin) * scale);
      }
    }

    return yMap;
  }

  // Compute Y positions per match column
  const yAtMatch = useMemo(() => {
    const result: Map<number, Map<string, number>> = new Map();
    for (let m = 1; m <= maxMatchNum; m++) {
      const states = statesAtMatch.get(m) ?? [];
      result.set(m, layoutY(states));
    }
    return result;
  }, [statesAtMatch, chartH, minGap]);

  // Cutoff: Y position between rank 4 and 5 in the latest column
  const latestY = yAtMatch.get(maxMatchNum);
  const cutoffY = useMemo(() => {
    if (!latestY) return pT + chartH * 0.4;
    // Find the Y gap between the 4th and 5th team
    const latestStates = statesAtMatch.get(maxMatchNum) ?? [];
    if (latestStates.length < 5) return pT + chartH * 0.4;
    const y4 = latestY.get(latestStates[3].fid) ?? 0;
    const y5 = latestY.get(latestStates[4].fid) ?? 0;
    return (y4 + y5) / 2;
  }, [latestY, statesAtMatch, maxMatchNum]);

  if (!ready) {
    return (
      <div className="wr-pnl wr-pulse-pnl">
        <div className="wr-ph">Season Pulse <sub>RANK RIVER</sub></div>
        <div className="wr-pulse-canvas" ref={containerRef} />
      </div>
    );
  }

  type RiverEntry = {
    fid: string;
    color: string;
    short: string;
    points: number;
    nrr: string;
    currentRank: number;
    endY: number;
    hasMatches: boolean;
    path: [number, number][];
    results: ("W" | "L" | "NR")[];
  };

  const rivers: RiverEntry[] = pulse!.map((t) => {
    const path: [number, number][] = [[x(0), centerY]]; // Start from center
    const results: ("W" | "L" | "NR")[] = [];
    const hasMatches = t.snapshots.length > 0;

    for (let i = 0; i < t.snapshots.length; i++) {
      const snap = t.snapshots[i];
      const matchY = yAtMatch.get(snap.match);
      const y = matchY?.get(t.fid) ?? centerY;
      path.push([x(snap.match), y]);
      results.push(snap.result);
    }

    const endY = latestY?.get(t.fid) ?? centerY;

    return {
      fid: t.fid,
      color: t.color,
      short: t.short,
      points: t.points,
      nrr: t.nrr,
      currentRank: t.current_rank,
      endY,
      hasMatches,
      path,
      results,
    };
  });

  // Z-order: selected team rendered last (on top)
  const sorted = [...rivers].sort((a, b) =>
    (a.fid === selectedTeam ? 1 : 0) - (b.fid === selectedTeam ? 1 : 0),
  );

  return (
    <div className="wr-pnl wr-pulse-pnl">
      <div className="wr-ph">Season Pulse <sub>RANK RIVER</sub></div>
      <div className="wr-pulse-canvas" ref={containerRef}>
        <svg viewBox={`0 0 ${W} ${H}`} className="wr-pulse-svg">
          {/* Playoff cutoff zone */}
          <rect x={pL} y={cutoffY - 1} width={chartW} height={2}
            fill="rgba(0,230,118,0.06)" />
          <line x1={pL} y1={cutoffY} x2={W - pR} y2={cutoffY}
            className="wr-cutoff" />

          {/* Match column markers */}
          {maxMatches > 0 && Array.from({ length: Math.min(maxMatches, xCols - 1) }, (_, i) => (
            <text key={`mc-${i}`} x={x(i + 1)} y={H - 3} className="wr-axis-label">
              M{i + 1}
            </text>
          ))}

          {/* River paths — only for teams with match data */}
          {sorted.map((r) => {
            if (!r.hasMatches) return null;
            const isHero = selectedTeam === r.fid;
            const dimmed = selectedTeam && !isHero;
            const opacity = dimmed ? 0.06 : isHero ? 1 : 0.65;

            const d = pointsToSmoothPath(r.path);
            if (!d) return null;

            return (
              <g key={r.fid} style={{ cursor: "pointer" }}
                onClick={() => dispatch({ type: "SELECT_TEAM", payload: r.fid })}>
                {/* Glow */}
                <path d={d} fill="none" stroke={r.color}
                  strokeWidth={isHero ? 10 : 4} strokeLinecap="round"
                  style={{ filter: "blur(6px)", opacity: opacity * 0.35 }} />
                {/* Main */}
                <path d={d} fill="none" stroke={r.color}
                  strokeWidth={isHero ? 3.5 : 2} strokeLinecap="round" strokeLinejoin="round"
                  style={{ opacity, transition: "opacity 0.3s" }} />

                {/* Match result dots */}
                {r.path.slice(1).map(([px, py], i) => {
                  const result = r.results[i];
                  if (dimmed) return null;
                  return (
                    <g key={i}>
                      {isHero && (
                        <circle cx={px} cy={py} r={7} fill={r.color}
                          style={{ opacity: 0.12, filter: "blur(4px)" }} />
                      )}
                      <circle cx={px} cy={py} r={isHero ? 4.5 : 3}
                        fill={result === "W" ? "#00e676" : result === "L" ? "#ff3d51" : "#555"}
                        stroke={isHero ? r.color : "none"} strokeWidth={isHero ? 1.5 : 0} />
                    </g>
                  );
                })}
              </g>
            );
          })}
        </svg>

        {/* Right-edge team labels — positioned by current rank */}
        {rivers.map((r) => {
          const isHero = selectedTeam === r.fid;
          const dimmed = selectedTeam && !isHero;
          const nrr = nrrDisplay(r.nrr);
          const noData = !r.hasMatches;
          return (
            <div key={`lbl-${r.fid}`}
              className={`wr-river-label ${isHero ? "hero" : ""}`}
              style={{
                position: "absolute",
                right: 0,
                top: r.endY,
                transform: "translateY(-50%)",
                width: pR - 2,
                color: r.color,
                borderLeft: `2px solid ${r.color}`,
                background: isHero ? `${r.color}12` : undefined,
                opacity: dimmed ? 0.12 : noData ? 0.3 : isHero ? 1 : 0.8,
                transition: "opacity 0.3s, top 0.5s ease",
                cursor: "pointer",
              }}
              onClick={() => dispatch({ type: "SELECT_TEAM", payload: r.fid })}>
              <span className="wr-river-name">{r.short}</span>
              <span className="wr-river-stat">
                {r.points}<small>pts</small>
                {isHero && nrr.text !== "-" ? ` ${nrr.text}` : ""}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
