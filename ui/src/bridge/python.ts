import { execFileSync } from "node:child_process";
import { resolve } from "node:path";

/**
 * Execute the `tower` CLI with the given arguments.
 * Returns stdout as a string.
 */
export function execTower(
  args: string[],
  projectRoot: string,
): string {
  return execFileSync("tower", args, {
    cwd: projectRoot,
    encoding: "utf-8",
    env: { ...process.env, OTEL_SDK_DISABLED: "true" },
    stdio: ["pipe", "pipe", "pipe"],
  }).trim();
}

/**
 * Execute the `tower-run` CLI with the given arguments.
 * Returns stdout as a string.
 */
export function execTowerRun(
  args: string[],
  projectRoot: string,
): string {
  return execFileSync("tower-run", args, {
    cwd: projectRoot,
    encoding: "utf-8",
    env: { ...process.env, OTEL_SDK_DISABLED: "true" },
    stdio: ["pipe", "pipe", "pipe"],
  }).trim();
}

/**
 * Initialize the project (idempotent).
 */
export function initProject(projectRoot: string): void {
  execTower(["init", "--defaults"], projectRoot);
}

/**
 * Sync memory: import Codex sessions into project memory.
 */
export function syncMemory(projectRoot: string): string {
  return execTowerRun(["sync-memory"], projectRoot);
}

/**
 * Build the assembled Tower prompt via Python.
 * Calls Python inline to invoke build_tower_prompt().
 */
export function buildTowerPrompt(
  projectRoot: string,
  userPrompt?: string,
): string {
  const promptArg = userPrompt
    ? JSON.stringify(userPrompt)
    : "None";
  const script = [
    "import sys, json",
    "from pathlib import Path",
    "from control_tower.prompts import build_tower_prompt",
    `root = Path(${JSON.stringify(resolve(projectRoot))})`,
    `prompt = build_tower_prompt(root, ${promptArg})`,
    "sys.stdout.write(prompt)",
  ].join("; ");

  return execFileSync("python3", ["-c", script], {
    cwd: projectRoot,
    encoding: "utf-8",
    env: { ...process.env, OTEL_SDK_DISABLED: "true" },
    stdio: ["pipe", "pipe", "pipe"],
  });
}
