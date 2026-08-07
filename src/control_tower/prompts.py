from __future__ import annotations

from pathlib import Path

from .docs_harness import docs_harness_context_refs
from .layout import tower_dir
from .project import load_agent_registry, load_graph_indexes, load_graph_nodes, load_project_config, read_text

MAX_GRAPH_CONTEXT_ITEMS = 3


def build_tower_prompt(project_root: Path, user_prompt: str | None = None) -> str:
    base = tower_dir(project_root)
    config = load_project_config(project_root)
    registry = load_agent_registry(project_root)
    l0 = read_text(base / "memory" / "l0.md").strip()
    l1 = read_text(base / "memory" / "l1.md").strip()
    tower_prompt = read_text(base / "agents" / "tower" / "prompt.md").strip()

    enabled_agents = [
        agent_key
        for agent_key, agent_config in registry.get("agents", {}).items()
        if agent_config.get("enabled")
    ]
    agent_files = [".control-tower/agents/tower/prompt.md"] + [
        path
        for agent_key in enabled_agents
        if (path := _agent_prompt_path(project_root, agent_key, registry["agents"][agent_key])) is not None
    ]
    configured_agents = []
    for agent_key in enabled_agents:
        agent_config = registry["agents"][agent_key]
        label = f"- {agent_config['name']} ({agent_key})"
        backend = agent_config.get("backend", "codex")
        if backend != "codex":
            label += f" [backend: {backend}]"
        if agent_config.get("custom"):
            label += " [custom]"
        configured_agents.append(label)
    if not configured_agents:
        configured_agents = ["- No subagents enabled"]

    docs_harness = config.get("docs_harness", {}) if isinstance(config, dict) else {}
    docs_section: list[str] = []
    if docs_harness.get("enabled"):
        docs_section = [
            "## Repo Docs Harness",
            "",
            f"- Enabled: {docs_harness.get('enabled')}",
            f"- Mode: {docs_harness.get('mode', 'unknown')}",
            f"- Doc roots: {', '.join(docs_harness.get('doc_roots', [])) or 'none'}",
            f"- Root map files: {', '.join(docs_harness.get('root_map_files', [])) or 'none'}",
            f"- Index files: {', '.join(docs_harness.get('index_files', [])) or 'none'}",
            f"- Context refs: {', '.join(docs_harness_context_refs(project_root, docs_harness))}",
            "",
            "Repo `docs/` is the durable knowledge store when this harness is enabled.",
            "`.control-tower/docs/state` and `.control-tower/memory` are operational project-state memory.",
            "After most successful Builder, Inspector, and Git-master steps, create and usually delegate a Scribe follow-up packet for repo docs unless the prior result makes that clearly unnecessary.",
            "",
        ]

    graph_section = _build_graph_section(project_root)

    sections = [
        f"You are {config.get('primary_agent', 'Tower')} for the project `{config.get('project_name', project_root.name)}`.",
        "",
        tower_prompt,
        "",
        "## Bootstrap Files",
        "",
        "Read and respect these project-local agent contracts as needed:",
        *[f"- {path}" for path in agent_files],
        "",
        "## Configured Agents",
        "",
        *configured_agents,
        "",
        "## Memory",
        "",
        "### L0",
        l0 or "No L0 snapshot yet.",
        "",
        "### L1",
        l1 or "No L1 working memory yet.",
        "",
        *graph_section,
        *docs_section,
        "## Operating Rules",
        "",
        "- Tower does not directly implement product code.",
        "- Tower delegates specialist work through typed packets.",
        "- Use `tower-run create-packet <agent> ...` to generate TaskPackets instead of writing JSON manually.",
        "- For implementation, review, research, Git, or docs work, create a packet in `.control-tower/packets/outbox/` and run `tower-run delegate <agent> --packet <path>`.",
        "- After each delegated step, read the ResultPacket, report status to the user, and seed the next handoff if needed.",
        "- After meaningful work, run `tower-run sync-memory`; use `tower-run sync-memory --emit-scribe-packet` when durable curation by Scribe is warranted.",
        "- Keep user communication concise, accurate, and traceable to repo state.",
        "- Custom agents can be delegated to exactly like built-in agents using the same packet workflow.",
        "- Agent backends (codex, gemini, cursor) are configured per-agent in the registry. The backend is selected automatically during delegation.",
        "",
        "## Current Request",
        "",
        user_prompt.strip() if user_prompt else "Resume control of the project and report the next best action.",
    ]
    return "\n".join(sections).strip() + "\n"


def _build_graph_section(project_root: Path) -> list[str]:
    try:
        graph_indexes = load_graph_indexes(project_root)
        graph_nodes = load_graph_nodes(project_root).get("nodes", {})
    except Exception:
        return [
            "## Decision Graph Operational Snapshot",
            "",
            "Graph context unavailable due to malformed graph state files.",
            "",
        ]
    if not isinstance(graph_nodes, dict):
        graph_nodes = {}

    active_decisions = list(graph_indexes.get("active_decisions", []))[:MAX_GRAPH_CONTEXT_ITEMS]
    open_questions = list(graph_indexes.get("open_questions", []))[:MAX_GRAPH_CONTEXT_ITEMS]
    current_tasks = list(graph_indexes.get("current_tasks", []))[:MAX_GRAPH_CONTEXT_ITEMS]
    indexed_blockers = graph_indexes.get("unresolved_blockers", [])
    if isinstance(indexed_blockers, list) and indexed_blockers:
        unresolved_blockers = indexed_blockers[:MAX_GRAPH_CONTEXT_ITEMS]
    else:
        # Prefer unresolved blockers from indexes when available; otherwise derive from blocked result packets.
        unresolved_blockers = _extract_blocked_packet_ids(graph_nodes)[:MAX_GRAPH_CONTEXT_ITEMS]

    # created_at values are expected to be ISO 8601 timestamps when present.
    recent_outcomes = [
        node
        for node in sorted(
            (
                candidate
                for candidate in graph_nodes.values()
                if isinstance(candidate, dict) and candidate.get("type") == "packet" and candidate.get("packet_type") == "result"
            ),
            key=lambda candidate: str(candidate.get("created_at", "")),
            reverse=True,
        )[:MAX_GRAPH_CONTEXT_ITEMS]
    ]
    recent_commits = list(graph_indexes.get("recent_commits", []))[:MAX_GRAPH_CONTEXT_ITEMS]

    return [
        "## Decision Graph Operational Snapshot",
        "",
        f"- Active decisions: {', '.join(active_decisions) if active_decisions else 'none'}",
        f"- Open questions: {', '.join(open_questions) if open_questions else 'none'}",
        f"- Current tasks: {', '.join(current_tasks) if current_tasks else 'none'}",
        f"- Unresolved blockers: {', '.join(unresolved_blockers) if unresolved_blockers else 'none'}",
        f"- Recent commits: {', '.join(recent_commits) if recent_commits else 'none'}",
        f"- Current branch: {graph_indexes.get('current_branch', 'unknown')}",
        "",
        "Recent agent outcomes from graph packet nodes:",
        *(
            [
                f"- {node.get('id')}: {node.get('from_agent', 'unknown')} [{node.get('status', 'unknown')}] "
                f"{node.get('summary') or node.get('title') or ''}".rstrip()
                for node in recent_outcomes
            ]
            or ["- none"]
        ),
        "",
        "Graph context consulted from `.control-tower/state/decision-graph/indexes.json` and `nodes.json`.",
        "",
    ]


def _extract_blocked_packet_ids(graph_nodes: dict[str, object]) -> list[str]:
    return [
        node_id
        for node_id, node in graph_nodes.items()
        if isinstance(node, dict)
        and node.get("type") == "packet"
        and node.get("packet_type") == "result"
        and node.get("status") == "blocked"
    ]


def build_subagent_prompt(project_root: Path, agent: str, packet_text: str) -> str:
    base = tower_dir(project_root)
    registry = load_agent_registry(project_root)
    agent_config = registry.get("agents", {}).get(agent, {})

    prompt = _load_agent_prompt(project_root, agent, agent_config)
    policy = _load_agent_policy(project_root, agent, agent_config)
    result_schema = ".control-tower/schemas/packets/result.schema.json"

    sections = [
        prompt,
        "",
        "## Policy",
        "",
        "```yaml",
        policy,
        "```",
        "",
        "## Task Packet",
        "",
        "```json",
        packet_text.strip(),
        "```",
        "",
        "## Output Contract",
        "",
        f"Return only a JSON object that conforms to `{result_schema}`.",
        "Do not wrap the JSON in markdown.",
        "If blocked, return a valid ResultPacket with `status` set to `blocked` and explain why in `summary` and `findings`.",
    ]
    return "\n".join(sections).strip() + "\n"


def _agent_prompt_path(project_root: Path, agent_key: str, agent_config: dict[str, object]) -> str | None:
    """Return the prompt file path for an agent, or None if no file exists."""
    if agent_config.get("prompt_file"):
        raw = str(agent_config["prompt_file"])
        resolved = (project_root / raw).resolve()
        if not _is_within(resolved, project_root.resolve()):
            return None
        if resolved.exists():
            return raw
        return None
    default = f".control-tower/agents/{agent_key}/prompt.md"
    if (project_root / default).exists():
        return default
    return None


def _is_within(path: Path, root: Path) -> bool:
    """Return True if *path* is the same as or contained within *root*."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _load_agent_prompt(project_root: Path, agent: str, agent_config: dict[str, object]) -> str:
    if agent_config.get("prompt_file"):
        raw = str(agent_config["prompt_file"])
        prompt_path = (project_root / raw).resolve()
        if not _is_within(prompt_path, project_root.resolve()):
            raise ValueError(
                f"Invalid prompt_file path for agent '{agent}': {raw!r}. "
                "The prompt_file must be located within the project root."
            )
        content = read_text(prompt_path).strip()
        if content:
            return content

    base = tower_dir(project_root)
    content = read_text(base / "agents" / agent / "prompt.md").strip()
    if content:
        return content

    # Fallback for custom agents with no prompt file
    name = agent_config.get("name", agent)
    role = agent_config.get("role", "custom")
    description = agent_config.get("description", "")
    return (
        f"# {name}\n\n"
        f"Role: {role}\n\n"
        f"## Responsibilities\n\n"
        f"{description}\n\n"
        f"## Constraints\n\n"
        f"- Return only a JSON ResultPacket.\n"
        f"- Do not wrap JSON in markdown.\n"
    )


def _load_agent_policy(project_root: Path, agent: str, agent_config: dict[str, object]) -> str:
    base = tower_dir(project_root)
    content = read_text(base / "agents" / agent / "policy.yaml").strip()
    if content:
        return content

    # Fallback for custom agents
    role = agent_config.get("role", "custom")
    return (
        f"agent: {agent}\n"
        f"role: {role}\n"
        f"allowed_actions:\n"
        f"  - read_files\n"
        f"  - write_files\n"
        f"  - run_commands\n"
        f"constraints:\n"
        f"  - Return results as a valid ResultPacket JSON\n"
    )
