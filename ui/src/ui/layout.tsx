import React, { useState, useEffect } from "react";
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

/** Hook that tracks terminal height, updating on resize. */
function useTerminalHeight(): number {
  const { stdout } = useStdout();
  const [height, setHeight] = useState(stdout?.rows ?? 40);

  useEffect(() => {
    if (!stdout) return;
    const onResize = () => setHeight(stdout.rows);
    stdout.on("resize", onResize);
    return () => { stdout.off("resize", onResize); };
  }, [stdout]);

  return height;
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
  const termHeight = useTerminalHeight();

  // Calculate how many rows the fixed panels consume so TowerPanel
  // can limit its output to exactly the remaining space.
  // StatusBar:     3 lines (border-top, content, border-bottom)
  // AgentPanel:    agents.length + 3 (border-top, header, rows, border-bottom)
  // PacketFlow:    visible packets + 3 (border-top, header, rows/placeholder, border-bottom)
  // ResultSummary: 0 when null, ~5 when shown
  const packetLines = Math.min(packetEvents.length || 1, 6);
  const resultLines = latestResult ? 5 : 0;
  const fixedRows =
    3 +                        // StatusBar
    (agents.length + 3) +      // AgentPanel
    (packetLines + 3) +        // PacketFlow
    resultLines;               // ResultSummary

  // TowerPanel border/header takes 4 rows (top border, header, bottom border, + 1 safety)
  const towerChrome = 4;
  const towerMaxLines = Math.max(3, termHeight - fixedRows - towerChrome);

  return (
    <Box flexDirection="column" height={termHeight} width="100%">
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
        maxLines={towerMaxLines}
      />
      <AgentPanel agents={agents} />
      <PacketFlow events={packetEvents} />
      <ResultSummary result={latestResult} />
    </Box>
  );
}
