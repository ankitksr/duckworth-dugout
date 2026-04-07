import React from "react";
import { WarRoomProvider, useWarRoomState } from "../hooks/useWarRoom";
import { useWarRoomData } from "../hooks/useWarRoomData";

import { WarRoomTopBar } from "./panels/WarRoomTopBar";
import { WarRoomBottomBar } from "./panels/WarRoomBottomBar";
import { StandingsPanel } from "./panels/StandingsPanel";
import { CapRacePanel } from "./panels/CapRacePanel";
import { SeasonPulse } from "./panels/SeasonPulse";
import { MatchTimeline } from "./panels/MatchTimeline";
import { AIWirePanel } from "./panels/AIWirePanel";
import { IntelLogPanel } from "./panels/IntelLogPanel";
import { BriefingPanel } from "./bridge/BriefingPanel";
import { TeamIntelPanel } from "./bridge/TeamIntelPanel";

function WarRoomInner() {
  const { loading, selectedTeam } = useWarRoomState();
  useWarRoomData();

  if (loading) {
    return (
      <div className="wr">
        <div className="wr-loading">Loading Dugout...</div>
      </div>
    );
  }

  return (
    <div className="wr">
      <WarRoomTopBar />
      <main className="wr-main">
        <div className="wr-col wr-col-left">
          <StandingsPanel />
          <MatchTimeline />
          <CapRacePanel />
        </div>
        <div className="wr-col wr-col-center">
          <SeasonPulse />
          <div className="wr-center-lower">
            {selectedTeam ? <TeamIntelPanel /> : <BriefingPanel />}
          </div>
        </div>
        <div className="wr-col wr-col-right">
          <AIWirePanel />
          <IntelLogPanel />
        </div>
      </main>
      <WarRoomBottomBar />
    </div>
  );
}

export function WarRoomView() {
  return (
    <WarRoomProvider>
      <WarRoomInner />
    </WarRoomProvider>
  );
}
