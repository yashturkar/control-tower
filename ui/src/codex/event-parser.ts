import type { ThreadEvent, ThreadItem } from "@openai/codex-sdk";
import type { TowerEvent } from "../types.js";

/**
 * Parse a raw Codex SDK ThreadEvent into a typed TowerEvent.
 */
export function parseStreamEvent(event: ThreadEvent): TowerEvent | null {
  const now = Date.now();

  if (event.type === "item.completed") {
    return parseItem(event.item, now);
  }

  if (event.type === "item.started" || event.type === "item.updated") {
    // For started/updated we still parse to show real-time progress
    return parseItem(event.item, now);
  }

  if (event.type === "turn.completed") {
    return { type: "turn_completed", finalResponse: "", timestamp: now };
  }

  return null;
}

function parseItem(item: ThreadItem, now: number): TowerEvent | null {
  switch (item.type) {
    case "agent_message":
      return {
        type: "message",
        text: item.text,
        role: "assistant",
        timestamp: now,
      };

    case "command_execution":
      return {
        type: "tool_call",
        tool: "shell",
        args: item.command,
        timestamp: now,
      };

    case "mcp_tool_call":
      return {
        type: "tool_call",
        tool: `${item.server}:${item.tool}`,
        args: typeof item.arguments === "string"
          ? item.arguments
          : JSON.stringify(item.arguments ?? ""),
        timestamp: now,
      };

    case "file_change":
      return {
        type: "tool_call",
        tool: "file_change",
        args: item.changes.map((c) => `${c.kind} ${c.path}`).join(", "),
        timestamp: now,
      };

    case "reasoning":
      // Skip reasoning items — these are internal
      return null;

    case "web_search":
      return {
        type: "tool_call",
        tool: "web_search",
        args: item.query,
        timestamp: now,
      };

    case "todo_list":
      // Skip todo list items
      return null;

    case "error":
      return {
        type: "message",
        text: `Error: ${item.message}`,
        role: "assistant",
        timestamp: now,
      };

    default:
      return null;
  }
}

/**
 * Check if a TowerEvent represents a delegation-related tool call.
 */
export function isDelegationEvent(event: TowerEvent): boolean {
  if (event.type !== "tool_call") return false;
  return (
    event.args.includes("tower-run delegate") ||
    event.args.includes("tower-run create-packet")
  );
}

/**
 * Check if a TowerEvent represents a memory sync call.
 */
export function isMemorySyncEvent(event: TowerEvent): boolean {
  if (event.type !== "tool_call") return false;
  return event.args.includes("tower-run sync-memory");
}

/**
 * Extract the agent name from a delegation tool call event, if present.
 */
export function extractAgentFromEvent(event: TowerEvent): string | null {
  if (event.type !== "tool_call") return null;
  const agents = ["builder", "inspector", "scout", "git-master", "scribe"];
  for (const agent of agents) {
    if (event.args.includes(agent)) return agent;
  }
  return null;
}
