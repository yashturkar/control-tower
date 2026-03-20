import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import type {
  AgentRegistry,
  ProjectConfig,
  RuntimeState,
} from "../types.js";
import { TOWER_DIR_NAME } from "../constants.js";

function towerDir(projectRoot: string): string {
  return join(projectRoot, TOWER_DIR_NAME);
}

function readJson<T>(path: string): T {
  const raw = readFileSync(path, "utf-8");
  return JSON.parse(raw) as T;
}

export function readProjectConfig(projectRoot: string): ProjectConfig {
  return readJson<ProjectConfig>(
    join(towerDir(projectRoot), "state", "project.json"),
  );
}

export function readAgentRegistry(projectRoot: string): AgentRegistry {
  return readJson<AgentRegistry>(
    join(towerDir(projectRoot), "state", "agent-registry.json"),
  );
}

export function readRuntimeState(projectRoot: string): RuntimeState {
  return readJson<RuntimeState>(
    join(towerDir(projectRoot), "state", "runtime.json"),
  );
}

export function towerDirPath(projectRoot: string): string {
  return towerDir(projectRoot);
}

export function packetsOutboxPath(projectRoot: string): string {
  return join(towerDir(projectRoot), "packets", "outbox");
}

export function packetsInboxPath(projectRoot: string): string {
  return join(towerDir(projectRoot), "packets", "inbox");
}

export function memoryDirPath(projectRoot: string): string {
  return join(towerDir(projectRoot), "memory");
}

export function hasTowerDir(projectRoot: string): boolean {
  return existsSync(towerDir(projectRoot));
}
