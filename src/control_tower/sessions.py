from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .memory import import_project_sessions, mark_runtime_sync
from .project import load_runtime_state


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def update_git_branch(project_root: Path) -> str:
    branch = "unknown"
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
        branch = result.stdout.strip() or "unknown"
    except Exception:
        branch = "unknown"
    mark_runtime_sync(project_root, git_branch=branch)
    return branch


def sync_and_capture_latest(project_root: Path, role: str | None = None) -> str | None:
    new_sessions = import_project_sessions(project_root)
    latest = new_sessions[-1].session_id if new_sessions else None
    updates = {"last_sync_time": iso_now()}
    if role == "tower" and latest:
        updates["last_tower_session_id"] = latest
    elif role and latest:
        runtime = load_runtime_state(project_root)
        agent_runs = runtime.get("last_agent_sessions", {})
        agent_runs[role] = latest
        updates["last_agent_sessions"] = agent_runs
    mark_runtime_sync(project_root, **updates)
    return latest
