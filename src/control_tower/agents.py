from __future__ import annotations

from dataclasses import dataclass

from .backends import DEFAULT_BACKEND, VALID_BACKENDS


@dataclass(frozen=True)
class AgentDefinition:
    key: str
    display_name: str
    role: str
    description: str
    default_enabled: bool
    default_search: bool
    default_dangerously_bypass: bool = False
    default_sandbox: str = "workspace-write"
    default_backend: str = DEFAULT_BACKEND
    default_model: str | None = None
    default_model_reasoning_effort: str | None = None


AGENT_DEFINITIONS = [
    AgentDefinition(
        key="builder",
        display_name="Builder",
        role="implementation",
        description="Writes product code, tests, and refactors within scope.",
        default_enabled=True,
        default_search=False,
        default_dangerously_bypass=True,
        default_model="gpt-5.6-sol",
        default_model_reasoning_effort="medium",
    ),
    AgentDefinition(
        key="inspector",
        display_name="Inspector",
        role="review",
        description="Reviews work for correctness, regressions, and quality gaps.",
        default_enabled=True,
        default_search=False,
        default_dangerously_bypass=True,
        default_model="gpt-5.6-sol",
        default_model_reasoning_effort="high",
    ),
    AgentDefinition(
        key="scout",
        display_name="Scout",
        role="research",
        description="Researches options, risks, and technical approaches.",
        default_enabled=True,
        default_search=True,
        default_dangerously_bypass=False,
        default_model="gpt-5.6-terra",
        default_model_reasoning_effort="medium",
    ),
    AgentDefinition(
        key="git-master",
        display_name="Git-master",
        role="git-operations",
        description="Handles branch, commit, diff, and PR-oriented repo operations.",
        default_enabled=True,
        default_search=False,
        default_dangerously_bypass=True,
        default_model="gpt-5.6-luna",
        default_model_reasoning_effort="low",
    ),
    AgentDefinition(
        key="scribe",
        display_name="Scribe",
        role="documentation-memory",
        description="Maintains docs, task state, and durable memory.",
        default_enabled=True,
        default_search=False,
        default_dangerously_bypass=True,
        default_model="gpt-5.6-luna",
        default_model_reasoning_effort="medium",
    ),
]

BUILTIN_AGENT_KEYS = frozenset(d.key for d in AGENT_DEFINITIONS)


def _agent_entry(definition: AgentDefinition) -> dict[str, object]:
    return {
        "name": definition.display_name,
        "role": definition.role,
        "description": definition.description,
        "enabled": definition.default_enabled,
        "model": definition.default_model,
        "model_reasoning_effort": definition.default_model_reasoning_effort,
        "dangerously_bypass": definition.default_dangerously_bypass,
        "sandbox": definition.default_sandbox,
        "search": definition.default_search,
        "backend": definition.default_backend,
    }


def default_agent_registry() -> dict[str, dict[str, object]]:
    return {
        "agents": {
            definition.key: _agent_entry(definition)
            for definition in AGENT_DEFINITIONS
        }
    }


def make_custom_agent_entry(
    name: str,
    role: str,
    description: str,
    *,
    enabled: bool = True,
    model: str | None = None,
    model_reasoning_effort: str | None = None,
    dangerously_bypass: bool = False,
    sandbox: str = "workspace-write",
    search: bool = False,
    backend: str = DEFAULT_BACKEND,
    prompt_file: str | None = None,
) -> dict[str, object]:
    if backend not in VALID_BACKENDS:
        raise ValueError(f"Invalid backend {backend!r}. Valid: {', '.join(VALID_BACKENDS)}")
    entry: dict[str, object] = {
        "name": name,
        "role": role,
        "description": description,
        "enabled": enabled,
        "model": model,
        "dangerously_bypass": dangerously_bypass,
        "sandbox": sandbox,
        "search": search,
        "backend": backend,
        "custom": True,
    }
    if backend == DEFAULT_BACKEND and model_reasoning_effort:
        entry["model_reasoning_effort"] = model_reasoning_effort
    if prompt_file:
        entry["prompt_file"] = prompt_file
    return entry


def list_registered_agents(registry: dict[str, dict[str, object]]) -> list[str]:
    return list(registry.get("agents", {}).keys())


def list_enabled_agents(registry: dict[str, dict[str, object]]) -> list[str]:
    return [
        key for key, config in registry.get("agents", {}).items()
        if config.get("enabled")
    ]
