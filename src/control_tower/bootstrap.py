from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from .agents import default_agent_registry
from .docs_harness import detect_docs_harness
from .layout import tower_dir
from .project import load_runtime_state, save_runtime_state


def _template_root() -> Path:
    return Path(str(resources.files("control_tower"))) / "templates" / "project"


MANAGED_TEMPLATE_PREFIXES = (
    Path("schemas/packets"),
    Path("schemas/decision-graph"),
)


def _should_refresh_existing(relative: Path) -> bool:
    return any(relative.parts[: len(prefix.parts)] == prefix.parts for prefix in MANAGED_TEMPLATE_PREFIXES)


def _merge_project_config(template_config: dict[str, object], existing_config: dict[str, object], project_root: Path) -> dict[str, object]:
    merged = dict(template_config)
    merged.update(existing_config)
    merged["project_name"] = project_root.name
    merged["project_root"] = str(project_root)
    merged["docs_harness"] = detect_docs_harness(project_root, existing_config.get("docs_harness", {}))
    return merged


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def init_project(project_root: Path, force: bool = False) -> Path:
    destination = tower_dir(project_root)
    source_root = _template_root()

    for source in source_root.rglob("*"):
        relative = source.relative_to(source_root)
        target = destination / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if target.exists() and not force and not _should_refresh_existing(relative):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    project_state = destination / "state" / "project.json"
    template_project_state = source_root / "state" / "project.json"
    template_config = json.loads(template_project_state.read_text())
    existing_config = json.loads(project_state.read_text()) if project_state.exists() else {}
    config = _merge_project_config(template_config, existing_config, project_root)
    project_state.write_text(json.dumps(config, indent=2) + "\n")

    agent_registry = destination / "state" / "agent-registry.json"
    if not agent_registry.exists():
        agent_registry.write_text(json.dumps(default_agent_registry(), indent=2) + "\n")
    runtime = load_runtime_state(project_root)
    if not runtime.get("session_import_cutoff"):
        runtime["session_import_cutoff"] = _iso_now()
        save_runtime_state(project_root, runtime)
    return destination
