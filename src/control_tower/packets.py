from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_packet(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"Packet file does not exist: {path}")
    raw = path.read_text().strip()
    if not raw:
        raise ValueError(f"Packet file is empty: {path}")
    return json.loads(raw)


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "task"


def validate_task_packet(packet: dict[str, Any]) -> None:
    required = [
        "schema_version",
        "packet_type",
        "packet_id",
        "trace_id",
        "created_at",
        "from_agent",
        "to_agent",
        "task_type",
        "priority",
        "project_id",
        "session_id",
        "title",
        "objective",
        "instructions",
        "constraints",
        "inputs",
        "expected_outputs",
        "definition_of_done",
        "memory_context_refs",
        "doc_context_refs",
        "time_budget",
        "requires_review",
        "allow_partial",
        "metadata",
    ]
    missing = [key for key in required if key not in packet]
    if missing:
        raise ValueError(f"TaskPacket missing required fields: {', '.join(missing)}")
    if packet.get("packet_type") != "task":
        raise ValueError("TaskPacket packet_type must be 'task'")

    time_budget = packet.get("time_budget")
    if not isinstance(time_budget, dict):
        raise ValueError("TaskPacket time_budget must be an object")
    if "soft_seconds" not in time_budget or "hard_seconds" not in time_budget:
        raise ValueError("TaskPacket time_budget must include soft_seconds and hard_seconds")


def validate_result_packet(packet: dict[str, Any]) -> None:
    required = [
        "schema_version",
        "packet_type",
        "packet_id",
        "trace_id",
        "parent_packet_id",
        "created_at",
        "from_agent",
        "to_agent",
        "status",
        "summary",
        "work_completed",
        "artifacts_changed",
        "artifacts_created",
        "artifacts_deleted",
        "findings",
        "follow_up_recommendations",
        "review_requested",
        "doc_update_needed",
        "memory_worthy",
        "metrics",
        "raw_output_ref",
        "metadata",
    ]
    missing = [key for key in required if key not in packet]
    if missing:
        raise ValueError(f"ResultPacket missing required fields: {', '.join(missing)}")
    if packet.get("packet_type") != "result":
        raise ValueError("ResultPacket packet_type must be 'result'")


def create_task_packet(
    *,
    from_agent: str,
    to_agent: str,
    task_type: str,
    priority: str,
    project_id: str,
    session_id: str,
    title: str,
    objective: str,
    instructions: list[str],
    constraints: list[str],
    files: list[str],
    artifacts: list[str],
    references: list[str],
    expected_outputs: list[str],
    definition_of_done: list[str],
    memory_context_refs: list[str],
    doc_context_refs: list[str],
    soft_seconds: int,
    hard_seconds: int,
    requires_review: bool,
    allow_partial: bool,
    metadata: dict[str, Any] | None = None,
    trace_id: str | None = None,
    parent_packet_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "packet_type": "task",
        "packet_id": str(uuid.uuid4()),
        "trace_id": trace_id or str(uuid.uuid4()),
        "parent_packet_id": parent_packet_id,
        "created_at": utc_now(),
        "from_agent": from_agent,
        "to_agent": to_agent,
        "task_type": task_type,
        "priority": priority,
        "project_id": project_id,
        "session_id": session_id,
        "title": title,
        "objective": objective,
        "instructions": instructions,
        "constraints": constraints,
        "inputs": {
            "files": files,
            "artifacts": artifacts,
            "references": references,
        },
        "expected_outputs": expected_outputs,
        "definition_of_done": definition_of_done,
        "memory_context_refs": memory_context_refs,
        "doc_context_refs": doc_context_refs,
        "time_budget": {
            "soft_seconds": soft_seconds,
            "hard_seconds": hard_seconds,
        },
        "requires_review": requires_review,
        "allow_partial": allow_partial,
        "metadata": metadata or {},
    }


def new_scribe_memory_sync_packet(project_id: str, session_id: str, trace_id: str, refs: list[str]) -> dict[str, Any]:
    packet_id = str(uuid.uuid4())
    return {
        "schema_version": "1.0.0",
        "packet_type": "task",
        "packet_id": packet_id,
        "trace_id": trace_id,
        "parent_packet_id": None,
        "created_at": utc_now(),
        "from_agent": "tower",
        "to_agent": "scribe",
        "task_type": "memory-sync",
        "priority": "normal",
        "project_id": project_id,
        "session_id": session_id,
        "title": "Curate imported Tower memory",
        "objective": "Convert imported Codex sessions into durable working memory, task state, and documentation updates.",
        "instructions": [
            "Review newly imported L2 session logs and transcripts.",
            "Update L1 working memory and docs/state to reflect new durable knowledge.",
            "Call out unresolved risks, stale docs, and open questions explicitly.",
        ],
        "constraints": [
            "Do not invent facts that are not grounded in imported logs or repo state.",
            "Keep L0 concise and action-oriented.",
            "Preserve append-only behavior for raw logs.",
        ],
        "inputs": {
            "files": refs,
            "artifacts": [],
            "references": [],
        },
        "expected_outputs": [
            "Updated docs/state files if needed",
            "A ResultPacket with doc and memory follow-ups",
        ],
        "definition_of_done": [
            "New sessions are reflected in memory summaries",
            "Doc drift is captured or corrected",
            "Open questions are current",
        ],
        "memory_context_refs": refs,
        "doc_context_refs": [
            ".control-tower/docs/state/current-status.md",
            ".control-tower/docs/state/open-questions.md",
            ".control-tower/docs/tasks/active.md",
        ],
        "time_budget": {"soft_seconds": 300, "hard_seconds": 900},
        "requires_review": False,
        "allow_partial": True,
        "metadata": {"generated_by": "tower sync-memory"},
    }


def new_scribe_docs_followup_packet(
    project_id: str,
    session_id: str,
    trace_id: str,
    from_agent: str,
    result_ref: str,
    changed_files: list[str],
    doc_refs: list[str],
) -> dict[str, Any]:
    packet_id = str(uuid.uuid4())
    return {
        "schema_version": "1.0.0",
        "packet_type": "task",
        "packet_id": packet_id,
        "trace_id": trace_id,
        "parent_packet_id": None,
        "created_at": utc_now(),
        "from_agent": "tower",
        "to_agent": "scribe",
        "task_type": "documentation",
        "priority": "normal",
        "project_id": project_id,
        "session_id": session_id,
        "title": f"Update repo docs after {from_agent.title()} work",
        "objective": "Inspect the latest agent result and update the impacted durable repo docs under the configured docs harness.",
        "instructions": [
            "Review the referenced ResultPacket and the changed files before editing docs.",
            "Update existing relevant docs under the configured repo docs roots when possible.",
            "Create a new repo doc only if no suitable existing page covers the change.",
            "Refresh docs indices if you add a new page.",
            "Report doc drift or unresolved ambiguity explicitly instead of inventing facts.",
        ],
        "constraints": [
            "Treat repo docs under `docs/` as the durable docs harness.",
            "Treat `.control-tower/docs/state` and `.control-tower/memory` as operational memory, not durable product docs.",
            "Do not modify product source code unless the task packet explicitly requires a small doc-adjacent fix.",
        ],
        "inputs": {
            "files": changed_files,
            "artifacts": [],
            "references": [result_ref],
        },
        "expected_outputs": [
            "Updated repo docs if needed",
            "A ResultPacket summarizing doc updates, drift, and follow-up gaps",
        ],
        "definition_of_done": [
            "Durable repo docs reflect the changed behavior or workflow",
            "Relevant indices are refreshed if new docs were added",
            "Open doc drift or ambiguity is called out explicitly",
        ],
        "memory_context_refs": [result_ref],
        "doc_context_refs": doc_refs,
        "time_budget": {"soft_seconds": 300, "hard_seconds": 900},
        "requires_review": False,
        "allow_partial": True,
        "metadata": {
            "generated_by": "tower delegate follow-up",
            "seed_result_packet": result_ref,
            "seed_result_agent": from_agent,
        },
    }
