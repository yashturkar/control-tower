from __future__ import annotations

from dataclasses import dataclass


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


AGENT_DEFINITIONS = [
    AgentDefinition(
        key="builder",
        display_name="Builder",
        role="implementation",
        description="Writes product code, tests, and refactors within scope.",
        default_enabled=True,
        default_search=False,
        default_dangerously_bypass=True,
    ),
    AgentDefinition(
        key="inspector",
        display_name="Inspector",
        role="review",
        description="Reviews work for correctness, regressions, and quality gaps.",
        default_enabled=True,
        default_search=False,
        default_dangerously_bypass=True,
    ),
    AgentDefinition(
        key="scout",
        display_name="Scout",
        role="research",
        description="Researches options, risks, and technical approaches.",
        default_enabled=True,
        default_search=True,
        default_dangerously_bypass=False,
    ),
    AgentDefinition(
        key="git-master",
        display_name="Git-master",
        role="git-operations",
        description="Handles branch, commit, diff, and PR-oriented repo operations.",
        default_enabled=True,
        default_search=False,
        default_dangerously_bypass=True,
    ),
    AgentDefinition(
        key="scribe",
        display_name="Scribe",
        role="documentation-memory",
        description="Maintains docs, task state, and durable memory.",
        default_enabled=True,
        default_search=False,
        default_dangerously_bypass=True,
    ),
]


def default_agent_registry() -> dict[str, dict[str, object]]:
    return {
        "agents": {
            definition.key: {
                "name": definition.display_name,
                "role": definition.role,
                "description": definition.description,
                "enabled": definition.default_enabled,
                "model": None,
                "dangerously_bypass": definition.default_dangerously_bypass,
                "sandbox": definition.default_sandbox,
                "search": definition.default_search,
            }
            for definition in AGENT_DEFINITIONS
        }
    }
