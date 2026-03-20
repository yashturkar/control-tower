import React from "react";
import { Box, useStdout } from "ink";
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
  const { stdout } = useStdout();
  const termHeight = stdout?.rows ?? 40;

  return (
    <Box flexDirection="column" height={termHeight} width="100%">
      <StatusBar
        projectName={projectName}
        branch={branch}
        agents={agents}
        memoryStatus={memoryStatus}
      />
      <Box flexGrow={1} flexDirection="column" overflow="hidden" width="100%">
        <TowerPanel
          events={towerEvents}
          isRunning={isTowerRunning}
          isComplete={isTowerComplete}
        />
      </Box>
      <AgentPanel agents={agents} />
      <PacketFlow events={packetEvents} />
      <ResultSummary result={latestResult} />
    </Box>
  );
}
