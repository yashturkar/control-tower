import React from "react";
import { Box } from "ink";
import type {
  TowerEvent,
  AgentStatus,
  PacketEvent,
  MemoryStatus,
  ResultPacket,
} from "../types.js";
import { StatusBar } from "./panels/status-bar.js";
import { TowerPanel } from "./panels/tower-panel.js";
import { AgentPanel } from "./panels/agent-panel.js";
import { PacketFlow } from "./panels/packet-flow.js";
import { ResultSummary } from "./panels/result-summary.js";

interface LayoutProps {
  projectName: string;
  branch: string;
  towerEvents: TowerEvent[];
  isTowerRunning: boolean;
  isTowerComplete: boolean;
  agents: AgentStatus[];
  packetEvents: PacketEvent[];
  memoryStatus: MemoryStatus;
  latestResult: ResultPacket | null;
}

export function Layout({
  projectName,
  branch,
  towerEvents,
  isTowerRunning,
  isTowerComplete,
  agents,
  packetEvents,
  memoryStatus,
  latestResult,
}: LayoutProps) {
  return (
    <Box flexDirection="column">
      <StatusBar
        projectName={projectName}
        branch={branch}
        agents={agents}
        memoryStatus={memoryStatus}
      />
      <TowerPanel
        events={towerEvents}
        isRunning={isTowerRunning}
        isComplete={isTowerComplete}
      />
      <AgentPanel agents={agents} />
      <PacketFlow events={packetEvents} />
      <ResultSummary result={latestResult} />
    </Box>
  );
}
