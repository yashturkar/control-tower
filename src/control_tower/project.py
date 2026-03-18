from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agents import default_agent_registry
from .layout import tower_dir


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def read_text(path: Path, default: str = "") -> str:
    if not path.exists():
        return default
    return path.read_text()


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def load_project_config(project_root: Path) -> dict[str, Any]:
    base = tower_dir(project_root)
    return read_json(base / "state" / "project.json", {})


def load_runtime_state(project_root: Path) -> dict[str, Any]:
    base = tower_dir(project_root)
    return read_json(base / "state" / "runtime.json", {})


def save_runtime_state(project_root: Path, state: dict[str, Any]) -> None:
    base = tower_dir(project_root)
    write_json(base / "state" / "runtime.json", state)


def load_session_index(project_root: Path) -> dict[str, Any]:
    base = tower_dir(project_root)
    return read_json(base / "state" / "session-index.json", {"sessions": {}})


def save_session_index(project_root: Path, index: dict[str, Any]) -> None:
    base = tower_dir(project_root)
    write_json(base / "state" / "session-index.json", index)


def load_agent_registry(project_root: Path) -> dict[str, Any]:
    base = tower_dir(project_root)
    registry = read_json(base / "state" / "agent-registry.json", {})
    if registry.get("agents"):
        return registry
    return default_agent_registry()


def save_agent_registry(project_root: Path, registry: dict[str, Any]) -> None:
    base = tower_dir(project_root)
    write_json(base / "state" / "agent-registry.json", registry)
