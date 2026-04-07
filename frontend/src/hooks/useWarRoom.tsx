import {
  createContext,
  useContext,
  useReducer,
  type Dispatch,
  type ReactNode,
} from "react";
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

// ── State ──

export type IntelTab = "scenarios" | "records" | "briefing" | "dossier" | "narrative";

export interface WarRoomState {
  selectedTeam: string | null;
  capTab: "orange" | "purple" | "sr" | "econ" | "mvp";
  intelTab: IntelTab;
  standings: WRStanding[] | null;
  schedule: WRFixture[] | null;
  caps: WRCaps | null;
  ticker: WRTickerItem[] | null;
  intelLog: WRIntelItem[] | null;
  pulse: WRPulseTeam[] | null;
  meta: WRMeta | null;
  scenarios: WRScenarios | null;
  records: WRRecords | null;
  briefings: WRBriefing[];
  narratives: WRNarrative[];
  dossiers: WRDossier[];
  wire: WRWireItem[];
  loading: boolean;
}

const initialState: WarRoomState = {
  selectedTeam: null,
  capTab: "orange",
  intelTab: "briefing",
  standings: null,
  schedule: null,
  caps: null,
  ticker: null,
  intelLog: null,
  pulse: null,
  meta: null,
  scenarios: null,
  records: null,
  briefings: [],
  narratives: [],
  dossiers: [],
  wire: [],
  loading: true,
};

// ── Actions ──

export type WarRoomAction =
  | { type: "SELECT_TEAM"; payload: string | null }
  | { type: "SET_CAP_TAB"; payload: "orange" | "purple" | "sr" | "econ" | "mvp" }
  | { type: "SET_INTEL_TAB"; payload: IntelTab }
  | {
      type: "LOAD_DATA";
      payload: {
        standings: WRStanding[];
        schedule: WRFixture[];
        caps: WRCaps;
        ticker: WRTickerItem[];
        intelLog: WRIntelItem[];
        pulse: WRPulseTeam[];
        meta: WRMeta;
        scenarios: WRScenarios | null;
        records: WRRecords | null;
        briefings: WRBriefing[];
        narratives: WRNarrative[];
        dossiers: WRDossier[];
        wire?: WRWireItem[];
      };
    }
;

// ── Reducer ──

function warRoomReducer(
  state: WarRoomState,
  action: WarRoomAction,
): WarRoomState {
  switch (action.type) {
    case "SELECT_TEAM":
      return {
        ...state,
        selectedTeam:
          action.payload === state.selectedTeam ? null : action.payload,
      };
    case "SET_CAP_TAB":
      return { ...state, capTab: action.payload };
    case "SET_INTEL_TAB":
      return { ...state, intelTab: action.payload };
    case "LOAD_DATA":
      return {
        ...state,
        standings: action.payload.standings,
        schedule: action.payload.schedule,
        caps: action.payload.caps,
        ticker: action.payload.ticker,
        intelLog: action.payload.intelLog,
        pulse: action.payload.pulse,
        meta: action.payload.meta,
        scenarios: action.payload.scenarios,
        records: action.payload.records,
        briefings: action.payload.briefings,
        narratives: action.payload.narratives,
        dossiers: action.payload.dossiers,
        wire: action.payload.wire ?? state.wire,
        loading: false,
      };
    default:
      return state;
  }
}

// ── Contexts ──

const StateCtx = createContext<WarRoomState | null>(null);
const DispatchCtx = createContext<Dispatch<WarRoomAction> | null>(null);

export function WarRoomProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(warRoomReducer, initialState);
  return (
    <StateCtx.Provider value={state}>
      <DispatchCtx.Provider value={dispatch}>{children}</DispatchCtx.Provider>
    </StateCtx.Provider>
  );
}

export function useWarRoomState(): WarRoomState {
  const ctx = useContext(StateCtx);
  if (!ctx)
    throw new Error("useWarRoomState must be used within WarRoomProvider");
  return ctx;
}

export function useWarRoomDispatch(): Dispatch<WarRoomAction> {
  const ctx = useContext(DispatchCtx);
  if (!ctx)
    throw new Error("useWarRoomDispatch must be used within WarRoomProvider");
  return ctx;
}
