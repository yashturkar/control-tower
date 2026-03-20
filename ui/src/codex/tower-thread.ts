import type { Codex, ThreadEvent } from "@openai/codex-sdk";
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

/**
 * Start a new Tower session and return an async iterable of parsed events.
 */
export async function* startTowerSession(
  codex: Codex,
  options: TowerSessionOptions,
  onThreadId?: OnThreadId,
): AsyncGenerator<TowerEvent> {
  const threadOpts = buildThreadOptions(
    options.workingDirectory,
    options.clientConfig,
  );
  const thread = codex.startThread(threadOpts);
  const streamedTurn = await thread.runStreamed(options.prompt);

  for await (const event of streamedTurn.events) {
    // Capture thread ID when the SDK emits it
    if (event.type === "thread.started" && onThreadId) {
      onThreadId(event.thread_id);
    }
    const parsed = parseStreamEvent(event);
    if (parsed) {
      yield parsed;
    }
  }
}

/**
 * Resume an existing Tower session and return an async iterable of parsed events.
 */
export async function* resumeTowerSession(
  codex: Codex,
  options: TowerResumeOptions,
  onThreadId?: OnThreadId,
): AsyncGenerator<TowerEvent> {
  const threadOpts = buildThreadOptions(
    options.workingDirectory,
    options.clientConfig,
  );
  const thread = codex.resumeThread(options.threadId, threadOpts);

  const prompt =
    options.prompt ??
    "Resume control of the project and report the next best action.";

  const streamedTurn = await thread.runStreamed(prompt);

  for await (const event of streamedTurn.events) {
    if (event.type === "thread.started" && onThreadId) {
      onThreadId(event.thread_id);
    }
    const parsed = parseStreamEvent(event);
    if (parsed) {
      yield parsed;
    }
  }
}
