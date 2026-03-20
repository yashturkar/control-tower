import React from "react";
import { Box, Text } from "ink";
import type { MemoryStatus, AgentStatus } from "../../types.js";
import { MemoryIndicator } from "./memory-indicator.js";

interface StatusBarProps {
  projectName: string;
  branch: string;
  agents: AgentStatus[];
  memoryStatus: MemoryStatus;
}

export function StatusBar({
  projectName,
  branch,
  agents,
  memoryStatus,
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
      <MemoryIndicator status={memoryStatus} />
    </Box>
  );
}
