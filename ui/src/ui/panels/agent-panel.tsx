import React from "react";
import { Box, Text } from "ink";
import Spinner from "ink-spinner";
import type { AgentStatus } from "../../types.js";
import { AGENT_COLORS } from "../../constants.js";
import type { AgentKey } from "../../types.js";

interface AgentPanelProps {
  agents: AgentStatus[];
}

function formatElapsed(startedAt: number | null): string {
  if (!startedAt) return "--   ";
  const elapsed = Math.floor((Date.now() - startedAt) / 1000);
  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  return `${mins}:${secs.toString().padStart(2, "0")} `;
}

function StateIcon({ state }: { state: AgentStatus["state"] }) {
  switch (state) {
    case "idle":
      return <Text dimColor>○</Text>;
    case "running":
      return (
        <Text color="yellow">
          <Spinner type="dots" />
        </Text>
      );
    case "completed":
      return <Text color="green">●</Text>;
    case "failed":
      return <Text color="red">●</Text>;
  }
}

function AgentRow({ agent }: { agent: AgentStatus }) {
  const color = AGENT_COLORS[agent.key as AgentKey] ?? "white";

  return (
    <Box>
      <StateIcon state={agent.state} />
      <Text color={color} bold>
        {" "}
        {agent.displayName.padEnd(12)}
      </Text>
      <Text
        color={
          agent.state === "running"
            ? "yellow"
            : agent.state === "completed"
              ? "green"
              : agent.state === "failed"
                ? "red"
                : undefined
        }
        dimColor={agent.state === "idle"}
      >
        {agent.state.toUpperCase().padEnd(10)}
      </Text>
      <Text dimColor>{formatElapsed(agent.startedAt)}</Text>
      {agent.taskTitle && (
        <Text dimColor> {agent.taskTitle.slice(0, 40)}</Text>
      )}
    </Box>
  );
}

export function AgentPanel({ agents }: AgentPanelProps) {
  return (
    <Box flexDirection="column" borderStyle="single" borderColor="gray" paddingX={1} width="100%">
      <Text bold dimColor>
        Agents
      </Text>
      {agents.map((agent) => (
        <AgentRow key={agent.key} agent={agent} />
      ))}
    </Box>
  );
}
