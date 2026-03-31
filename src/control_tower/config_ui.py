from __future__ import annotations

import re
import sys
from pathlib import Path

from .agents import AGENT_DEFINITIONS, BUILTIN_AGENT_KEYS, default_agent_registry, make_custom_agent_entry
from .backends import VALID_BACKENDS
from .docs_harness import detect_docs_harness, ensure_docs_harness
from .project import load_agent_registry, load_project_config, save_agent_registry, write_json


SANDBOX_OPTIONS = ["workspace-write", "read-only", "danger-full-access"]

BACKEND_MODELS: dict[str, list[str]] = {
    "codex": [
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.3-codex",
        "gpt-5.2-codex",
        "gpt-5.2",
    ],
    "gemini": [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
    ],
    "cursor": [
        "composer-2",
        "opus-4.6-thinking",
        "sonnet-4.6-thinking",
        "gpt-5.4-high",
        "auto",
    ],
}
INIT_BANNER = [
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                       @@@                                          ",
    "                                                      @--->                                         ",
    "                                                        @                                           ",
    "                                            +@@         %                                           ",
    "                                       @@@----@         %                                           ",
    "                                      {@---@@@          @                                           ",
    "                                          @@            @                                           ",
    "                                    @@@@-@----------------@-@@@@                                    ",
    "                                   @@-@@@@@@@@@@@@@@@@@@@@@@@@-@@                                   ",
    "                               @@@@@----------------------------@@@@@                               ",
    "                            @@------@@@@@@@@@@@@@@@@@@@@@@@@@@@@------@{                            ",
    "                             @@@@@-@----@@-------@@-------@@----@-@@@@@                             ",
    "                              %@----@-==-@-=><><-@@->><>~-@-=>-@----@@                              ",
    "                               @@-+-@@->-@@*[[[[-@@-[[[[*@@-<~-@-+-@@                               ",
    "                                @@---@-+~^@------@@------@)==-@---@@                                ",
    "                                @@@@@@@-----====----===+-----@@@@@@@                                ",
    "                                ^@%@@@@@@@@@@@@@@@@@@@@@@@@@@@@@%@@+                                ",
    "                              %   @@@----@@@@@@@@@@@@@@@@@@-*--@@%   @                              ",
    "                              %@@@@@@@-<~--~~~~=~~~~~~~~--=+[-@@@@@@@@.                             ",
    "                              %@------------------------------------@@                              ",
    "                               @@@@@@@@@@@@~<[[[[[[[[[[<-@@@@@@@@@@@@:                              ",
    "                                    @@@---@@-<<<<<)))<)-@@---@@%                                    ",
    "                                      @@---@------------@---@@                                      ",
    "                                       @@@:@@@@@@@@@@@@@@-@@@                                       ",
    "                                        @@----------------@@                                        ",
    "                                         @@@~<<>><<<<>>~@@@                                         ",
    "                                          %@-><)>><<>>)-@@                                          ",
    "                                          @@-<<<<><><><-@%                                          ",
    "                                          %@->>><>)<<><-@%                                          ",
    "                                          @@-<>>>><>><>-@%                                          ",
    "                                          @@------------@@                                          ",
    "                                         :@@@@@@@@@@@@@@@@:                                         ",
    "                                         @@--------------@@                                         ",
    "                                         %@-}]}[[[[]][[[-@%                                         ",
    "                                         @@->^>^>^^>^^>^-@@                                         ",
    "                                         %@-<>>><<>>>>><-@#                                         ",
    "                                         %@->><>)>><<<><-@@                                         ",
    "                                         @@-<><<><><>><<-@%                                         ",
    "                                         %@->><<><<<<<<<-@@                                         ",
    "                                         @@-><>>>>>><<>>*-@@                                        ",
    "                                        @@-+<<<<<<>><>><(-@#                                        ",
    "                                        #@-<<<<>>>><>><>>-@@                                        ",
    "                                        @@-><<<<<>><<>><<-@@                                        ",
    "                                        %@-<>)>>><)>)<><<-@@                                        ",
    "                                        %@-<>><<>>>>><<>>-@%                                        ",
    "                                        %@----------------@@                                        ",
    "                                        @@@@@@@@@@@@@@@@@@@%@                                        ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
    "                                                                                                    ",
]


def should_prompt_for_init_ui() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def configure_project_interactively(project_root: Path) -> None:
    project_config = load_project_config(project_root)
    registry = load_agent_registry(project_root)
    if not registry.get("agents"):
        registry = default_agent_registry()

    print("")
    _print_banner()
    print("Control Tower init")
    print(f"Project: {project_root.name}")
    print("Choose a quick setup or open the detailed per-agent configurator.")
    print("Press Enter to accept the current default shown in brackets.")
    print("")

    setup_mode = _prompt_choice("Setup mode", ["quick", "custom"], "quick")
    print("")

    project_config["project_name"] = project_config.get("project_name", project_root.name) or project_root.name

    if setup_mode == "custom":
        configured_agents = _configure_agents_custom(registry, project_root)
    else:
        configured_agents = default_agent_registry()["agents"]
        _print_quick_setup_notice()

    project_config["enabled_agents"] = [key for key, config in configured_agents.items() if config["enabled"]]
    project_config["docs_harness"] = _configure_docs_harness(project_root, project_config.get("docs_harness", {}))
    write_json(project_root / ".control-tower" / "state" / "project.json", project_config)
    save_agent_registry(project_root, {"agents": configured_agents})

    print("Saved agent configuration:")
    for key, config in configured_agents.items():
        status = "enabled" if config["enabled"] else "disabled"
        custom_tag = " (custom)" if config.get("custom") else ""
        line = f"- {config['name']} [{status}]{custom_tag}"
        if config["enabled"]:
            backend = config.get("backend", "codex")
            if backend != "codex":
                line += f" backend={backend}"
            if config.get("dangerously_bypass"):
                line += " mode=bypass"
            else:
                line += f" sandbox={config['sandbox']}"
            if config["model"]:
                line += f" model={config['model']}"
        print(line)
    print("")
    print("To adjust this later, edit:")
    print(f"- {project_root / '.control-tower' / 'state' / 'agent-registry.json'}")
    print(f"- {project_root / '.control-tower' / 'state' / 'project.json'}")
    print("")


def _configure_docs_harness(project_root: Path, existing: dict[str, object]) -> dict[str, object]:
    detected = detect_docs_harness(project_root, existing)
    if detected.get("enabled"):
        print("Detected repo docs harness:")
        print(f"- Roots: {', '.join(detected.get('doc_roots', [])) or 'none'}")
        print(f"- Index files: {', '.join(detected.get('index_files', [])) or 'none'}")
        print("")
        return detected

    if _prompt_yes_no("No repo docs harness detected. Scaffold minimal docs harness", True):
        configured = ensure_docs_harness(project_root, existing, scaffold_missing=True)
        print("Scaffolded minimal repo docs harness.")
        print("")
        return configured

    print("Leaving repo docs harness disabled for now.")
    print("")
    return detect_docs_harness(project_root, existing)


def _configure_agents_custom(registry: dict[str, dict[str, object]], project_root: Path) -> dict[str, dict[str, object]]:
    configured_agents: dict[str, dict[str, object]] = {}

    # Configure built-in agents
    for definition in AGENT_DEFINITIONS:
        current = registry["agents"].get(definition.key, {})
        print(f"{definition.display_name}: {definition.description}")
        enabled = _prompt_yes_no("Enable this agent", bool(current.get("enabled", definition.default_enabled)))
        model = current.get("model") or ""
        sandbox = str(current.get("sandbox", definition.default_sandbox))
        search = bool(current.get("search", definition.default_search))
        dangerously_bypass = bool(current.get("dangerously_bypass", definition.default_dangerously_bypass))
        backend_raw = current.get("backend", definition.default_backend)
        backend = str(backend_raw) if backend_raw and str(backend_raw) in VALID_BACKENDS else definition.default_backend

        if enabled:
            backend, model = _prompt_backend_and_model(backend, str(model))
            dangerously_bypass = _prompt_yes_no("Use dangerous bypass", dangerously_bypass)
            if not dangerously_bypass:
                sandbox = _prompt_choice("Sandbox", SANDBOX_OPTIONS, sandbox)

        configured_agents[definition.key] = {
            "name": definition.display_name,
            "role": definition.role,
            "description": definition.description,
            "enabled": enabled,
            "model": model or None,
            "dangerously_bypass": dangerously_bypass,
            "sandbox": sandbox,
            "search": search,
            "backend": backend,
        }
        print("")

    # Configure existing custom agents
    for key, config in registry["agents"].items():
        if key in BUILTIN_AGENT_KEYS:
            continue
        print(f"Custom agent: {config.get('name', key)}")
        print(f"  {config.get('description', 'No description')}")
        enabled = _prompt_yes_no("Keep this agent enabled", bool(config.get("enabled", True)))
        if enabled:
            backend_raw = config.get("backend")
            backend_default = str(backend_raw) if backend_raw and str(backend_raw) in VALID_BACKENDS else "codex"
            backend, model = _prompt_backend_and_model(backend_default, str(config.get("model") or ""))
            dangerously_bypass = _prompt_yes_no("Use dangerous bypass", bool(config.get("dangerously_bypass", False)))
            sandbox = config.get("sandbox", "workspace-write")
            if not dangerously_bypass:
                sandbox = _prompt_choice("Sandbox", SANDBOX_OPTIONS, str(sandbox))
        else:
            backend = str(config.get("backend") or "codex") if config.get("backend") and str(config["backend"]) in VALID_BACKENDS else "codex"
            model = config.get("model") or ""
            dangerously_bypass = bool(config.get("dangerously_bypass", False))
            sandbox = config.get("sandbox", "workspace-write")

        configured_agents[key] = {
            "name": config.get("name", key),
            "role": config.get("role", "custom"),
            "description": config.get("description", ""),
            "enabled": enabled,
            "model": model or None,
            "dangerously_bypass": dangerously_bypass,
            "sandbox": str(sandbox),
            "search": bool(config.get("search", False)),
            "backend": backend,
            "custom": True,
        }
        if config.get("prompt_file"):
            configured_agents[key]["prompt_file"] = config["prompt_file"]
        print("")

    # Offer to add new custom agents
    while _prompt_yes_no("Add a new custom agent", False):
        agent = _create_custom_agent_interactive(project_root, configured_agents)
        if agent:
            key, entry = agent
            configured_agents[key] = entry
            print(f"Added custom agent: {entry['name']} ({key})")
        print("")

    return configured_agents


def _create_custom_agent_interactive(
    project_root: Path,
    existing: dict[str, dict[str, object]],
) -> tuple[str, dict[str, object]] | None:
    name = _prompt_text("Agent display name (blank to cancel)", "", allow_blank=True)
    if not name:
        return None
    key = _slugify(name)
    if key in existing or key in BUILTIN_AGENT_KEYS:
        print(f"Agent key '{key}' already exists. Choose a different name.")
        return None

    role = _prompt_text("Role (e.g. security-review, migration, infra)", "custom")
    description = _prompt_text("Description (blank to cancel)", "", allow_blank=True)
    if not description:
        return None

    backend, model = _prompt_backend_and_model("codex", "")
    dangerously_bypass = _prompt_yes_no("Use dangerous bypass", False)
    sandbox = "workspace-write"
    if not dangerously_bypass:
        sandbox = _prompt_choice("Sandbox", SANDBOX_OPTIONS, "workspace-write")

    prompt_file = f".control-tower/agents/{key}/prompt.md"
    use_prompt_file = _prompt_yes_no(f"Create prompt file at {prompt_file}", True)

    if use_prompt_file:
        prompt_path = project_root / prompt_file
        if not prompt_path.exists():
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(
                f"# {name}\n\n"
                f"Role: {role}\n\n"
                f"## Responsibilities\n\n"
                f"{description}\n\n"
                f"## Constraints\n\n"
                f"- Return only a JSON ResultPacket.\n"
                f"- Do not wrap JSON in markdown.\n"
            )
            # Also create a default policy.yaml
            policy_path = prompt_path.parent / "policy.yaml"
            if not policy_path.exists():
                policy_path.write_text(
                    f"agent: {key}\n"
                    f"role: {role}\n"
                    f"allowed_actions:\n"
                    f"  - read_files\n"
                    f"  - write_files\n"
                    f"  - run_commands\n"
                    f"constraints:\n"
                    f"  - Return results as a valid ResultPacket JSON\n"
                )
            print(f"Created {prompt_file}")

    entry = make_custom_agent_entry(
        name=name,
        role=role,
        description=description,
        enabled=True,
        model=model or None,
        dangerously_bypass=dangerously_bypass,
        sandbox=sandbox,
        backend=backend,
        prompt_file=prompt_file if use_prompt_file else None,
    )
    return key, entry


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "custom-agent"


def _print_banner() -> None:
    lines = list(INIT_BANNER)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    non_empty = [line for line in lines if line.strip()]
    if non_empty:
        left_margin = min(len(line) - len(line.lstrip(" ")) for line in non_empty)
    else:
        left_margin = 0

    for line in lines:
        print(line[left_margin:].rstrip())
    print("")


def _print_quick_setup_notice() -> None:
    print("+--------------------------------------------------------------+")
    print("|                   !!! QUICK SETUP NOTICE !!!                 |")
    print("+--------------------------------------------------------------+")
    print("| Builder, Inspector, Git-master, and Scribe will run in       |")
    print("| dangerous bypass mode by default. Scout stays sandboxed.     |")
    print("| Use `custom` now or edit `.control-tower/state/agent-        |")
    print("| registry.json` later if you want stricter agent settings.    |")
    print("+--------------------------------------------------------------+")
    print("")


def _prompt_text(label: str, default: str, allow_blank: bool = False) -> str:
    while True:
        raw = input(f"{label} [{default}]: ").strip()
        if raw:
            return raw
        if allow_blank:
            return ""
        if default:
            return default
        print("A value is required. Please try again.")


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


def _prompt_backend_and_model(
    default_backend: str = "codex",
    default_model: str = "",
) -> tuple[str, str]:
    """Prompt for backend, then show curated model choices for that backend."""
    backend = _prompt_choice("Backend", list(VALID_BACKENDS), default_backend)
    models = BACKEND_MODELS.get(backend, [])
    if not models:
        model = _prompt_text("Model", default_model, allow_blank=True)
        return backend, model

    print(f"  Models for {backend}:")
    for i, m in enumerate(models, 1):
        tag = " (default)" if i == 1 else ""
        print(f"    {i}) {m}{tag}")
    print(f"    {len(models) + 1}) custom")

    while True:
        current_display = default_model if default_model else models[0]
        raw = input(f"  Model [{current_display}]: ").strip()
        if not raw:
            return backend, default_model or ""
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(models):
                return backend, models[idx - 1]
            if idx == len(models) + 1:
                custom = _prompt_text("  Custom model name", "", allow_blank=True)
                return backend, custom
            print(f"  Enter 1-{len(models) + 1} or a model name.")
            continue
        # Accept a typed-in model name directly
        return backend, raw
