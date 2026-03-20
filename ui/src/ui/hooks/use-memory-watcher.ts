import { useState, useEffect, useRef } from "react";
import { watch } from "chokidar";
import { basename } from "node:path";
import type { MemoryStatus, TowerEvent } from "../../types.js";
import { memoryDirPath } from "../../bridge/config.js";
import { isMemorySyncEvent } from "../../codex/event-parser.js";

const IDLE_TIMEOUT_MS = 3000;

export function useMemoryWatcher(
  projectRoot: string,
  enabled: boolean,
  towerEvents: TowerEvent[],
): MemoryStatus {
  const [status, setStatus] = useState<MemoryStatus>({
    state: "idle",
    detail: "",
  });
  const watcherRef = useRef<ReturnType<typeof watch> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Watch filesystem for memory file changes
  useEffect(() => {
    if (!enabled) return;

    const memDir = memoryDirPath(projectRoot);

    const watcher = watch(memDir, {
      ignoreInitial: true,
      awaitWriteFinish: { stabilityThreshold: 200, pollInterval: 100 },
    });

    watcherRef.current = watcher;

    watcher.on("change", (filePath: string) => {
      const fileName = basename(filePath);
      setStatus({ state: "storing", detail: `Storing ${fileName}` });
      resetIdleTimeout();
    });

    watcher.on("add", (filePath: string) => {
      const fileName = basename(filePath);
      setStatus({ state: "storing", detail: `Storing ${fileName}` });
      resetIdleTimeout();
    });

    return () => {
      watcher.close();
      watcherRef.current = null;
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [projectRoot, enabled]);

  // Watch tower stream events for sync-memory calls
  useEffect(() => {
    if (towerEvents.length === 0) return;

    const lastEvent = towerEvents[towerEvents.length - 1];
    if (lastEvent && isMemorySyncEvent(lastEvent)) {
      setStatus({ state: "syncing", detail: "Syncing sessions" });
      resetIdleTimeout();
    }
  }, [towerEvents]);

  function resetIdleTimeout() {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => {
      setStatus({ state: "idle", detail: "" });
    }, IDLE_TIMEOUT_MS);
  }

  return status;
}
