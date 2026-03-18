from __future__ import annotations

import json
import shutil
from importlib import resources
from pathlib import Path

from .agents import default_agent_registry
from .layout import tower_dir


def _template_root() -> Path:
    return Path(str(resources.files("control_tower"))) / "templates" / "project"


def init_project(project_root: Path, force: bool = False) -> Path:
    destination = tower_dir(project_root)
    source_root = _template_root()

    for source in source_root.rglob("*"):
        relative = source.relative_to(source_root)
        target = destination / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if target.exists() and not force:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    project_state = destination / "state" / "project.json"
    config = json.loads(project_state.read_text())
    config["project_name"] = project_root.name
    config["project_root"] = str(project_root)
    project_state.write_text(json.dumps(config, indent=2) + "\n")

    agent_registry = destination / "state" / "agent-registry.json"
    if not agent_registry.exists():
        agent_registry.write_text(json.dumps(default_agent_registry(), indent=2) + "\n")
    return destination
