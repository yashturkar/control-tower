from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .layout import sessions_root, tower_dir
from .project import (
    load_agent_registry,
    load_project_config,
    load_runtime_state,
    load_session_index,
    save_runtime_state,
    save_session_index,
    write_text,
)


@dataclass
class ImportedSession:
    session_id: str
    timestamp: str
    source_path: Path
    transcript_path: Path
    session_copy_path: Path
    user_messages: list[str]
    agent_messages: list[str]
    source: str | None
    originator: str | None


def _iter_session_files() -> list[Path]:
    root = sessions_root()
    if not root.exists():
        return []
    return sorted(root.rglob("*.jsonl"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    items = []
    for line in path.read_text().splitlines():
        if line.strip():
            items.append(json.loads(line))
    return items


def _session_meta(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in events:
        if event.get("type") == "session_meta":
            return event.get("payload", {})
    return None


def _collect_transcript(events: list[dict[str, Any]]) -> tuple[list[str], list[str], list[str]]:
    transcript_lines: list[str] = []
    user_messages: list[str] = []
    agent_messages: list[str] = []
    for event in events:
        if event.get("type") != "event_msg":
            continue
        payload = event.get("payload", {})
        event_type = payload.get("type")
        if event_type == "user_message":
            message = (payload.get("message") or "").strip()
            if message:
                user_messages.append(message)
                transcript_lines.append(f"## User\n\n{message}\n")
        elif event_type == "agent_message":
            message = (payload.get("message") or "").strip()
            if message:
                agent_messages.append(message)
                transcript_lines.append(f"## Agent\n\n{message}\n")
    return transcript_lines, user_messages, agent_messages


def import_project_sessions(project_root: Path) -> list[ImportedSession]:
    project_root = project_root.resolve()
    base = tower_dir(project_root)
    index = load_session_index(project_root)
    imported = index.setdefault("sessions", {})
    new_sessions: list[ImportedSession] = []

    for session_path in _iter_session_files():
        events = _load_jsonl(session_path)
        meta = _session_meta(events)
        if not meta:
            continue
        cwd = meta.get("cwd")
        session_id = meta.get("id")
        if not session_id or not cwd:
            continue
        try:
            normalized_cwd = str(Path(cwd).expanduser().resolve())
        except Exception:
            normalized_cwd = cwd
        if normalized_cwd != str(project_root):
            continue
        if session_id in imported:
            continue

        transcript_lines, user_messages, agent_messages = _collect_transcript(events)
        session_copy_path = base / "memory" / "l2" / "sessions" / f"{session_id}.jsonl"
        session_copy_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(session_path, session_copy_path)

        transcript_path = base / "memory" / "l2" / "transcripts" / f"{session_id}.md"
        write_text(transcript_path, "\n".join(transcript_lines).strip() + "\n" if transcript_lines else "")

        imported[session_id] = {
            "session_id": session_id,
            "timestamp": meta.get("timestamp"),
            "source_path": str(session_path),
            "cached_copy": str(session_copy_path),
            "transcript_path": str(transcript_path),
            "cwd": normalized_cwd,
            "originator": meta.get("originator"),
            "source": meta.get("source"),
            "user_message_count": len(user_messages),
            "agent_message_count": len(agent_messages),
        }
        new_sessions.append(
            ImportedSession(
                session_id=session_id,
                timestamp=meta.get("timestamp", ""),
                source_path=session_path,
                transcript_path=transcript_path,
                session_copy_path=session_copy_path,
                user_messages=user_messages,
                agent_messages=agent_messages,
                source=meta.get("source"),
                originator=meta.get("originator"),
            )
        )

    save_session_index(project_root, index)
    if new_sessions:
        _append_black_box_events(project_root, new_sessions)
    _refresh_memory(project_root)
    return new_sessions


def _append_black_box_events(project_root: Path, sessions: list[ImportedSession]) -> None:
    log_path = tower_dir(project_root) / "logs" / "black-box.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as handle:
        for session in sessions:
            event = {
                "event_type": "codex_session_imported",
                "session_id": session.session_id,
                "timestamp": session.timestamp,
                "source": session.source,
                "originator": session.originator,
                "transcript_path": str(session.transcript_path.relative_to(project_root)),
            }
            handle.write(json.dumps(event) + "\n")


def _refresh_memory(project_root: Path) -> None:
    config = load_project_config(project_root)
    runtime = load_runtime_state(project_root)
    index = load_session_index(project_root)
    sessions = sorted(index.get("sessions", {}).values(), key=lambda item: item.get("timestamp", ""))
    branch = runtime.get("git_branch") or "unknown"
    last_tower_session_id = runtime.get("last_tower_session_id")
    last_session = sessions[-1] if sessions else None
    recent_user_goals = _collect_recent_user_goals(project_root, sessions)

    l0 = _build_l0(branch, last_session, last_tower_session_id, recent_user_goals)
    l1 = _build_l1(project_root, config, runtime, sessions, recent_user_goals)

    base = tower_dir(project_root)
    write_text(base / "memory" / "l0.md", l0)
    write_text(base / "memory" / "l1.md", l1)


def _collect_recent_user_goals(project_root: Path, sessions: list[dict[str, Any]]) -> list[str]:
    goals: list[str] = []
    base = tower_dir(project_root)
    for session in reversed(sessions):
        transcript = base / "memory" / "l2" / "transcripts" / f"{session['session_id']}.md"
        if not transcript.exists():
            continue
        sections = transcript.read_text().split("## User\n\n")
        for block in sections[1:]:
            snippet = block.split("\n## ", 1)[0].strip().replace("\n", " ")
            if snippet:
                goals.append(snippet[:220])
            if len(goals) >= 5:
                return goals
    return goals


def _build_l0(
    branch: str,
    last_session: dict[str, Any] | None,
    last_tower_session_id: str | None,
    recent_user_goals: list[str],
) -> str:
    if not last_session:
        return (
            "Control Tower is initialized but has no imported Codex history yet. "
            "Next step: start a Tower session for this repo and sync memory after meaningful work.\n"
        )
    latest_goal = recent_user_goals[0] if recent_user_goals else "No captured user goal yet."
    tower_ref = last_tower_session_id or last_session.get("session_id")
    return (
        f"Project is on branch `{branch}` with {last_session.get('session_id')} as the latest imported session. "
        f"Last tracked Tower session: `{tower_ref}`. "
        f"Most recent user goal: {latest_goal}\n"
    )


def _build_l1(
    project_root: Path,
    config: dict[str, Any],
    runtime: dict[str, Any],
    sessions: list[dict[str, Any]],
    recent_user_goals: list[str],
) -> str:
    registry = load_agent_registry(project_root)
    active_agents = [
        agent_config.get("name", agent_key)
        for agent_key, agent_config in registry.get("agents", {}).items()
        if agent_config.get("enabled")
    ]
    lines = [
        "# L1 Working Memory",
        "",
        "## Project",
        "",
        f"- Name: {config.get('project_name', project_root.name)}",
        f"- Root: {project_root}",
        f"- Primary agent: {config.get('primary_agent', 'Tower')}",
        f"- Current branch: {runtime.get('git_branch', 'unknown')}",
        "",
        "## Status",
        "",
        f"- Imported Codex sessions: {len(sessions)}",
        f"- Last Tower session: {runtime.get('last_tower_session_id', 'none')}",
        f"- Last sync time: {runtime.get('last_sync_time', 'never')}",
        "",
        "## Active Agents",
        "",
    ]
    lines.append("- Tower")
    if active_agents:
        lines.extend(f"- {agent}" for agent in active_agents)
    else:
        lines.append("- No subagents enabled")
    lines.extend(
        [
            "",
            "## Recent User Goals",
            "",
        ]
    )
    if recent_user_goals:
        lines.extend(f"- {goal}" for goal in recent_user_goals)
    else:
        lines.append("- No imported user goals yet")

    lines.extend(
        [
            "",
            "## Memory Policy",
            "",
            "- L2 is the source of truth for imported Codex sessions.",
            "- L1 is deterministic and should be curated further by Scribe after major work.",
            "- L0 must stay concise and action-oriented.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def mark_runtime_sync(project_root: Path, **updates: Any) -> None:
    runtime = load_runtime_state(project_root)
    runtime.update(updates)
    save_runtime_state(project_root, runtime)
