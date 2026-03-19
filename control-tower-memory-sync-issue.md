# Memory sync can self-contaminate L0/L1 by treating bootstrap-derived `## Recent User Goals` text as user intent

## Summary

`tower-run sync-memory` can still write malformed bootstrap or memory text back into persistent memory.

Current `HEAD` already filters obvious Tower role prompts such as `You are Tower ...`, so this is narrower than the original unfiltered behavior. But the current extraction logic still accepts bootstrap-derived fragments that begin at memory headings like `## Recent User Goals`, and then persists them as if they were real user goals.

That produces entries like:

- `Most recent user goal: ## Recent User Goals ...` in L0
- `- ## Recent User Goals ...` in L1

Once written, that malformed memory is embedded into future Tower bootstrap prompts, so the system can keep reinforcing its own corrupted state.

## Impact

This is a memory self-contamination bug.

A fragment of Tower's own startup or bootstrap payload can be misclassified as user intent, written into `L0` and `L1`, and then re-injected into future Tower starts. Even if the exact initial contamination came from older behavior, current `HEAD` still accepts the key malformed shape and can preserve or reintroduce the corruption.

## Affected Code

### Raw session import copies user messages verbatim into L2 transcripts

[`src/control_tower/memory.py`](src/control_tower/memory.py)

- `_collect_transcript()` copies every `user_message` directly into transcript markdown.
- Relevant lines: `68-87`

### Recent goals are rebuilt by scanning transcript `## User` sections

[`src/control_tower/memory.py`](src/control_tower/memory.py)

- `_collect_recent_user_goals()` splits transcript content on `## User\n\n`.
- Relevant lines: `190-210`

### Goal extraction is too naive

[`src/control_tower/memory.py`](src/control_tower/memory.py)

- `_extract_user_goal_snippet()` only truncates at the next `\n## `.
- Relevant lines: `213-215`

If the block itself starts with `## Recent User Goals`, that heading is preserved as part of the snippet.

### Meta filtering is incomplete

[`src/control_tower/memory.py`](src/control_tower/memory.py)

- `_is_bootstrap_or_meta_goal()` filters role text like `You are Tower` and agent-role phrases.
- Relevant lines: `218-228`

It does not filter memory or bootstrap headings such as:

- `## Recent User Goals`
- `## Memory Policy`
- `### L0`
- `### L1`
- `## Bootstrap Files`
- `## Configured Agents`
- `## Operating Rules`
- `## Current Request`

### Tower bootstrap prompts embed L0 and L1 directly

[`src/control_tower/prompts.py`](src/control_tower/prompts.py)

- `build_tower_prompt()` includes both L0 and L1 in the startup prompt.
- Relevant lines: `63-69`

Since L1 contains a `## Recent User Goals` section by design, any quoted, truncated, or bootstrap-derived payload that starts at that heading can survive the current filters.

## Reproduction

### Confirmed on current `HEAD`

I reproduced the issue on current `HEAD` by importing a single interactive session whose `user_message` contained a bootstrap-derived fragment beginning with:

```md
## Recent User Goals

- Start with AGENTS.md, implement the plan at ~/.claude/plans/wondrous-rolling-crane.md and commit to a new branch, then create a relative PR to https://github.com/yashturkar/flight-deck/pull/6
```

After `import_project_sessions(...)`, current `HEAD` produced:

### L0

```md
Project is on branch `unknown` with s1 as the latest imported session. Last tracked Tower session: `s1`. Most recent user goal: ## Recent User Goals  - Start with AGENTS.md, implement the plan at ~/.claude/plans/wondrous-rolling-crane.md and commit to a new branch, then create a relative PR to https://github.com/yashturkar/flight-deck/pull/6
```

### L1

```md
# L1 Working Memory

## Recent User Goals

- ## Recent User Goals  - Start with AGENTS.md, implement the plan at ~/.claude/plans/wondrous-rolling-crane.md and commit to a new branch, then create a relative PR to https://github.com/yashturkar/flight-deck/pull/6
```

## Real-world evidence

I also found a real Codex session log containing the contaminated Tower startup payload, including:

- `Most recent user goal: ## Recent User Goals ...`
- an L1 `## Recent User Goals` section whose first bullet was itself `## Recent User Goals ...`

That confirms this was not just a theoretical edge case.

## Actual behavior

Memory sync can treat bootstrap or memory markup as a real user goal and write it into deterministic memory.

## Expected behavior

Tower bootstrap scaffolding and memory headings should never be accepted as user goals.

In particular, goal extraction should reject snippets that begin with or clearly contain prompt or memory structure such as:

- `## Recent User Goals`
- `## Memory Policy`
- `### L0`
- `### L1`
- `## Bootstrap Files`
- `## Configured Agents`
- `## Operating Rules`
- `## Current Request`

## Why the current filter is not sufficient

The current filter added in `ea79020` catches obvious prompt role text such as:

- `You are Tower`
- `You are Scout`
- role phrases like `the main orchestrator for this repository`

That protects against a plain full bootstrap prompt in many cases.

But it does not protect against:

- truncated bootstrap text
- quoted bootstrap excerpts
- copied L0 or L1 content
- already-contaminated memory reappearing inside later prompts
- any snippet whose first surviving text is a memory heading rather than role text

So the system is still vulnerable to the same class of corruption.

## Root cause

The bug is the combination of:

1. Verbatim import of raw `user_message` text into L2 transcripts.
2. Heuristic extraction of recent goals by string-splitting markdown transcripts.
3. A filter that only recognizes agent-role text, not memory or bootstrap structure.

This makes the pipeline fragile to any prompt-shaped or memory-shaped text that is not caught by the current role-based filter.

## Suggested fix

### Harden extraction

Do not treat heading-based or prompt-shaped markdown as goal candidates.

Examples of safer rules:

- Reject snippets starting with `#`, `##`, or `###`.
- Reject snippets containing known Tower bootstrap section markers.
- Prefer extracting only the first plain-text paragraph or sentence from a user block.
- Consider ignoring very long prompt-like messages entirely for goal extraction.

### Expand filtering

Explicitly filter snippets containing or beginning with:

- `recent user goals`
- `memory policy`
- `bootstrap files`
- `configured agents`
- `operating rules`
- `current request`
- `l0`
- `l1`

### Add regression coverage

Add tests for:

- a full Tower bootstrap prompt
- a quoted Tower bootstrap prompt
- a truncated bootstrap fragment starting at `## Recent User Goals`
- previously contaminated L0 or L1 content being re-imported
- a real user message that mentions Tower or Scout naturally and should still be kept

## Severity

Moderate to high.

This does not usually break execution immediately, but it degrades the correctness of persistent memory and can cause cumulative drift across sessions. Since Tower bootstraps itself from L0 and L1, corrupted memory directly affects future startup behavior.

## Notes

This issue is narrower than "all Tower startup prompts still contaminate memory" on current `HEAD`. The current role-text filter prevents the simplest form of that bug.

However, the underlying self-contamination problem is still real because bootstrap-derived memory fragments beginning at `## Recent User Goals` are still accepted and written back into L0 and L1.
