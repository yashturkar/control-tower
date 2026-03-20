import { useState, useEffect, useRef } from "react";
import type { Codex } from "@openai/codex-sdk";
import type { TowerEvent, CodexOptions } from "../../types.js";
import type { CodexClientConfig } from "../../codex/client.js";
import {
  startTowerSession,
  resumeTowerSession,
} from "../../codex/tower-thread.js";
import { syncMemory } from "../../bridge/python.js";
import { readRuntimeState } from "../../bridge/config.js";

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

    async function run() {
      setIsRunning(true);

      try {
        let stream: AsyncGenerator<TowerEvent>;

        if (options.resume) {
          const runtime = readRuntimeState(options.projectRoot);
          const threadId =
            options.sessionId ?? runtime.last_tower_session_id;
          if (!threadId) {
            throw new Error("No session ID found to resume.");
          }
          stream = resumeTowerSession(codex!, {
            threadId,
            prompt: options.userPrompt,
            workingDirectory: options.projectRoot,
            clientConfig,
          });
        } else {
          stream = startTowerSession(codex!, {
            workingDirectory: options.projectRoot,
            prompt: assembledPrompt!,
            clientConfig,
          });
        }

        for await (const event of stream) {
          if (cancelled) break;
          setEvents((prev) => [...prev, event]);
        }

        if (!cancelled) {
          setIsComplete(true);
          // Sync memory after session completes
          try {
            syncMemory(options.projectRoot);
          } catch {
            // Non-fatal
          }
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
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
