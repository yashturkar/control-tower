from __future__ import annotations

import sys
from pathlib import Path

from .agents import AGENT_DEFINITIONS, default_agent_registry
from .project import load_agent_registry, load_project_config, save_agent_registry, write_json


SANDBOX_OPTIONS = ["workspace-write", "read-only", "danger-full-access"]


def should_prompt_for_init_ui() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def configure_project_interactively(project_root: Path) -> None:
    project_config = load_project_config(project_root)
    registry = load_agent_registry(project_root)
    if not registry.get("agents"):
        registry = default_agent_registry()

    print("")
    print("Control Tower init")
    print(f"Project: {project_root.name}")
    print("Choose a quick setup or open the detailed per-agent configurator.")
    print("Press Enter to accept the current default shown in brackets.")
    print("")

    setup_mode = _prompt_choice("Setup mode", ["quick", "custom"], "quick")
    print("")

    project_config["project_name"] = project_config.get("project_name", project_root.name) or project_root.name

    if setup_mode == "custom":
        configured_agents = _configure_agents_custom(registry)
    else:
        configured_agents = registry["agents"]

    project_config["enabled_agents"] = [key for key, config in configured_agents.items() if config["enabled"]]
    write_json(project_root / ".control-tower" / "state" / "project.json", project_config)
    save_agent_registry(project_root, {"agents": configured_agents})

    print("Saved agent configuration:")
    for key, config in configured_agents.items():
        status = "enabled" if config["enabled"] else "disabled"
        line = f"- {config['name']} [{status}]"
        if config["enabled"]:
            line += f" sandbox={config['sandbox']}"
            if config["model"]:
                line += f" model={config['model']}"
        print(line)
    print("")
    print("To adjust this later, edit:")
    print(f"- {project_root / '.control-tower' / 'state' / 'agent-registry.json'}")
    print(f"- {project_root / '.control-tower' / 'state' / 'project.json'}")
    print("")


def _configure_agents_custom(registry: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    configured_agents: dict[str, dict[str, object]] = {}
    for definition in AGENT_DEFINITIONS:
        current = registry["agents"].get(definition.key, {})
        print(f"{definition.display_name}: {definition.description}")
        enabled = _prompt_yes_no("Enable this agent", bool(current.get("enabled", definition.default_enabled)))
        model = current.get("model") or ""
        sandbox = str(current.get("sandbox", definition.default_sandbox))
        search = bool(current.get("search", definition.default_search))

        if enabled:
            model = _prompt_text("Model override", model, allow_blank=True)
            sandbox = _prompt_choice("Sandbox", SANDBOX_OPTIONS, sandbox)

        configured_agents[definition.key] = {
            "name": definition.display_name,
            "role": definition.role,
            "description": definition.description,
            "enabled": enabled,
            "model": model or None,
            "sandbox": sandbox,
            "search": search,
        }
        print("")
    return configured_agents


def _prompt_text(label: str, default: str, allow_blank: bool = False) -> str:
    while True:
        raw = input(f"{label} [{default}]: ").strip()
        if raw:
            return raw
        if allow_blank:
            return ""
        if default:
            return default


def _prompt_yes_no(label: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{label} [{suffix}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Enter y or n.")


def _prompt_choice(label: str, options: list[str], default: str) -> str:
    joined = "/".join(options)
    while True:
        raw = input(f"{label} [{default}] ({joined}): ").strip()
        if not raw:
            return default
        if raw in options:
            return raw
        print(f"Choose one of: {joined}")
