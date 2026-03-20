import { useState, useEffect, useRef } from "react";
import { watch } from "chokidar";
import { readFileSync } from "node:fs";
import { basename } from "node:path";
import type {
  PacketEvent,
  TaskPacket,
  ResultPacket,
} from "../../types.js";
import {
  packetsOutboxPath,
  packetsInboxPath,
} from "../../bridge/config.js";

export function usePacketWatcher(
  projectRoot: string,
  enabled: boolean,
): PacketEvent[] {
  const [events, setEvents] = useState<PacketEvent[]>([]);
  const watcherRef = useRef<ReturnType<typeof watch> | null>(null);

  useEffect(() => {
    if (!enabled) return;

    const outboxDir = packetsOutboxPath(projectRoot);
    const inboxDir = packetsInboxPath(projectRoot);

    const watcher = watch([outboxDir, inboxDir], {
      ignoreInitial: true,
      awaitWriteFinish: { stabilityThreshold: 300, pollInterval: 100 },
    });

    watcherRef.current = watcher;

    watcher.on("add", (filePath: string) => {
      if (!filePath.endsWith(".json")) return;

      try {
        const raw = readFileSync(filePath, "utf-8");
        const packet = JSON.parse(raw) as TaskPacket | ResultPacket;
        const direction = filePath.includes("/outbox/")
          ? ("outbox" as const)
          : ("inbox" as const);
        const agent =
          direction === "outbox"
            ? (packet as TaskPacket).to_agent
            : (packet as ResultPacket).from_agent;
        const title =
          direction === "outbox"
            ? (packet as TaskPacket).title
            : (packet as ResultPacket).summary?.slice(0, 60) ?? "result";
        const status =
          direction === "outbox"
            ? "delegated"
            : (packet as ResultPacket).status ?? "unknown";

        const event: PacketEvent = {
          direction,
          filePath,
          fileName: basename(filePath),
          agent,
          title,
          status,
          timestamp: Date.now(),
          packet,
        };

        setEvents((prev) => [...prev, event]);
      } catch {
        // Skip unparseable files
      }
    });

    return () => {
      watcher.close();
      watcherRef.current = null;
    };
  }, [projectRoot, enabled]);

  return events;
}
