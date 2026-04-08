import { useEffect } from "react";
import type {
  WRStanding,
  WRFixture,
  WRCaps,
  WRTickerItem,
  WRIntelItem,
  WRMeta,
  WRPulseTeam,
  WRScenarios,
  WRRecords,
  WRBriefing,
  WRNarrative,
  WRDossier,
  WRWireItem,
} from "../types/war-room";
import { useWarRoomDispatch } from "./useWarRoom";

const BASE = `${import.meta.env.BASE_URL.replace(/\/$/, "")}/api/ipl/war-room`;

/** Poll interval: 5 minutes. */
const POLL_MS = 5 * 60 * 1000;

async function fetchJson<T>(url: string, bustCache = false): Promise<T | null> {
  try {
    const finalUrl = bustCache ? `${url}?_t=${Date.now()}` : url;
    const res = await fetch(finalUrl);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

/**
 * Fetches all War Room panel data on mount, then polls every 5 minutes
 * so live scores and intel refresh without a manual page reload.
 */
export function useWarRoomData() {
  const dispatch = useWarRoomDispatch();

  useEffect(() => {
    let active = true;

    async function loadAll(bustCache = false) {
      const [
        standings, schedule, caps, ticker, intelLog, pulse, metaData,
        scenarios, records, briefings, narratives, dossiers, wire,
      ] = await Promise.all([
        fetchJson<WRStanding[]>(`${BASE}/standings.json`, bustCache),
        fetchJson<WRFixture[]>(`${BASE}/schedule.json`, bustCache),
        fetchJson<WRCaps>(`${BASE}/caps.json`, bustCache),
        fetchJson<WRTickerItem[]>(`${BASE}/ticker.json`, bustCache),
        fetchJson<WRIntelItem[]>(`${BASE}/intel-log.json`, bustCache),
        fetchJson<WRPulseTeam[]>(`${BASE}/pulse.json`, bustCache),
        fetchJson<WRMeta>(`${BASE}/meta.json`, bustCache),
        fetchJson<WRScenarios>(`${BASE}/scenarios.json`, bustCache),
        fetchJson<WRRecords>(`${BASE}/records.json`, bustCache),
        fetchJson<WRBriefing[]>(`${BASE}/briefing.json`, bustCache),
        fetchJson<WRNarrative[]>(`${BASE}/narratives.json`, bustCache),
        fetchJson<WRDossier[]>(`${BASE}/dossier.json`, bustCache),
        fetchJson<WRWireItem[]>(`${BASE}/wire.json`, bustCache),
      ]);

      if (!active) return;

      dispatch({
        type: "LOAD_DATA",
        payload: {
          standings: standings ?? [],
          schedule: schedule ?? [],
          caps: caps ?? { orange_cap: [], purple_cap: [], best_sr: [], best_econ: [], updated: "" },
          ticker: ticker ?? [],
          intelLog: intelLog ?? [],
          pulse: pulse ?? [],
          meta: metaData ?? {
            season: "2026",
            last_sync: "",
            panels: {
              intel_log: { synced_at: "" },
              standings: { synced_at: "" },
              caps: { synced_at: "" },
              schedule: { synced_at: "" },
              ticker: { synced_at: "" },
            },
          },
          scenarios: scenarios ?? null,
          records: records ?? null,
          briefings: briefings ?? [],
          narratives: narratives ?? [],
          dossiers: dossiers ?? [],
          wire: wire ?? [],
        },
      });
    }

    // Initial load (use browser cache)
    loadAll(false);

    // Poll with cache-busting so GitHub Pages CDN serves fresh JSON
    const interval = setInterval(() => loadAll(true), POLL_MS);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [dispatch]);
}
