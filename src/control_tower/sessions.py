from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .layout import sessions_root
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


def find_latest_session_id_for_project(project_root: Path) -> str | None:
    project_root = project_root.resolve()
    candidates: list[tuple[str, str]] = []
    root = sessions_root()
    if not root.exists():
        return None

    for session_path in root.rglob("*.jsonl"):
        try:
            first_line = session_path.read_text().splitlines()[0]
            event = json.loads(first_line)
        except Exception:
            continue
        if event.get("type") != "session_meta":
            continue
        payload = event.get("payload", {})
        session_id = payload.get("id")
        cwd = payload.get("cwd")
        timestamp = payload.get("timestamp")
        if not session_id or not cwd or not timestamp:
            continue
        try:
            normalized_cwd = Path(cwd).expanduser().resolve()
        except Exception:
            continue
        if normalized_cwd == project_root:
            candidates.append((timestamp, session_id))

    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]
