import React, { useMemo } from "react";
import type { CodexOptions, ResultPacket } from "./types.js";
import { createCodexClient } from "./codex/client.js";
import { readProjectConfig, readRuntimeState } from "./bridge/config.js";
import { useBootSequence } from "./ui/hooks/use-boot-sequence.js";
import { useTowerSession } from "./ui/hooks/use-tower-session.js";
import { useAgentPool } from "./ui/hooks/use-agent-pool.js";
import { usePacketWatcher } from "./ui/hooks/use-packet-watcher.js";
import { useMemoryWatcher } from "./ui/hooks/use-memory-watcher.js";
import { BootScreen } from "./ui/boot-screen.js";
import { Layout } from "./ui/layout.js";

interface AppProps {
  options: CodexOptions;
}

export function App({ options }: AppProps) {
  // Boot sequence
  const { steps, isReady, error, assembledPrompt } =
    useBootSequence(options);

  // Create Codex SDK client (memoized, only when ready)
  const codex = useMemo(() => {
    if (!isReady) return null;
    return createCodexClient({
      model: options.model,
      sandbox: options.sandbox,
      approval: options.approval,
      dangerous: options.dangerous,
    });
  }, [isReady, options.model, options.sandbox, options.approval, options.dangerous]);

  // Tower session
  const { events: towerEvents, isRunning, isComplete, error: sessionError } =
    useTowerSession(codex, options, assembledPrompt, isReady);

  // Packet watcher
  const packetEvents = usePacketWatcher(options.projectRoot, isReady);

  // Agent pool derived from packet events
  const agents = useAgentPool(packetEvents);

  // Memory watcher
  const memoryStatus = useMemoryWatcher(
    options.projectRoot,
    isReady,
    towerEvents,
  );

  // Find the latest result packet from inbox events
  const latestResult = useMemo((): ResultPacket | null => {
    const inboxEvents = packetEvents.filter((e) => e.direction === "inbox");
    if (inboxEvents.length === 0) return null;
    const last = inboxEvents[inboxEvents.length - 1];
    if (last && "status" in last.packet && last.packet.packet_type === "result") {
      return last.packet as ResultPacket;
    }
    return null;
  }, [packetEvents]);

  // Read project info for status bar
  const { projectName, branch } = useMemo(() => {
    try {
      const config = readProjectConfig(options.projectRoot);
      const runtime = readRuntimeState(options.projectRoot);
      return {
        projectName: config.project_name ?? "unknown",
        branch: runtime.git_branch ?? "unknown",
      };
    } catch {
      return { projectName: "unknown", branch: "unknown" };
    }
  }, [options.projectRoot]);

  // Show boot screen until ready
  if (!isReady) {
    return <BootScreen steps={steps} error={error} />;
  }

  return (
    <Layout
      projectName={projectName}
      branch={branch}
      towerEvents={towerEvents}
      isTowerRunning={isRunning}
      isTowerComplete={isComplete}
      agents={agents}
      packetEvents={packetEvents}
      memoryStatus={memoryStatus}
      latestResult={latestResult}
    />
  );
}
