import React from "react";
import { Box, Text } from "ink";
import type { PacketEvent } from "../../types.js";

interface PacketFlowProps {
  events: PacketEvent[];
  maxItems?: number;
}

function statusColor(status: string): string {
  switch (status.toLowerCase()) {
    case "success":
      return "green";
    case "partial":
      return "yellow";
    case "blocked":
      return "red";
    case "failed":
      return "red";
    case "delegated":
      return "cyan";
    default:
      return "white";
  }
}

export function PacketFlow({ events, maxItems = 6 }: PacketFlowProps) {
  const visible = events.slice(-maxItems);

  return (
    <Box flexDirection="column" borderStyle="single" borderColor="gray" paddingX={1}>
      <Text bold dimColor>
        Packets
      </Text>
      {visible.length === 0 && (
        <Text dimColor>No packet activity yet</Text>
      )}
      {visible.map((event, i) => {
        const arrow = event.direction === "outbox" ? "→" : "←";
        const arrowColor = event.direction === "outbox" ? "cyan" : "green";

        return (
          <Box key={i}>
            <Text color={arrowColor}>{arrow} </Text>
            <Text>{event.fileName.slice(0, 45).padEnd(46)}</Text>
            <Text color={statusColor(event.status)}>
              {event.status.toUpperCase()}
            </Text>
            {event.direction === "inbox" && "artifacts_changed" in event.packet && (
              <Text dimColor>
                {" "}
                {(event.packet as { artifacts_changed: string[] }).artifacts_changed
                  .length}{" "}
                files
              </Text>
            )}
          </Box>
        );
      })}
    </Box>
  );
}
