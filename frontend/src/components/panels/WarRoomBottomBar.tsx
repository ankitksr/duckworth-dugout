import React from "react";
import { useWarRoomState } from "../../hooks/useWarRoom";
import { timeAgo } from "../helpers";

export function WarRoomBottomBar() {
  const { meta, selectedTeam } = useWarRoomState();
  const lastSync = meta?.last_sync
    ? timeAgo(meta.last_sync)
    : "—";

  return (
    <footer className="wr-bot">
      <span>
        SYNCED {lastSync} &middot; DUCKWORTH-MCP &middot; CRICSHEET &middot; ESPNCRICINFO &middot;
        WISDEN &middot; CRICKETADDICTOR &middot; CRICTRACKER &middot; WIKIPEDIA &middot; GEMINI
      </span>
      <span style={{ color: "var(--wr-t3)" }}>
        IPL {meta?.season ?? "2026"} &middot; {meta?.panels?.schedule?.fixtures ?? 0} FIXTURES
      </span>
      <span className="wr-bot-brand">
        <a
          href="https://github.com/ankitksr/duckworth-dugout"
          target="_blank"
          rel="noopener noreferrer"
          className="wr-bot-gh"
          title="View on GitHub"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z" />
          </svg>
          ankitksr
        </a>
        {selectedTeam
          ? `${selectedTeam.toUpperCase()} — IPL MONITOR`
          : "IPL MONITOR"}
      </span>
    </footer>
  );
}
