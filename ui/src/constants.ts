import type { AgentKey, BootStep } from "./types.js";

export const AGENT_KEYS: AgentKey[] = [
  "builder",
  "inspector",
  "scout",
  "git-master",
  "scribe",
];

export const AGENT_DISPLAY_NAMES: Record<AgentKey, string> = {
  builder: "Builder",
  inspector: "Inspector",
  scout: "Scout",
  "git-master": "Git-master",
  scribe: "Scribe",
};

export const AGENT_COLORS: Record<AgentKey, string> = {
  builder: "cyan",
  inspector: "yellow",
  scout: "green",
  "git-master": "magenta",
  scribe: "blue",
};

export const INITIAL_BOOT_STEPS: BootStep[] = [
  { name: "init", label: "Initializing project", state: "pending" },
  { name: "sync", label: "Syncing memory", state: "pending" },
  { name: "prompt", label: "Assembling prompt", state: "pending" },
  { name: "thread", label: "Starting thread", state: "pending" },
];

export const TOWER_DIR_NAME = ".control-tower";
export const PACKETS_OUTBOX = "packets/outbox";
export const PACKETS_INBOX = "packets/inbox";
export const MEMORY_DIR = "memory";
