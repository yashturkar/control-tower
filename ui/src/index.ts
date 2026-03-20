#!/usr/bin/env node

import React from "react";
import { render } from "ink";
import { resolve } from "node:path";
import { App } from "./app.js";
import type { CodexOptions } from "./types.js";

function parseArgs(argv: string[]): CodexOptions {
  const args = argv.slice(2);
  const options: CodexOptions = {
    projectRoot: process.cwd(),
  };

  let i = 0;
  const positional: string[] = [];

  while (i < args.length) {
    const arg = args[i]!;

    if (arg === "--project-root" && args[i + 1]) {
      options.projectRoot = resolve(args[++i]!);
    } else if (arg === "--model" && args[i + 1]) {
      options.model = args[++i];
    } else if (arg === "--sandbox" && args[i + 1]) {
      options.sandbox = args[++i];
    } else if (arg === "--approval" && args[i + 1]) {
      options.approval = args[++i];
    } else if (arg === "--search") {
      options.search = true;
    } else if (arg === "--no-search") {
      options.search = false;
    } else if (arg === "--dangerous") {
      options.dangerous = true;
    } else if (arg === "--no-dangerous") {
      options.dangerous = false;
    } else if (arg === "--resume") {
      options.resume = true;
    } else if (arg === "--session-id" && args[i + 1]) {
      options.sessionId = args[++i];
    } else if (!arg.startsWith("--")) {
      positional.push(arg);
    }

    i++;
  }

  if (positional.length > 0) {
    options.userPrompt = positional.join(" ");
  }

  return options;
}

const options = parseArgs(process.argv);

const { waitUntilExit } = render(
  React.createElement(App, { options }),
);

waitUntilExit().then(() => {
  process.exit(0);
}).catch((err: unknown) => {
  console.error("Tower UI error:", err);
  process.exit(1);
});
