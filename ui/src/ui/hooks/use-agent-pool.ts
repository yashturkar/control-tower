import { useState, useEffect } from "react";
import type {
  AgentKey,
  AgentStatus,
  PacketEvent,
} from "../../types.js";
import { AGENT_KEYS, AGENT_DISPLAY_NAMES } from "../../constants.js";

function createInitialAgentStatuses(): AgentStatus[] {
  return AGENT_KEYS.map((key) => ({
    key,
    displayName: AGENT_DISPLAY_NAMES[key],
    state: "idle" as const,
    startedAt: null,
    taskTitle: null,
    resultStatus: null,
  }));
}

export function useAgentPool(packetEvents: PacketEvent[]): AgentStatus[] {
  const [agents, setAgents] = useState<AgentStatus[]>(
    createInitialAgentStatuses(),
  );

  useEffect(() => {
    const updated = createInitialAgentStatuses();

    // Process events chronologically to build up agent states
    for (const event of packetEvents) {
      const agentKey = event.agent as AgentKey;
      const agent = updated.find((a) => a.key === agentKey);
      if (!agent) continue;

      if (event.direction === "outbox") {
        agent.state = "running";
        agent.startedAt = event.timestamp;
        agent.taskTitle = event.title;
        agent.resultStatus = null;
      } else if (event.direction === "inbox") {
        const resultPacket = event.packet;
        if ("status" in resultPacket) {
          agent.state =
            resultPacket.status === "success" || resultPacket.status === "partial"
              ? "completed"
              : "failed";
          agent.resultStatus = resultPacket.status;
        } else {
          agent.state = "completed";
        }
      }
    }

    setAgents(updated);
  }, [packetEvents]);

  return agents;
}
