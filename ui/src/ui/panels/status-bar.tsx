import React from "react";
import { Box, Text } from "ink";
import type { MemoryStatus, AgentStatus, TokenUsage } from "../../types.js";
import { MemoryIndicator } from "./memory-indicator.js";

interface StatusBarProps {
  projectName: string;
  branch: string;
  agents: AgentStatus[];
  memoryStatus: MemoryStatus;
  usage: TokenUsage;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function ContextIndicator({ usage }: { usage: TokenUsage }) {
  const total = usage.inputTokens + usage.outputTokens;
  if (total === 0) return null;

  // Codex models typically have 200k context
  const contextLimit = 200_000;
  const pct = Math.round((usage.inputTokens / contextLimit) * 100);
  const color = pct > 80 ? "red" : pct > 60 ? "yellow" : "green";

  return (
    <Text color={color}>
      {formatTokens(total)} tokens ({pct}%)
    </Text>
  );
}

export function StatusBar({
  projectName,
  branch,
  agents,
  memoryStatus,
  usage,
}: StatusBarProps) {
  const activeCount = agents.filter((a) => a.state === "running").length;

  return (
    <Box
      borderStyle="single"
      borderColor="cyan"
      paddingX={1}
      justifyContent="space-between"
    >
      <Box>
        <Text bold color="cyan">
          CONTROL TOWER
        </Text>
        <Text>{"  "}</Text>
        <Text>{projectName}</Text>
        <Text>{"  "}</Text>
        <Text dimColor>{branch}</Text>
        {activeCount > 0 && (
          <>
            <Text>{"  "}</Text>
            <Text color="yellow">
              {activeCount} agent{activeCount > 1 ? "s" : ""} active
            </Text>
          </>
        )}
      </Box>
      <Box>
        <ContextIndicator usage={usage} />
        <Text>{"  "}</Text>
        <MemoryIndicator status={memoryStatus} />
      </Box>
    </Box>
  );
}
