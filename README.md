# <img src="assets/tower.png" alt="Control Tower icon" width="44" valign="middle" /> Control Tower

Control Tower is a bootstrap for a Codex-driven multi-agent orchestration workflow.

It installs a `tower` command for humans and a `tower-run` command for Tower’s internal runtime operations. Together they wrap OpenAI Codex CLI, initialize a project-local `.control-tower/` runtime, load Tower with persistent project memory, and provide delegated subagent entrypoints for:

- `Builder`
  Implementation specialist for product code, tests, and refactors.
- `Inspector`
  Review specialist for correctness, regressions, and quality checks.
- `Scout`
  Research specialist for discovery, options, and technical tradeoffs.
- `Git-master`
  Repository operations specialist for branch, commit, and PR workflows.
- `Scribe`
  Documentation and memory specialist for summaries, docs, and durable project state.

## What this bootstrap does

- Creates a portable `.control-tower/` directory inside any repo you run `tower` in.
- Opens an init-time CLI setup flow with a fast default path and an optional detailed per-agent configurator.
- Starts Codex with a Tower-specific bootstrap prompt that includes project memory and agent contracts.
- Persists project memory in three tiers:
  - `L0`: fast snapshot
  - `L1`: working summary
  - `L2`: imported Codex session logs
- Adds a decision graph under `.control-tower/state/decision-graph/` so memory summaries stay linked to decisions, tasks, sessions, packets, and commits.
- Imports Codex session JSONL files from `~/.codex/sessions` into project memory.
- Gives Tower a concrete delegation path via `tower-run delegate <agent> --packet <file>`.

## Quickstart

Clone this repo, then run:

```bash
./setup.sh
```

That installs `tower` and `tower-run` into `~/.local/bin/`.

If you want a one-line remote install instead of cloning first:

```bash
curl -fsSL https://raw.githubusercontent.com/yashturkar/control-tower/main/scripts/bootstrap_remote_install.sh | bash
```

That command:

- clones or updates Control Tower under `~/.local/share/control-tower/repo`
- installs `tower` and `tower-run`
- leaves the local clone available for future updates

Inside any Git repo:

```bash
tower init
tower start
```

`tower init` defaults to a quick setup that keeps the standard agent lineup and enables dangerous bypass for every subagent except `Scout`, which stays sandboxed. If you choose `custom`, it opens the detailed per-agent configurator for enablement, bypass/sandbox, and model overrides. You can always edit `.control-tower/state/agent-registry.json` and `.control-tower/state/project.json` later.

Tower now runs without sandboxing or approval gates by default:

```bash
tower start
```

If you want to disable that for a specific session:

```bash
tower start --no-dangerous
```

The repo default lives in `.control-tower/state/project.json`:

```json
{
  "codex_defaults": {
    "dangerously_bypass": true
  }
}
```

Resume the last Tower session for the current repo:

```bash
tower resume
```

Update the installed Tower CLI and refresh the current repo's `.control-tower/` runtime:

```bash
tower update
```

Inspect project state:

```bash
tower status
```

Low-level runtime example:

```bash
tower-run create-packet builder \
  --title "Implement feature X" \
  --objective "Add feature X and tests" \
  --instruction "Modify the relevant source and tests" \
  --expected-output "Updated source and tests" \
  --definition-of-done "Feature X works and tests pass"

tower-run sync-memory --emit-scribe-packet
```

## Expected project layout

After `tower init`, the target repo gets:

```text
.control-tower/
  agents/
  docs/
  logs/
  memory/
  packets/
  schemas/
  state/
```

The files are intended to be committed with the target repo so Tower can carry context across machines and collaborators.

## Delegation model

```mermaid
flowchart TD
    U["User"] --> TS["tower start"]
    TS --> TB["Tower bootstrap prompt<br/>L0 + L1 + configured agents"]
    TB --> D{"Tower needs specialist work?"}
    D -- "No" --> TU["Tower replies to user"]
    D -- "Implementation" --> B["tower-run delegate builder"]
    D -- "Review" --> I["tower-run delegate inspector"]
    D -- "Research" --> SC["tower-run delegate scout"]
    D -- "Git / PR" --> G["tower-run delegate git-master"]
    D -- "Docs / memory" --> S["tower-run delegate scribe"]
    B --> RP["ResultPacket"]
    I --> RP
    SC --> RP
    G --> RP
    S --> RP
    RP --> TR["Tower reads ResultPacket"]
    TR --> TU
    TR --> NH{"Need another handoff?"}
    NH -- "Yes" --> D
    NH -- "No" --> SM["tower-run sync-memory"]
    SM --> L2["Beacon L2<br/>Imported Codex sessions"]
    SM --> L1["Beacon L1<br/>Working memory"]
    SM --> L0["Beacon L0<br/>Snapshot memory"]
    SM --> BB["Black Box log"]
    SM --> SP["Optional Scribe packet"]
    SP --> S
    L0 --> TB
    L1 --> TB
    TU --> U
```

Tower is intentionally non-coding. It delegates by creating a task packet and running:

```bash
tower-run create-packet builder \
  --title "Implement feature X" \
  --objective "Add feature X and tests" \
  --instruction "Modify the relevant source and tests" \
  --expected-output "Updated source and tests" \
  --definition-of-done "Feature X works and tests pass"

tower-run delegate builder --packet .control-tower/packets/outbox/task.json
```

Subagents run through `codex exec` with their own prompt, policy, and packet context. Their output is constrained to the ResultPacket schema.

The intended loop is:

1. Tower creates a TaskPacket.
2. Tower delegates to a subagent.
3. The subagent returns a ResultPacket.
4. Tower reads that ResultPacket, reports progress or success to the user, and decides whether to hand off to another subagent.
5. After the chain is complete, Tower syncs memory and optionally routes durable curation to Scribe.

For chained work, Tower can seed the next packet from the previous ResultPacket. Example: Builder finishes implementation, then Tower creates a Git-master packet from that Builder result, delegates Git-master, then creates a Scribe packet from the Git-master result.

```bash
tower-run create-packet git-master \
  --from-result .control-tower/packets/inbox/builder-result.json \
  --title "Commit Builder changes" \
  --task-type "git-operations" \
  --objective "Review the Builder output, stage the intended files, and create a commit" \
  --instruction "Use the Builder result packet as the source of truth for changed files" \
  --expected-output "Commit hash and commit summary" \
  --definition-of-done "Relevant changes are committed cleanly"
```

## Memory sync model

`tower-run sync-memory` scans the local Codex session store and imports sessions whose `cwd` matches the current project root. Imported sessions are copied into `.control-tower/memory/l2/sessions/`, a transcript index is maintained in `.control-tower/state/session-index.json`, a decision graph is refreshed under `.control-tower/state/decision-graph/`, and graph-backed `L0` / `L1` summaries are regenerated.

For higher-quality persistent memory, use `tower-run sync-memory --emit-scribe-packet`. That creates a Scribe task packet so Tower can delegate long-form curation of:

- session summaries
- open questions
- task ledgers
- decision registers
- architecture notes
- ADR/doc drift

Additional graph-oriented commands:

- `tower-run log-decision --title ... --topic ... --summary ...`
- `tower-run graph-status`
- `tower-run graph-view --web`
- `tower-run graph-view --tui --focus <node-id> --radius 2`
- `tower-run graph-export --format json --output graph.json`
- `tower-run graph-export --format dot --output graph.dot`
- `tower-run graph-export --format svg --output graph.svg`
- `tower-run explain --commit <sha>`
- `tower-run explain --decision <decision-id>`

## Requirements

- `python3` 3.9+
- `codex` installed and authenticated
- a writable `~/.local/bin` on your `PATH`

## Notes

- `tower` is the intended user interface.
- `tower-run` is the intended internal interface for Tower’s own orchestration primitives.
- `tower resume` prefers the last tracked Tower session for the current repo. If none is recorded, it falls back to `codex resume --last`.
- The bootstrap uses only the Python standard library.
- The repo includes JSON schemas and prompt/policy templates, but the runtime is intentionally lightweight so it can be used as a starting point and extended.
