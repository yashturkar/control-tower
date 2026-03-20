import { useState, useEffect, useCallback } from "react";
import type { BootStep, CodexOptions } from "../../types.js";
import { INITIAL_BOOT_STEPS } from "../../constants.js";
import { initProject, syncMemory, buildTowerPrompt } from "../../bridge/python.js";

export interface BootSequenceResult {
  steps: BootStep[];
  isReady: boolean;
  error: string | null;
  assembledPrompt: string | null;
}

export function useBootSequence(options: CodexOptions): BootSequenceResult {
  const [steps, setSteps] = useState<BootStep[]>(
    INITIAL_BOOT_STEPS.map((s) => ({ ...s })),
  );
  const [isReady, setIsReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [assembledPrompt, setAssembledPrompt] = useState<string | null>(null);

  const updateStep = useCallback(
    (name: string, state: BootStep["state"], err?: string) => {
      setSteps((prev) =>
        prev.map((s) =>
          s.name === name ? { ...s, state, error: err } : s,
        ),
      );
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      try {
        // Step 1: Init
        updateStep("init", "running");
        try {
          initProject(options.projectRoot);
        } catch {
          // Init is idempotent, continue even if already initialized
        }
        if (cancelled) return;
        updateStep("init", "done");

        // Step 2: Sync memory
        updateStep("sync", "running");
        try {
          syncMemory(options.projectRoot);
        } catch {
          // Non-fatal: sync may fail if no sessions exist yet
        }
        if (cancelled) return;
        updateStep("sync", "done");

        // Step 3: Assemble prompt
        updateStep("prompt", "running");
        const prompt = buildTowerPrompt(
          options.projectRoot,
          options.userPrompt,
        );
        if (cancelled) return;
        setAssembledPrompt(prompt);
        updateStep("prompt", "done");

        // Step 4: Thread ready (actual thread creation happens in useTowerSession)
        updateStep("thread", "running");
        // Small delay to show the step
        await new Promise((r) => setTimeout(r, 200));
        if (cancelled) return;
        updateStep("thread", "done");

        setIsReady(true);
      } catch (err) {
        if (cancelled) return;
        const message =
          err instanceof Error ? err.message : String(err);
        setError(message);
        // Mark current running step as error
        setSteps((prev) =>
          prev.map((s) =>
            s.state === "running" ? { ...s, state: "error", error: message } : s,
          ),
        );
      }
    }

    boot();
    return () => {
      cancelled = true;
    };
  }, [options.projectRoot, options.userPrompt, updateStep]);

  return { steps, isReady, error, assembledPrompt };
}
