import { useEffect, useRef } from "react";
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

const BASE = `${import.meta.env.BASE_URL}api/ipl/war-room`;

async function fetchJson<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

/**
 * Fetches all War Room panel data on mount.
 */
export function useWarRoomData() {
  const dispatch = useWarRoomDispatch();
  const loadedRef = useRef(false);

  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;

    async function loadAll() {
      const [
        standings, schedule, caps, ticker, intelLog, pulse, metaData,
        scenarios, records, briefings, narratives, dossiers, wire,
      ] = await Promise.all([
        fetchJson<WRStanding[]>(`${BASE}/standings.json`),
        fetchJson<WRFixture[]>(`${BASE}/schedule.json`),
        fetchJson<WRCaps>(`${BASE}/caps.json`),
        fetchJson<WRTickerItem[]>(`${BASE}/ticker.json`),
        fetchJson<WRIntelItem[]>(`${BASE}/intel-log.json`),
        fetchJson<WRPulseTeam[]>(`${BASE}/pulse.json`),
        fetchJson<WRMeta>(`${BASE}/meta.json`),
        fetchJson<WRScenarios>(`${BASE}/scenarios.json`),
        fetchJson<WRRecords>(`${BASE}/records.json`),
        fetchJson<WRBriefing[]>(`${BASE}/briefing.json`),
        fetchJson<WRNarrative[]>(`${BASE}/narratives.json`),
        fetchJson<WRDossier[]>(`${BASE}/dossier.json`),
        fetchJson<WRWireItem[]>(`${BASE}/wire.json`),
      ]);

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

    loadAll();
  }, [dispatch]);
}
