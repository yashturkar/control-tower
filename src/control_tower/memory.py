from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .graph import append_graph_events, sync_decision_graph
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


_META_GOAL_AGENT_NAMES = ("tower", "scout", "builder", "inspector", "git-master", "scribe")
_META_GOAL_ROLE_PHRASES = (
    "the main orchestrator for this repository",
    "the research and discovery specialist",
    "the implementation specialist",
    "the review and verification specialist",
    "the git and pr specialist",
    "the documentation and memory specialist",
)
_META_GOAL_SECTION_MARKERS = (
    "bootstrap files",
    "configured agents",
    "current request",
    "l0",
    "l1",
    "l1 working memory",
    "memory",
    "memory policy",
    "operating rules",
    "recent user goals",
)
_TRANSCRIPT_SECTION_SPLIT_RE = re.compile(r"\n## (?:User|Agent)\n\n", re.MULTILINE)
_MARKDOWN_LIST_PREFIX_RE = re.compile(r"^(?:[-*+]\s+|\d+\.\s+)")


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
        append_graph_events(project_root, _session_graph_events(project_root, new_sessions))
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
    graph_state = sync_decision_graph(project_root)
    graph_nodes = graph_state.get("nodes", {})
    graph_indexes = graph_state.get("indexes", {})

    l0 = _build_l0(branch, last_session, last_tower_session_id, recent_user_goals, graph_indexes, graph_nodes)
    l1 = _build_l1(project_root, config, runtime, sessions, recent_user_goals, graph_indexes, graph_nodes)

    base = tower_dir(project_root)
    write_text(base / "memory" / "l0.md", l0)
    write_text(base / "memory" / "l1.md", l1)


def _collect_recent_user_goals(project_root: Path, sessions: list[dict[str, Any]]) -> list[str]:
    goals: list[str] = []
    seen: set[str] = set()
    base = tower_dir(project_root)
    for session in reversed(sessions):
        transcript = base / "memory" / "l2" / "transcripts" / f"{session['session_id']}.md"
        if not transcript.exists():
            continue
        sections = transcript.read_text().split("## User\n\n")
        for block in sections[1:]:
            snippet = _extract_user_goal_snippet(block)
            if not snippet or _is_bootstrap_or_meta_goal(snippet):
                continue
            dedupe_key = _goal_dedupe_key(snippet)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            goals.append(snippet[:220])
            if len(goals) >= 5:
                return goals
    return goals


def _extract_user_goal_snippet(block: str) -> str | None:
    message = _extract_user_message_block(block)
    if not message or _is_structured_meta_message(message):
        return None

    paragraph: list[str] = []
    for raw_line in message.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if paragraph:
                break
            continue
        if stripped.startswith("```") or stripped.startswith(">"):
            break
        if _is_meta_heading_line(stripped):
            if paragraph:
                break
            continue

        cleaned = _strip_markdown_list_prefix(stripped)
        if _is_meta_heading_line(cleaned):
            if paragraph:
                break
            continue

        if cleaned.startswith("#"):
            if paragraph:
                break
            return None

        paragraph.append(cleaned)
        if stripped != cleaned:
            break

    snippet = " ".join(paragraph).strip()
    return snippet or None


def _is_bootstrap_or_meta_goal(snippet: str) -> bool:
    normalized = _normalize_goal_text(snippet)
    if not normalized:
        return False
    if snippet.lstrip().startswith("#"):
        return True
    if any(normalized.startswith(f"# {agent}") for agent in _META_GOAL_AGENT_NAMES):
        return True
    if _contains_meta_role_text(normalized):
        return True
    return False


def _extract_user_message_block(block: str) -> str:
    return _TRANSCRIPT_SECTION_SPLIT_RE.split(block, maxsplit=1)[0].strip()


def _is_structured_meta_message(message: str) -> bool:
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    if not lines:
        return False
    first_line = lines[0]
    if first_line.startswith(">") or first_line.startswith("```"):
        return True

    meta_heading_hits = sum(1 for line in lines if _is_meta_heading_line(line))
    if meta_heading_hits >= 2:
        return True

    normalized = _normalize_goal_text(message)
    if meta_heading_hits and _contains_meta_role_text(normalized):
        return True
    return False


def _is_meta_heading_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    heading_text = _extract_markdown_heading_text(_strip_markdown_list_prefix(stripped))
    if heading_text is None:
        return False
    return _normalize_goal_text(heading_text) in _META_GOAL_SECTION_MARKERS


def _extract_markdown_heading_text(line: str) -> str | None:
    if not line.startswith("#"):
        return None
    return line.lstrip("#").strip() or None


def _strip_markdown_list_prefix(line: str) -> str:
    return _MARKDOWN_LIST_PREFIX_RE.sub("", line, count=1).strip()


def _contains_meta_role_text(normalized: str) -> bool:
    if any(f"you are {agent}" in normalized for agent in _META_GOAL_AGENT_NAMES):
        return True
    if any(phrase in normalized for phrase in _META_GOAL_ROLE_PHRASES):
        return True
    return False


def _goal_dedupe_key(snippet: str) -> str:
    return _normalize_goal_text(snippet)


def _normalize_goal_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _build_l0(
    branch: str,
    last_session: dict[str, Any] | None,
    last_tower_session_id: str | None,
    recent_user_goals: list[str],
    graph_indexes: dict[str, Any],
    graph_nodes: dict[str, dict[str, Any]],
) -> str:
    if not last_session:
        return (
            "Control Tower is initialized but has no imported Codex history yet. "
            "Next step: start a Tower session for this repo and sync memory after meaningful work.\n"
        )
    latest_goal = recent_user_goals[0] if recent_user_goals else "No captured user goal yet."
    tower_ref = last_tower_session_id or last_session.get("session_id")
    active_decision = _first_graph_title(graph_indexes.get("active_decisions", []), graph_nodes)
    open_question = _first_graph_title(graph_indexes.get("open_questions", []), graph_nodes)
    recent_commit = _format_recent_commit(graph_indexes.get("recent_commits", []), graph_indexes, graph_nodes)
    return (
        f"Project is on branch `{branch}` with {last_session.get('session_id')} as the latest imported session. "
        f"Last tracked Tower session: `{tower_ref}`. "
        f"Most recent user goal: {latest_goal} "
        f"Top active decision: {active_decision}. "
        f"Top open question: {open_question}. "
        f"Recent commit status: {recent_commit}\n"
    )


def _build_l1(
    project_root: Path,
    config: dict[str, Any],
    runtime: dict[str, Any],
    sessions: list[dict[str, Any]],
    recent_user_goals: list[str],
    graph_indexes: dict[str, Any],
    graph_nodes: dict[str, dict[str, Any]],
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
            "## Active Decisions",
            "",
        ]
    )
    _extend_graph_section(lines, graph_indexes.get("active_decisions", []), graph_nodes, empty_message="No accepted decisions yet")
    lines.extend(
        [
            "",
            "## Current Tasks",
            "",
        ]
    )
    _extend_graph_section(lines, graph_indexes.get("current_tasks", []), graph_nodes, empty_message="No active tasks in the ledger")
    lines.extend(
        [
            "",
            "## Open Questions",
            "",
        ]
    )
    _extend_graph_section(lines, graph_indexes.get("open_questions", []), graph_nodes, empty_message="No open questions recorded")
    lines.extend(
        [
            "",
            "## Known Risks",
            "",
        ]
    )
    _extend_graph_section(lines, graph_indexes.get("known_risks", []), graph_nodes, empty_message="No known risks recorded")
    lines.extend(
        [
            "",
            "## Recent Commits",
            "",
        ]
    )
    _extend_commit_section(lines, graph_indexes.get("recent_commits", []), graph_indexes, graph_nodes)
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
            "## Unexplained Changes",
            "",
        ]
    )
    if graph_indexes.get("unexplained_commits"):
        for commit_id in graph_indexes["unexplained_commits"]:
            commit = graph_nodes.get(commit_id, {})
            lines.append(f"- {commit.get('sha', commit_id)}: {commit.get('subject', 'No subject')} (needs curation)")
    else:
        lines.append("- No unexplained commits in the current graph window")

    lines.extend(
        [
            "",
            "## Memory Policy",
            "",
            "- L2 is the source of truth for imported Codex sessions.",
            "- The decision graph is the canonical structured provenance layer between L2 and L1/L0.",
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


def refresh_memory_views(project_root: Path) -> None:
    _refresh_memory(project_root)


def _session_graph_events(project_root: Path, sessions: list[ImportedSession]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for session in sessions:
        transcript_ref = str(session.transcript_path.relative_to(project_root))
        session_ref = str(session.session_copy_path.relative_to(project_root))
        node = {
            "id": f"session:{session.session_id}",
            "type": "session",
            "session_id": session.session_id,
            "timestamp": session.timestamp,
            "source": session.source,
            "originator": session.originator,
            "transcript_path": transcript_ref,
            "session_path": session_ref,
        }
        events.append(
            {
                "event_id": f"session.observed:session:{session.session_id}",
                "timestamp": session.timestamp,
                "event_type": "session.observed",
                "payload": node,
            }
        )
    return events


def _first_graph_title(node_ids: list[str], graph_nodes: dict[str, dict[str, Any]]) -> str:
    if not node_ids:
        return "None recorded"
    node = graph_nodes.get(node_ids[0], {})
    return str(node.get("title") or node.get("subject") or node_ids[0])


def _format_recent_commit(commit_ids: list[str], graph_indexes: dict[str, Any], graph_nodes: dict[str, dict[str, Any]]) -> str:
    if not commit_ids:
        return "No commits observed"
    commit_id = commit_ids[0]
    commit = graph_nodes.get(commit_id, {})
    sha = commit.get("sha", commit_id)
    subject = commit.get("subject", "No subject")
    unexplained = commit_id in set(graph_indexes.get("unexplained_commits", []))
    suffix = "unexplained" if unexplained else "linked"
    return f"{sha} ({subject}, {suffix})"


def _extend_graph_section(
    lines: list[str],
    node_ids: list[str],
    graph_nodes: dict[str, dict[str, Any]],
    *,
    empty_message: str,
) -> None:
    if not node_ids:
        lines.append(f"- {empty_message}")
        return
    for node_id in node_ids[:5]:
        node = graph_nodes.get(node_id, {})
        title = node.get("title") or node.get("subject") or node_id
        summary = node.get("summary") or node.get("status")
        if summary:
            lines.append(f"- {title}: {summary}")
        else:
            lines.append(f"- {title}")


def _extend_commit_section(
    lines: list[str],
    commit_ids: list[str],
    graph_indexes: dict[str, Any],
    graph_nodes: dict[str, dict[str, Any]],
) -> None:
    if not commit_ids:
        lines.append("- No commits observed yet")
        return
    unexplained = set(graph_indexes.get("unexplained_commits", []))
    for commit_id in commit_ids[:5]:
        commit = graph_nodes.get(commit_id, {})
        sha = commit.get("sha", commit_id)
        subject = commit.get("subject", "No subject")
        if commit_id in unexplained:
            lines.append(f"- {sha}: {subject} (no linked rationale yet)")
        else:
            lines.append(f"- {sha}: {subject}")
