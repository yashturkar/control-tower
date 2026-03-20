import React, { useMemo } from "react";
import { Box, Text } from "ink";
import type { TowerEvent } from "../../types.js";

interface TowerPanelProps {
  events: TowerEvent[];
  isRunning: boolean;
  isComplete: boolean;
  maxLines?: number;
}

/** Friendly label for shell tool calls instead of raw commands. */
function summarizeToolCall(tool: string, args: string): string | null {
  if (tool === "shell") {
    if (args.includes("tower-run delegate")) {
      const agentMatch = args.match(/delegate\s+(\w[\w-]*)/);
      return agentMatch ? `Delegating to ${agentMatch[1]}` : "Delegating to agent";
    }
    if (args.includes("tower-run create-packet")) return "Creating task packet";
    if (args.includes("tower-run sync-memory")) return "Syncing memory";
    if (args.includes("tower-run")) {
      const subMatch = args.match(/tower-run\s+([\w-]+)/);
      return subMatch ? `tower-run ${subMatch[1]}` : "Running tower-run";
    }
    // Generic shell commands that aren't tower-related — collapse
    return null;
  }
  if (tool === "file_change") return `File changes: ${args.slice(0, 80)}`;
  if (tool === "web_search") return `Searching: ${args.slice(0, 80)}`;
  return `[${tool}] ${args.slice(0, 80)}`;
}

interface DisplayLine {
  prefix: string;
  color: string;
  text: string;
}

/**
 * Collapse raw events into display lines.
 * Consecutive skippable tool calls (generic shell commands) are merged
 * into a single "[N tool calls]" summary line.
 */
function collapseEvents(events: TowerEvent[]): DisplayLine[] {
  const lines: DisplayLine[] = [];
  let skippedCount = 0;

  function flushSkipped() {
    if (skippedCount > 0) {
      lines.push({
        prefix: "> Tower:",
        color: "gray",
        text: `[${skippedCount} shell command${skippedCount > 1 ? "s" : ""}]`,
      });
      skippedCount = 0;
    }
  }

  for (const event of events) {
    if (event.type === "message") {
      flushSkipped();
      lines.push({
        prefix: event.role === "user" ? "> User:" : "> Tower:",
        color: event.role === "user" ? "green" : "white",
        text: event.text,
      });
    } else if (event.type === "tool_call") {
      const summary = summarizeToolCall(event.tool, event.args);
      if (summary === null) {
        // Generic/noisy shell command — collapse
        skippedCount++;
      } else {
        flushSkipped();
        lines.push({ prefix: "> Tower:", color: "yellow", text: summary });
      }
    } else if (event.type === "turn_completed") {
      flushSkipped();
      if (event.finalResponse) {
        lines.push({ prefix: "> Tower:", color: "cyan", text: event.finalResponse });
      }
    }
  }

  flushSkipped();
  return lines;
}

export function TowerPanel({
  events,
  isRunning,
  isComplete,
  maxLines = 20,
}: TowerPanelProps) {
  const displayLines = useMemo(() => collapseEvents(events), [events]);
  const visible = displayLines.slice(-maxLines);

  return (
    <Box flexDirection="column" flexGrow={1} borderStyle="single" borderColor="cyan" paddingX={1} overflow="hidden" width="100%">
      <Box justifyContent="space-between" width="100%">
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

      {visible.map((line, i) => (
        <Box key={i} width="100%">
          <Text color={line.color} bold>
            {line.prefix}{" "}
          </Text>
          <Text wrap="wrap">{line.text}</Text>
        </Box>
      ))}
    </Box>
  );
}
