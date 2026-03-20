import React from "react";
import { Box, Text } from "ink";
import type { TowerEvent } from "../../types.js";

interface TowerPanelProps {
  events: TowerEvent[];
  isRunning: boolean;
  isComplete: boolean;
  maxLines?: number;
}

function formatEvent(event: TowerEvent): { prefix: string; color: string; text: string } {
  switch (event.type) {
    case "message":
      return {
        prefix: event.role === "user" ? "> User:" : "> Tower:",
        color: event.role === "user" ? "green" : "white",
        text: event.text,
      };
    case "tool_call":
      return {
        prefix: "> Tower:",
        color: "yellow",
        text: `[${event.tool}] ${event.args.slice(0, 120)}`,
      };
    case "turn_completed":
      return {
        prefix: "> Tower:",
        color: "cyan",
        text: event.finalResponse || "(turn completed)",
      };
  }
}

export function TowerPanel({
  events,
  isRunning,
  isComplete,
  maxLines = 20,
}: TowerPanelProps) {
  const visible = events.slice(-maxLines);

  return (
    <Box flexDirection="column" borderStyle="single" borderColor="cyan" paddingX={1}>
      <Box justifyContent="space-between">
        <Text bold color="cyan">
          Tower
        </Text>
        <Text dimColor>
          {isRunning ? "Running" : isComplete ? "Complete" : "Ready"}
        </Text>
      </Box>

      {visible.length === 0 && (
        <Text dimColor>Waiting for Tower response...</Text>
      )}

      {visible.map((event, i) => {
        const formatted = formatEvent(event);
        return (
          <Box key={i}>
            <Text color={formatted.color} bold>
              {formatted.prefix}{" "}
            </Text>
            <Text wrap="wrap">{formatted.text}</Text>
          </Box>
        );
      })}
    </Box>
  );
}
