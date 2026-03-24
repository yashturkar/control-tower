from __future__ import annotations

from pathlib import Path

from .docs_harness import docs_harness_context_refs
from .layout import tower_dir
from .project import load_agent_registry, load_graph_indexes, load_graph_nodes, load_project_config, read_text


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
        f".control-tower/agents/{agent_key}/prompt.md" for agent_key in enabled_agents
    ]
    configured_agents = [
        f"- {registry['agents'][agent_key]['name']} ({agent_key})"
        for agent_key in enabled_agents
    ] or ["- No subagents enabled"]
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

    graph_indexes = load_graph_indexes(project_root)
    graph_nodes = load_graph_nodes(project_root).get("nodes", {})
    active_decisions = list(graph_indexes.get("active_decisions", []))[:3]
    open_questions = list(graph_indexes.get("open_questions", []))[:3]
    current_tasks = list(graph_indexes.get("current_tasks", []))[:3]
    unresolved_blockers = [
        node_id
        for node_id, node in graph_nodes.items()
        if node.get("type") == "packet" and node.get("packet_type") == "result" and node.get("status") == "blocked"
    ][:3]
    recent_outcomes = [
        node
        for node in sorted(
            (
                candidate
                for candidate in graph_nodes.values()
                if candidate.get("type") == "packet" and candidate.get("packet_type") == "result"
            ),
            key=lambda candidate: str(candidate.get("created_at", "")),
            reverse=True,
        )[:3]
    ]
    graph_section = [
        "## Decision Graph Operational Snapshot",
        "",
        f"- Active decisions: {', '.join(active_decisions) if active_decisions else 'none'}",
        f"- Open questions: {', '.join(open_questions) if open_questions else 'none'}",
        f"- Current tasks: {', '.join(current_tasks) if current_tasks else 'none'}",
        f"- Unresolved blockers: {', '.join(unresolved_blockers) if unresolved_blockers else 'none'}",
        f"- Recent commits: {', '.join(graph_indexes.get('recent_commits', [])[:3]) or 'none'}",
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
        "",
        "## Current Request",
        "",
        user_prompt.strip() if user_prompt else "Resume control of the project and report the next best action.",
    ]
    return "\n".join(sections).strip() + "\n"


def build_subagent_prompt(project_root: Path, agent: str, packet_text: str) -> str:
    base = tower_dir(project_root)
    prompt = read_text(base / "agents" / agent / "prompt.md").strip()
    policy = read_text(base / "agents" / agent / "policy.yaml").strip()
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
