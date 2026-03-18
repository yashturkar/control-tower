from __future__ import annotations

from pathlib import Path

from .layout import tower_dir
from .project import load_agent_registry, load_project_config, read_text


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
