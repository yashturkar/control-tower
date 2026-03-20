import type { Codex, Thread, ThreadEvent, Usage } from "@openai/codex-sdk";
import { buildThreadOptions, type CodexClientConfig } from "./client.js";
import { parseStreamEvent } from "./event-parser.js";
import type { TowerEvent } from "../types.js";

export interface TowerSessionOptions {
  workingDirectory: string;
  prompt: string;
  clientConfig: CodexClientConfig;
}

export interface TowerResumeOptions {
  threadId: string;
  prompt?: string;
  workingDirectory: string;
  clientConfig: CodexClientConfig;
}

/** Callback invoked when the SDK emits a thread.started event with the thread ID. */
export type OnThreadId = (threadId: string) => void;

/** Callback invoked for each parsed TowerEvent. */
export type OnTowerEvent = (event: TowerEvent) => void;

/**
 * Manages a Tower thread that supports multiple turns.
 * The thread stays alive between turns so the user can send follow-up messages.
 */
export class TowerSession {
  private thread: Thread;
  private onThreadId?: OnThreadId;

  constructor(thread: Thread, onThreadId?: OnThreadId) {
    this.thread = thread;
    this.onThreadId = onThreadId;
  }

  /**
   * Run a single turn and emit parsed events via the callback.
   * Returns usage stats when the turn completes.
   */
  async runTurn(prompt: string, onEvent: OnTowerEvent): Promise<Usage | null> {
    const streamedTurn = await this.thread.runStreamed(prompt);
    let turnUsage: Usage | null = null;

    for await (const event of streamedTurn.events) {
      if (event.type === "thread.started" && this.onThreadId) {
        this.onThreadId(event.thread_id);
        this.onThreadId = undefined; // Only capture once
      }
      if (event.type === "turn.completed") {
        turnUsage = event.usage;
      }
      const parsed = parseStreamEvent(event);
      if (parsed) {
        onEvent(parsed);
      }
    }

    return turnUsage;
  }
}

/**
 * Create a new Tower session (new thread).
 */
export function createTowerSession(
  codex: Codex,
  options: TowerSessionOptions,
  onThreadId?: OnThreadId,
): TowerSession {
  const threadOpts = buildThreadOptions(
    options.workingDirectory,
    options.clientConfig,
  );
  const thread = codex.startThread(threadOpts);
  return new TowerSession(thread, onThreadId);
}

/**
 * Resume an existing Tower session.
 */
export function resumeTowerSession(
  codex: Codex,
  options: TowerResumeOptions,
  onThreadId?: OnThreadId,
): TowerSession {
  const threadOpts = buildThreadOptions(
    options.workingDirectory,
    options.clientConfig,
  );
  const thread = codex.resumeThread(options.threadId, threadOpts);
  return new TowerSession(thread, onThreadId);
}
