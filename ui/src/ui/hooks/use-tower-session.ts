import { useState, useEffect, useRef } from "react";
import type { Codex } from "@openai/codex-sdk";
import type { TowerEvent, CodexOptions } from "../../types.js";
import type { CodexClientConfig } from "../../codex/client.js";
import {
  startTowerSession,
  resumeTowerSession,
} from "../../codex/tower-thread.js";
import { syncMemory } from "../../bridge/python.js";
import { readRuntimeState, saveSessionId } from "../../bridge/config.js";

export interface TowerSessionState {
  events: TowerEvent[];
  isRunning: boolean;
  isComplete: boolean;
  error: string | null;
}

export function useTowerSession(
  codex: Codex | null,
  options: CodexOptions,
  assembledPrompt: string | null,
  isReady: boolean,
): TowerSessionState {
  const [events, setEvents] = useState<TowerEvent[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [isComplete, setIsComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const startedRef = useRef(false);

  useEffect(() => {
    if (!isReady || !codex || !assembledPrompt || startedRef.current) return;
    startedRef.current = true;

    let cancelled = false;

    const clientConfig: CodexClientConfig = {
      model: options.model,
      sandbox: options.sandbox,
      approval: options.approval,
      dangerous: options.dangerous,
    };

    /** Persist thread ID to runtime.json as soon as the SDK provides it. */
    function onThreadId(threadId: string) {
      try {
        saveSessionId(options.projectRoot, threadId);
      } catch {
        // Non-fatal — resume will fall back to session file scan
      }
    }

    /** Best-effort memory sync (used on both clean exit and SIGINT). */
    function cleanup() {
      try {
        syncMemory(options.projectRoot);
      } catch {
        // Non-fatal
      }
    }

    async function run() {
      setIsRunning(true);

      // Run cleanup on SIGINT so Ctrl+C still persists state
      const sigintHandler = () => {
        cleanup();
        process.exit(0);
      };
      process.on("SIGINT", sigintHandler);

      try {
        let stream: AsyncGenerator<TowerEvent>;

        if (options.resume) {
          const runtime = readRuntimeState(options.projectRoot);
          const threadId =
            options.sessionId ?? runtime.last_tower_session_id;
          if (!threadId) {
            throw new Error(
              "No session ID found to resume. Run `tower start` first to create a session.",
            );
          }
          stream = resumeTowerSession(codex!, {
            threadId,
            prompt: options.userPrompt,
            workingDirectory: options.projectRoot,
            clientConfig,
          }, onThreadId);
        } else {
          stream = startTowerSession(codex!, {
            workingDirectory: options.projectRoot,
            prompt: assembledPrompt!,
            clientConfig,
          }, onThreadId);
        }

        for await (const event of stream) {
          if (cancelled) break;
          setEvents((prev) => [...prev, event]);
        }

        if (!cancelled) {
          setIsComplete(true);
          cleanup();
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        process.removeListener("SIGINT", sigintHandler);
        if (!cancelled) {
          setIsRunning(false);
        }
      }
    }

    run();

    return () => {
      cancelled = true;
    };
  }, [isReady, codex, assembledPrompt, options]);

  return { events, isRunning, isComplete, error };
}
