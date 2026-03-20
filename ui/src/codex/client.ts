import { Codex, type CodexOptions as SdkCodexOptions } from "@openai/codex-sdk";

export interface CodexClientConfig {
  model?: string;
  sandbox?: string;
  approval?: string;
  dangerous?: boolean;
}

/**
 * Create a Codex SDK client configured for the given project.
 */
export function createCodexClient(options: CodexClientConfig): Codex {
  const sdkOptions: SdkCodexOptions = {
    env: {
      ...process.env as Record<string, string>,
      OTEL_SDK_DISABLED: "true",
    },
  };

  return new Codex(sdkOptions);
}

/**
 * Build ThreadOptions from our config.
 * Thread-level options like model, sandbox, approval are set per-thread.
 */
export function buildThreadOptions(
  workingDirectory: string,
  config: CodexClientConfig,
) {
  return {
    workingDirectory,
    ...(config.model ? { model: config.model } : {}),
    ...(config.sandbox ? { sandboxMode: config.sandbox as "read-only" | "workspace-write" | "danger-full-access" } : {}),
    ...(config.approval ? { approvalPolicy: config.approval as "never" | "on-request" | "on-failure" | "untrusted" } : {}),
    ...(config.dangerous ? { sandboxMode: "danger-full-access" as const, approvalPolicy: "never" as const } : {}),
  };
}
