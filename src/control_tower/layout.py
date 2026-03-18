from __future__ import annotations

import os
from pathlib import Path


CONTROL_TOWER_DIRNAME = ".control-tower"


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def tower_dir(project_root: Path) -> Path:
    return project_root / CONTROL_TOWER_DIRNAME


def get_codex_home() -> Path:
    override = os.environ.get("CONTROL_TOWER_CODEX_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".codex"


def sessions_root() -> Path:
    return get_codex_home() / "sessions"
