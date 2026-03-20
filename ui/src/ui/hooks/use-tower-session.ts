import { useState, useEffect, useRef, useCallback } from "react";
import type { Codex } from "@openai/codex-sdk";
import type { TowerEvent, CodexOptions } from "../../types.js";
import type { CodexClientConfig } from "../../codex/client.js";
import {
  TowerSession,
  createTowerSession,
  resumeTowerSession,
} from "../../codex/tower-thread.js";
import { syncMemory } from "../../bridge/python.js";
import { readRuntimeState, saveSessionId } from "../../bridge/config.js";

export interface TowerSessionState {
  events: TowerEvent[];
  isRunning: boolean;
  isComplete: boolean;
  error: string | null;
  sendMessage: (text: string) => void;
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
  const sessionRef = useRef<TowerSession | null>(null);

  const appendEvent = useCallback((event: TowerEvent) => {
    setEvents((prev) => [...prev, event]);
  }, []);

  /** Run a single turn on the session. */
  const runTurn = useCallback(async (session: TowerSession, prompt: string) => {
    setIsRunning(true);
    setIsComplete(false);
    try {
      await session.runTurn(prompt, appendEvent);
      setIsComplete(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsRunning(false);
    }
  }, [appendEvent]);

  /** Send a follow-up message to Tower. */
  const sendMessage = useCallback((text: string) => {
    const session = sessionRef.current;
    if (!session || isRunning) return;

    // Add user message to the event stream
    appendEvent({
      type: "message",
      text,
      role: "user",
      timestamp: Date.now(),
    });

    runTurn(session, text);
  }, [isRunning, appendEvent, runTurn]);

  useEffect(() => {
    if (!isReady || !codex || !assembledPrompt || startedRef.current) return;
    startedRef.current = true;

    const clientConfig: CodexClientConfig = {
      model: options.model,
      sandbox: options.sandbox,
      approval: options.approval,
      dangerous: options.dangerous,
    };

    function onThreadId(threadId: string) {
      try {
        saveSessionId(options.projectRoot, threadId);
      } catch {
        // Non-fatal
      }
    }

    function cleanup() {
      try {
        syncMemory(options.projectRoot);
      } catch {
        // Non-fatal
      }
    }

    const sigintHandler = () => {
      cleanup();
      process.exit(0);
    };
    process.on("SIGINT", sigintHandler);

    let session: TowerSession;

    if (options.resume) {
      const runtime = readRuntimeState(options.projectRoot);
      const threadId = options.sessionId ?? runtime.last_tower_session_id;
      if (!threadId) {
        setError("No session ID found to resume. Run `tower start` first.");
        return;
      }
      session = resumeTowerSession(codex, {
        threadId,
        prompt: options.userPrompt,
        workingDirectory: options.projectRoot,
        clientConfig,
      }, onThreadId);
    } else {
      session = createTowerSession(codex, {
        workingDirectory: options.projectRoot,
        prompt: assembledPrompt,
        clientConfig,
      }, onThreadId);
    }

    sessionRef.current = session;

    const initialPrompt = options.resume
      ? (options.userPrompt ?? "Resume control of the project and report the next best action.")
      : assembledPrompt;

    runTurn(session, initialPrompt);

    return () => {
      process.removeListener("SIGINT", sigintHandler);
      cleanup();
    };
  }, [isReady, codex, assembledPrompt, options, runTurn]);

  return { events, isRunning, isComplete, error, sendMessage };
}
