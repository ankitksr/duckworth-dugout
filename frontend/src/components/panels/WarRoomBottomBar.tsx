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
        SYNCED {lastSync} &middot; CRICSHEET &middot; ESPNCRICINFO &middot;
        WISDEN &middot; GEMINI &middot; DUCKWORTH-MCP
      </span>
      <span style={{ color: "var(--wr-t3)" }}>
        IPL {meta?.season ?? "2026"} &middot; {meta?.panels?.schedule?.fixtures ?? 0} FIXTURES
      </span>
      <span className="wr-bot-brand">
        <a
          href="https://github.com"
          target="_blank"
          rel="noopener noreferrer"
          className="wr-bot-gh"
          title="View on GitHub"
        >
          &#9733;
        </a>
        {selectedTeam
          ? `${selectedTeam.toUpperCase()} — IPL MONITOR`
          : "IPL MONITOR"}
      </span>
    </footer>
  );
}
