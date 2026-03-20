// ── Agent types ──────────────────────────────────────────────────────────────

export type AgentKey = "builder" | "inspector" | "scout" | "git-master" | "scribe";

export type AgentState = "idle" | "running" | "completed" | "failed";

export interface AgentStatus {
  key: AgentKey;
  displayName: string;
  state: AgentState;
  startedAt: number | null;
  taskTitle: string | null;
  resultStatus: ResultStatus | null;
}

// ── Packet types (mirror JSON schemas) ───────────────────────────────────────

export type Priority = "low" | "normal" | "high" | "critical";
export type ResultStatus = "success" | "partial" | "blocked" | "failed";
export type FindingSeverity = "info" | "warning" | "high" | "critical";

export interface TaskPacket {
  schema_version: string;
  packet_type: "task";
  packet_id: string;
  trace_id: string;
  parent_packet_id: string | null;
  created_at: string;
  from_agent: string;
  to_agent: string;
  task_type: string;
  priority: Priority;
  project_id: string;
  session_id: string;
  title: string;
  objective: string;
  instructions: string[];
  constraints: string[];
  inputs: {
    files: string[];
    artifacts: string[];
    references: string[];
  };
  expected_outputs: string[];
  definition_of_done: string[];
  memory_context_refs: string[];
  doc_context_refs: string[];
  time_budget: {
    soft_seconds: number;
    hard_seconds: number;
  };
  requires_review: boolean;
  allow_partial: boolean;
  metadata: Record<string, unknown>;
}

export interface Finding {
  severity: FindingSeverity;
  message: string;
}

export interface ResultPacket {
  schema_version: string;
  packet_type: "result";
  packet_id: string;
  trace_id: string;
  parent_packet_id: string;
  created_at: string;
  from_agent: string;
  to_agent: string;
  status: ResultStatus;
  summary: string;
  work_completed: string[];
  artifacts_changed: string[];
  artifacts_created: string[];
  artifacts_deleted: string[];
  findings: Finding[];
  follow_up_recommendations: string[];
  review_requested: boolean;
  doc_update_needed: boolean;
  memory_worthy: string[];
  metrics: {
    tokens_used: number;
    files_touched: number;
    tests_added: number;
    tests_passed: number;
  };
  raw_output_ref: string | null;
  metadata: Record<string, unknown>;
}

// ── Packet watcher events ────────────────────────────────────────────────────

export type PacketDirection = "outbox" | "inbox";

export interface PacketEvent {
  direction: PacketDirection;
  filePath: string;
  fileName: string;
  agent: string;
  title: string;
  status: string;
  timestamp: number;
  packet: TaskPacket | ResultPacket;
}

// ── Tower stream events ──────────────────────────────────────────────────────

export type TowerEventType = "message" | "tool_call" | "turn_completed";

export interface TowerMessageEvent {
  type: "message";
  text: string;
  role: "assistant" | "user";
  timestamp: number;
}

export interface TowerToolCallEvent {
  type: "tool_call";
  tool: string;
  args: string;
  timestamp: number;
}

export interface TowerTurnCompletedEvent {
  type: "turn_completed";
  finalResponse: string;
  timestamp: number;
}

export type TowerEvent =
  | TowerMessageEvent
  | TowerToolCallEvent
  | TowerTurnCompletedEvent;

// ── Memory watcher ───────────────────────────────────────────────────────────

export type MemoryState = "idle" | "reading" | "storing" | "syncing";

export interface MemoryStatus {
  state: MemoryState;
  detail: string;
}

// ── Boot sequence ────────────────────────────────────────────────────────────

export type BootStepName = "init" | "sync" | "prompt" | "thread";
export type BootStepState = "pending" | "running" | "done" | "error";

export interface BootStep {
  name: BootStepName;
  label: string;
  state: BootStepState;
  error?: string;
}

// ── Token usage ─────────────────────────────────────────────────────────────

export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  cachedInputTokens: number;
}

// ── Codex options ────────────────────────────────────────────────────────────

export interface CodexOptions {
  projectRoot: string;
  model?: string;
  sandbox?: string;
  approval?: string;
  search?: boolean;
  dangerous?: boolean;
  resume?: boolean;
  sessionId?: string;
  userPrompt?: string;
}

// ── Config types (from .control-tower/state/) ────────────────────────────────

export interface AgentRegistryEntry {
  name: string;
  role: string;
  description: string;
  enabled: boolean;
  model: string | null;
  dangerously_bypass: boolean;
  sandbox: string;
  search: boolean;
}

export interface AgentRegistry {
  agents: Record<string, AgentRegistryEntry>;
}

export interface ProjectConfig {
  project_name: string;
  codex_defaults?: {
    model?: string;
    sandbox?: string;
    approval?: string;
    search?: boolean;
    dangerously_bypass?: boolean;
  };
  docs_harness?: {
    enabled?: boolean;
    mode?: string;
    doc_roots?: string[];
    auto_scribe_mode?: string;
    auto_scribe_agents?: string[];
  };
  [key: string]: unknown;
}

export interface RuntimeState {
  last_tower_session_id?: string;
  last_imported_session_id?: string;
  last_sync_time?: string;
  git_branch?: string;
  last_agent_sessions?: Record<string, string>;
  [key: string]: unknown;
}
