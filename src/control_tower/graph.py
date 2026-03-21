from __future__ import annotations

import json
import math
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .layout import tower_dir
from .packets import load_packet, slugify
from .project import (
    load_graph_edges,
    load_graph_indexes,
    load_graph_nodes,
    load_runtime_state,
    load_session_index,
    load_task_ledger,
    read_text,
    save_graph_edges,
    save_graph_indexes,
    save_graph_nodes,
)


def graph_events_path(project_root: Path) -> Path:
    return tower_dir(project_root) / "state" / "decision-graph" / "events.jsonl"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_graph_events(project_root: Path) -> list[dict[str, Any]]:
    path = graph_events_path(project_root)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def append_graph_event(project_root: Path, event: dict[str, Any]) -> None:
    path = graph_events_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(event) + "\n")


def append_graph_events(project_root: Path, events: list[dict[str, Any]]) -> int:
    if not events:
        return 0
    existing = load_graph_events(project_root)
    seen = {_event_dedupe_key(event) for event in existing}
    appended = 0
    path = graph_events_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for event in events:
            dedupe = _event_dedupe_key(event)
            if dedupe in seen:
                continue
            handle.write(json.dumps(event) + "\n")
            seen.add(dedupe)
            appended += 1
    return appended


def sync_decision_graph(project_root: Path) -> dict[str, Any]:
    append_graph_events(project_root, _collect_state_events(project_root))
    return materialize_decision_graph(project_root)


def materialize_decision_graph(project_root: Path) -> dict[str, Any]:
    events = load_graph_events(project_root)
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    for event in events:
        payload = event.get("payload", {})
        event_type = event.get("event_type")
        if event_type in {
            "session.observed",
            "task.observed",
            "packet.observed",
            "commit.observed",
            "question.observed",
            "risk.observed",
            "decision.created",
            "event.observed",
            "artifact.observed",
        }:
            node = dict(payload)
            if node.get("id"):
                nodes[node["id"]] = node
        elif event_type == "edge.observed":
            edge = dict(payload)
            if edge.get("id"):
                edges[edge["id"]] = edge

    indexes = _build_indexes(nodes, list(edges.values()), load_runtime_state(project_root))
    save_graph_nodes(project_root, {"nodes": nodes})
    save_graph_edges(project_root, {"edges": list(edges.values())})
    save_graph_indexes(project_root, indexes)
    write_decision_register(project_root, indexes, nodes)
    return {"nodes": nodes, "edges": list(edges.values()), "indexes": indexes}


def create_decision_event(
    *,
    topic: str,
    title: str,
    summary: str,
    rationale: list[str],
    status: str,
    importance: str,
    source_refs: list[str],
    created_by: str,
    inferred: bool,
    related_refs: list[str] | None = None,
    related_node_ids: list[str] | None = None,
    decision_id: str | None = None,
) -> list[dict[str, Any]]:
    timestamp = utc_now()
    decision_id = decision_id or f"dec_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{slugify(topic)}"
    decision_node = {
        "id": decision_id,
        "type": "decision",
        "topic": topic,
        "title": title,
        "status": status,
        "importance": importance,
        "summary": summary,
        "rationale": rationale,
        "source_refs": source_refs,
        "inferred": inferred,
        "created_at": timestamp,
        "created_by": created_by,
    }
    events = [
        {
            "event_id": f"decision-created:{decision_id}",
            "timestamp": timestamp,
            "event_type": "decision.created",
            "payload": decision_node,
        }
    ]
    for ref in related_refs or []:
        artifact_node = {
            "id": _ref_node_id(ref),
            "type": "artifact",
            "ref": ref,
            "title": ref,
            "created_at": timestamp,
        }
        events.append(
            {
                "event_id": f"artifact.observed:{artifact_node['id']}",
                "timestamp": timestamp,
                "event_type": "artifact.observed",
                "payload": artifact_node,
            }
        )
        edge = {
            "id": f"edge:decision-ref:{decision_id}:{slugify(ref)}",
            "type": "references",
            "from": decision_id,
            "to": _ref_node_id(ref),
            "created_at": timestamp,
            "evidence_refs": source_refs,
        }
        events.append(
            {
                "event_id": f"edge-observed:{edge['id']}",
                "timestamp": timestamp,
                "event_type": "edge.observed",
                "payload": edge,
            }
        )
    for related_node_id in related_node_ids or []:
        edge = {
            "id": f"edge:decision-node:{decision_id}:{slugify(related_node_id)}",
            "type": "references",
            "from": decision_id,
            "to": related_node_id,
            "created_at": timestamp,
            "evidence_refs": source_refs,
        }
        events.append(
            {
                "event_id": f"edge-observed:{edge['id']}",
                "timestamp": timestamp,
                "event_type": "edge.observed",
                "payload": edge,
            }
        )
    return events


def graph_status(project_root: Path) -> dict[str, Any]:
    indexes = load_graph_indexes(project_root)
    nodes = load_graph_nodes(project_root).get("nodes", {})
    return {
        "active_decisions": len(indexes.get("active_decisions", [])),
        "inferred_decisions": len(indexes.get("inferred_decisions", [])),
        "unexplained_commits": len(indexes.get("unexplained_commits", [])),
        "open_questions": len(indexes.get("open_questions", [])),
        "known_risks": len(indexes.get("known_risks", [])),
        "nodes": len(nodes),
        "edges": len(load_graph_edges(project_root).get("edges", [])),
        "last_graph_sync": indexes.get("last_graph_sync", "never"),
    }


def explain_commit(project_root: Path, sha: str) -> dict[str, Any]:
    nodes = load_graph_nodes(project_root).get("nodes", {})
    edges = load_graph_edges(project_root).get("edges", [])
    commit_id = _resolve_commit_id(nodes, sha)
    commit = nodes.get(commit_id)
    related = [edge for edge in edges if edge.get("to") == commit_id or edge.get("from") == commit_id]
    linked_decisions = []
    linked_sessions = []
    linked_packets: list[dict[str, Any]] = []
    for edge in related:
        other = edge.get("from") if edge.get("to") == commit_id else edge.get("to")
        node = nodes.get(other, {})
        if node.get("type") == "decision":
            linked_decisions.append(node)
        elif node.get("type") == "session":
            linked_sessions.append(node)
        elif node.get("type") == "packet":
            linked_packets.append(node)
    session_ids = {node.get("id") for node in linked_sessions}
    packet_ids = {node.get("id") for node in linked_packets}
    for edge in edges:
        if edge.get("type") == "discussed_in" and edge.get("to") in session_ids:
            packet = nodes.get(edge.get("from"), {})
            if packet.get("type") == "packet":
                packet_ids.add(packet.get("id"))
                linked_packets.append(packet)
    for edge in edges:
        from_id = edge.get("from")
        to_id = edge.get("to")
        if from_id in packet_ids:
            node = nodes.get(to_id, {})
            if node.get("type") == "decision" and node not in linked_decisions:
                linked_decisions.append(node)
            if node.get("type") == "artifact":
                linked_decisions.extend(_decisions_for_artifact(nodes, edges, node.get("id")))
        elif to_id in packet_ids:
            node = nodes.get(from_id, {})
            if node.get("type") == "decision" and node not in linked_decisions:
                linked_decisions.append(node)
            if node.get("type") == "artifact":
                linked_decisions.extend(_decisions_for_artifact(nodes, edges, node.get("id")))
    return {
        "commit": commit,
        "linked_decisions": linked_decisions,
        "linked_sessions": linked_sessions,
        "linked_packets": linked_packets,
        "edges": related,
    }


def explain_decision(project_root: Path, decision_id: str) -> dict[str, Any]:
    nodes = load_graph_nodes(project_root).get("nodes", {})
    edges = load_graph_edges(project_root).get("edges", [])
    decision = nodes.get(decision_id)
    related = [edge for edge in edges if edge.get("to") == decision_id or edge.get("from") == decision_id]
    related_nodes = []
    for edge in related:
        other = edge.get("from") if edge.get("to") == decision_id else edge.get("to")
        node = nodes.get(other)
        if node:
            related_nodes.append(node)
    return {"decision": decision, "edges": related, "related_nodes": related_nodes}


def graph_snapshot(project_root: Path) -> dict[str, Any]:
    nodes = load_graph_nodes(project_root).get("nodes", {})
    edges = load_graph_edges(project_root).get("edges", [])
    return {"nodes": nodes, "edges": edges}


def export_graph_json(project_root: Path) -> dict[str, Any]:
    snapshot = graph_snapshot(project_root)
    return {
        "nodes": list(snapshot["nodes"].values()),
        "edges": snapshot["edges"],
    }


def export_graph_dot(project_root: Path) -> str:
    snapshot = graph_snapshot(project_root)
    nodes = snapshot["nodes"]
    lines = ["digraph decision_graph {"]
    lines.append("  rankdir=LR;")
    for node_id, node in sorted(nodes.items()):
        label = str(node.get("title") or node.get("subject") or node.get("id") or node_id).replace('"', '\\"')
        node_type = str(node.get("type") or "node").replace('"', '\\"')
        lines.append(f'  "{node_id}" [label="{label}\\n({node_type})"];')
    for edge in snapshot["edges"]:
        from_id = edge.get("from")
        to_id = edge.get("to")
        if not from_id or not to_id:
            continue
        edge_type = str(edge.get("type") or "edge").replace('"', '\\"')
        lines.append(f'  "{from_id}" -> "{to_id}" [label="{edge_type}"];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def export_graph_svg(project_root: Path) -> str:
    snapshot = graph_snapshot(project_root)
    nodes = sorted(snapshot["nodes"].values(), key=lambda node: str(node.get("id", "")))
    edges = snapshot["edges"]
    width = 1200
    height = 900
    cx = width / 2
    cy = height / 2
    radius = min(width, height) * 0.36
    if not nodes:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            '<rect width="100%" height="100%" fill="#0b1020" />'
            '<text x="50%" y="50%" fill="#d1d5db" text-anchor="middle" font-family="sans-serif" font-size="24">'
            "No graph nodes found"
            "</text></svg>"
        )
    positions: dict[str, tuple[float, float]] = {}
    for index, node in enumerate(nodes):
        angle = (2 * math.pi * index) / len(nodes)
        positions[str(node.get("id"))] = (cx + radius * math.cos(angle), cy + radius * math.sin(angle))

    def _esc(value: str) -> str:
        return (
            value.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0b1020" />',
    ]
    for edge in edges:
        from_id = str(edge.get("from") or "")
        to_id = str(edge.get("to") or "")
        if from_id not in positions or to_id not in positions:
            continue
        x1, y1 = positions[from_id]
        x2, y2 = positions[to_id]
        parts.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="#374151" stroke-width="1.5" />')
    for node in nodes:
        node_id = str(node.get("id"))
        x, y = positions[node_id]
        label = _esc(str(node.get("title") or node.get("subject") or node_id))
        node_type = _esc(str(node.get("type") or "node"))
        parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="8" fill="#60a5fa" />')
        parts.append(
            f'<text x="{x + 12:.2f}" y="{y + 4:.2f}" fill="#e5e7eb" font-family="sans-serif" font-size="11">{label} [{node_type}]</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def neighborhood_view(project_root: Path, center_id: str, radius: int) -> dict[str, Any]:
    if radius < 0:
        raise ValueError("Neighborhood radius must be >= 0.")
    snapshot = graph_snapshot(project_root)
    nodes: dict[str, dict[str, Any]] = snapshot["nodes"]
    edges: list[dict[str, Any]] = snapshot["edges"]
    if center_id not in nodes:
        return {"center": None, "nodes": [], "edges": []}
    visited = {center_id}
    frontier = {center_id}
    kept_edges: list[dict[str, Any]] = []
    for _ in range(max(0, radius)):
        next_frontier: set[str] = set()
        for edge in edges:
            from_id = edge.get("from")
            to_id = edge.get("to")
            if not from_id or not to_id:
                continue
            if from_id in frontier and to_id in nodes:
                next_frontier.add(to_id)
                kept_edges.append(edge)
            elif to_id in frontier and from_id in nodes:
                next_frontier.add(from_id)
                kept_edges.append(edge)
        next_frontier -= visited
        visited |= next_frontier
        frontier = next_frontier
        if not frontier:
            break
    neighborhood_nodes = [nodes[node_id] for node_id in sorted(visited)]
    edge_ids: set[str] = set()
    neighborhood_edges: list[dict[str, Any]] = []
    for edge in kept_edges:
        edge_id = str(edge.get("id") or "")
        if edge_id and edge_id in edge_ids:
            continue
        if edge_id:
            edge_ids.add(edge_id)
        neighborhood_edges.append(edge)
    return {"center": nodes[center_id], "nodes": neighborhood_nodes, "edges": neighborhood_edges}


def filter_graph_payload(
    payload: dict[str, Any],
    *,
    query: str | None = None,
    node_types: list[str] | None = None,
) -> dict[str, Any]:
    nodes = payload.get("nodes", [])
    edges = payload.get("edges", [])
    normalized_types = {value.strip().lower() for value in (node_types or []) if value.strip()}
    query_value = (query or "").strip().lower()

    def _match(node: dict[str, Any]) -> bool:
        if normalized_types and str(node.get("type", "")).lower() not in normalized_types:
            return False
        if not query_value:
            return True
        haystack = " ".join(
            [
                str(node.get("id", "")),
                str(node.get("type", "")),
                str(node.get("title", "")),
                str(node.get("subject", "")),
                str(node.get("sha", "")),
                str(node.get("session_id", "")),
                str(node.get("task_id", "")),
            ]
        ).lower()
        return query_value in haystack

    kept_nodes = [node for node in nodes if _match(node)]
    kept_ids = {str(node.get("id")) for node in kept_nodes}
    kept_edges = [edge for edge in edges if edge.get("from") in kept_ids and edge.get("to") in kept_ids]
    center = payload.get("center")
    if isinstance(center, dict):
        center_id = str(center.get("id", ""))
        center = center if center_id in kept_ids else None
    return {"center": center, "nodes": kept_nodes, "edges": kept_edges}


def write_decision_register(project_root: Path, indexes: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> None:
    path = tower_dir(project_root) / "docs" / "state" / "decisions.md"
    lines = [
        "# Decisions",
        "",
        "## Active Decisions",
        "",
    ]
    active = indexes.get("active_decisions", [])
    if active:
        for decision_id in active:
            decision = nodes.get(decision_id, {})
            lines.append(f"- `{decision_id}` {decision.get('title', 'Untitled decision')}: {decision.get('summary', '')}".rstrip())
    else:
        lines.append("- No accepted decisions yet.")
    lines.extend(["", "## Proposed / Inferred Decisions", ""])
    inferred = indexes.get("inferred_decisions", [])
    if inferred:
        for decision_id in inferred:
            decision = nodes.get(decision_id, {})
            lines.append(f"- `{decision_id}` {decision.get('title', 'Untitled decision')}: {decision.get('summary', '')}".rstrip())
    else:
        lines.append("- No inferred decisions awaiting curation.")
    lines.extend(["", "## Superseded Decisions", ""])
    superseded = indexes.get("superseded_decisions", [])
    if superseded:
        for decision_id in superseded:
            decision = nodes.get(decision_id, {})
            lines.append(f"- `{decision_id}` {decision.get('title', 'Untitled decision')}")
    else:
        lines.append("- No superseded decisions recorded.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def _collect_state_events(project_root: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    events.extend(_session_events(project_root))
    events.extend(_task_events(project_root))
    events.extend(_packet_events(project_root))
    events.extend(_black_box_events(project_root))
    events.extend(_doc_state_events(project_root))
    events.extend(_commit_events(project_root))
    return events


def _session_events(project_root: Path) -> list[dict[str, Any]]:
    index = load_session_index(project_root)
    events: list[dict[str, Any]] = []
    for session_id, session in index.get("sessions", {}).items():
        node = {
            "id": f"session:{session_id}",
            "type": "session",
            "session_id": session_id,
            "timestamp": session.get("timestamp"),
            "source": session.get("source"),
            "originator": session.get("originator"),
            "transcript_path": session.get("transcript_path"),
            "cwd": session.get("cwd"),
        }
        events.append(_node_event("session.observed", node, f"session:{session_id}"))
    return events


def _task_events(project_root: Path) -> list[dict[str, Any]]:
    ledger = load_task_ledger(project_root)
    events: list[dict[str, Any]] = []
    for index, task in enumerate(ledger.get("tasks", []), start=1):
        if not isinstance(task, dict):
            continue
        title = str(task.get("title") or task.get("task") or f"Task {index}")
        task_id = str(task.get("id") or f"task:{slugify(title)}")
        node = {
            "id": task_id if task_id.startswith("task:") else f"task:{task_id}",
            "type": "task",
            "title": title,
            "status": task.get("status", "open"),
            "priority": task.get("priority", "normal"),
            "details": task,
        }
        events.append(_node_event("task.observed", node, f"task:{node['id']}"))
    return events


def _packet_events(project_root: Path) -> list[dict[str, Any]]:
    base = tower_dir(project_root) / "packets"
    if not base.exists():
        return []
    events: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*.json")):
        try:
            packet = load_packet(path)
        except Exception:
            continue
        packet_id = str(packet.get("packet_id") or path.stem)
        packet_type = str(packet.get("packet_type") or "packet")
        relative = _relative_ref(project_root, path)
        node = {
            "id": f"packet:{packet_id}",
            "type": "packet",
            "packet_id": packet_id,
            "packet_type": packet_type,
            "title": packet.get("title") or packet.get("summary") or path.name,
            "status": packet.get("status"),
            "trace_id": packet.get("trace_id"),
            "from_agent": packet.get("from_agent"),
            "to_agent": packet.get("to_agent"),
            "path": relative,
            "created_at": packet.get("created_at"),
        }
        events.append(_node_event("packet.observed", node, f"packet:{packet_id}"))
        artifact_node = {
            "id": _ref_node_id(relative),
            "type": "artifact",
            "ref": relative,
            "title": relative,
            "created_at": packet.get("created_at"),
        }
        events.append(_node_event("artifact.observed", artifact_node, artifact_node["id"]))
        events.append(
            _edge_event(
                {
                    "id": f"edge:packet-artifact:{packet_id}:{slugify(relative)}",
                    "type": "references",
                    "from": f"packet:{packet_id}",
                    "to": artifact_node["id"],
                    "created_at": packet.get("created_at") or utc_now(),
                    "evidence_refs": [relative],
                }
            )
        )

        session_id = packet.get("session_id")
        if session_id:
            events.append(
                _edge_event(
                    {
                        "id": f"edge:packet-session:{packet_id}:{session_id}",
                        "type": "discussed_in",
                        "from": f"packet:{packet_id}",
                        "to": f"session:{session_id}",
                        "created_at": packet.get("created_at") or utc_now(),
                        "evidence_refs": [relative],
                    }
                )
            )
        if packet_type == "result":
            events.extend(_memory_worthy_decision_events(packet, relative))
    return events


def _memory_worthy_decision_events(packet: dict[str, Any], packet_ref: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    packet_id = str(packet.get("packet_id") or "result")
    for index, item in enumerate(packet.get("memory_worthy", []) or []):
        title = str(item).strip()
        if not title:
            continue
        decision_id = f"dec_inferred_{packet_id}_{index}_{slugify(title)}"
        summary = f"Inferred from ResultPacket memory_worthy entry: {title}"
        events.extend(
            create_decision_event(
                topic=slugify(title),
                title=title,
                summary=summary,
                rationale=["Captured from a ResultPacket memory_worthy entry pending curation."],
                status="proposed",
                importance="normal",
                source_refs=[packet_ref],
                created_by=str(packet.get("from_agent") or "unknown"),
                inferred=True,
                related_refs=[packet_ref],
                related_node_ids=[f"packet:{packet_id}"],
                decision_id=decision_id,
            )
        )
    return events


def _black_box_events(project_root: Path) -> list[dict[str, Any]]:
    path = tower_dir(project_root) / "logs" / "black-box.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_text().splitlines()):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        event_type = str(payload.get("event_type") or f"log-event-{index}")
        node = {
            "id": f"event:black-box:{index}",
            "type": "event",
            "event_type": event_type,
            "timestamp": payload.get("timestamp"),
            "payload": payload,
        }
        events.append(_node_event("event.observed", node, f"black-box:{index}:{event_type}"))
    return events


def _doc_state_events(project_root: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for kind, filename in (("question", "open-questions.md"), ("risk", "known-risks.md")):
        path = tower_dir(project_root) / "docs" / "state" / filename
        for line in read_text(path).splitlines():
            line = line.strip()
            if not line.startswith("- "):
                continue
            title = line[2:].strip()
            if not title:
                continue
            node = {
                "id": f"{kind}:{slugify(title)}",
                "type": kind,
                "title": title,
                "status": "open",
                "source_ref": _relative_ref(project_root, path),
            }
            events.append(_node_event(f"{kind}.observed", node, f"{kind}:{slugify(title)}"))
    return events


def _commit_events(project_root: Path) -> list[dict[str, Any]]:
    if not (project_root / ".git").exists():
        return []
    try:
        result = subprocess.run(
            ["git", "log", "--date=iso-strict", "--pretty=format:%H%x1f%P%x1f%aI%x1f%s%x1e", "--name-only"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return []
    events: list[dict[str, Any]] = []
    sessions = _sorted_session_nodes(project_root)
    for record in result.stdout.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        lines = record.splitlines()
        meta = lines[0].split("\x1f")
        if len(meta) < 4:
            continue
        sha, parents, authored_at, subject = meta[:4]
        files = [line.strip() for line in lines[1:] if line.strip()]
        node = {
            "id": f"commit:{sha}",
            "type": "commit",
            "sha": sha,
            "parents": [value for value in parents.split() if value],
            "authored_at": authored_at,
            "subject": subject,
            "files": files,
        }
        events.append(_node_event("commit.observed", node, f"commit:{sha}"))
        session_node = _nearest_session_for_commit(sessions, node.get("authored_at"))
        if session_node:
            events.append(
                _edge_event(
                    {
                        "id": f"edge:commit-session:{sha}:{session_node['session_id']}",
                        "type": "caused_by",
                        "from": f"commit:{sha}",
                        "to": session_node["id"],
                        "created_at": authored_at,
                        "evidence_refs": [session_node.get("transcript_path", "")],
                    }
                )
            )
    return events


def _build_indexes(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]], runtime: dict[str, Any]) -> dict[str, Any]:
    active_decisions = sorted(
        [node_id for node_id, node in nodes.items() if node.get("type") == "decision" and node.get("status") == "accepted"],
        key=lambda node_id: nodes[node_id].get("created_at", ""),
        reverse=True,
    )
    inferred_decisions = sorted(
        [node_id for node_id, node in nodes.items() if node.get("type") == "decision" and node.get("inferred")],
        key=lambda node_id: nodes[node_id].get("created_at", ""),
        reverse=True,
    )
    superseded_decisions = sorted(
        [node_id for node_id, node in nodes.items() if node.get("type") == "decision" and node.get("status") == "superseded"],
        key=lambda node_id: nodes[node_id].get("created_at", ""),
        reverse=True,
    )
    open_questions = sorted(
        [node_id for node_id, node in nodes.items() if node.get("type") == "question" and node.get("status", "open") == "open"]
    )
    known_risks = sorted(
        [node_id for node_id, node in nodes.items() if node.get("type") == "risk" and node.get("status", "open") == "open"]
    )
    current_tasks = sorted(
        [node_id for node_id, node in nodes.items() if node.get("type") == "task" and node.get("status", "open") != "done"]
    )
    commits = sorted(
        [node for node in nodes.values() if node.get("type") == "commit"],
        key=lambda node: node.get("authored_at", ""),
        reverse=True,
    )
    explained_commit_ids = {edge.get("to") for edge in edges if edge.get("to", "").startswith("commit:")}
    unexplained_commits = [node["id"] for node in commits if node["id"] not in explained_commit_ids]
    session_links: dict[str, list[str]] = {}
    for edge in edges:
        from_id = edge.get("from")
        to_id = edge.get("to")
        if from_id and to_id and from_id.startswith("packet:") and to_id.startswith("session:"):
            session_links.setdefault(to_id, []).append(from_id)
    return {
        "active_decisions": active_decisions,
        "inferred_decisions": inferred_decisions,
        "superseded_decisions": superseded_decisions,
        "open_questions": open_questions,
        "known_risks": known_risks,
        "current_tasks": current_tasks,
        "recent_commits": [node["id"] for node in commits[:5]],
        "unexplained_commits": unexplained_commits[:5],
        "session_links": session_links,
        "last_graph_sync": utc_now(),
        "current_branch": runtime.get("git_branch", "unknown"),
    }


def _node_event(event_type: str, node: dict[str, Any], dedupe_suffix: str) -> dict[str, Any]:
    return {
        "event_id": f"{event_type}:{dedupe_suffix}",
        "timestamp": node.get("created_at") or node.get("timestamp") or node.get("authored_at") or utc_now(),
        "event_type": event_type,
        "payload": node,
    }


def _edge_event(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": f"edge.observed:{edge['id']}",
        "timestamp": edge.get("created_at") or utc_now(),
        "event_type": "edge.observed",
        "payload": edge,
    }


def _relative_ref(project_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def _ref_node_id(ref: str) -> str:
    return f"artifact:{ref}"


def _event_dedupe_key(event: dict[str, Any]) -> str:
    return str(event.get("event_id") or uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(event, sort_keys=True)))


def _resolve_commit_id(nodes: dict[str, dict[str, Any]], sha: str) -> str:
    exact = f"commit:{sha}"
    if exact in nodes:
        return exact
    matches = [node_id for node_id, node in nodes.items() if node.get("type") == "commit" and str(node.get("sha", "")).startswith(sha)]
    if len(matches) == 1:
        return matches[0]
    return exact


def _decisions_for_artifact(
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    artifact_id: str | None,
) -> list[dict[str, Any]]:
    if not artifact_id:
        return []
    decisions: list[dict[str, Any]] = []
    for edge in edges:
        other = None
        if edge.get("from") == artifact_id:
            other = edge.get("to")
        elif edge.get("to") == artifact_id:
            other = edge.get("from")
        if not other:
            continue
        node = nodes.get(other, {})
        if node.get("type") == "decision" and node not in decisions:
            decisions.append(node)
    return decisions


def _sorted_session_nodes(project_root: Path) -> list[dict[str, Any]]:
    index = load_session_index(project_root)
    sessions = []
    for session_id, session in index.get("sessions", {}).items():
        timestamp = session.get("timestamp")
        parsed = _parse_timestamp(timestamp)
        if parsed is None:
            continue
        sessions.append(
            {
                "id": f"session:{session_id}",
                "session_id": session_id,
                "timestamp": timestamp,
                "parsed_timestamp": parsed,
                "transcript_path": session.get("transcript_path"),
            }
        )
    sessions.sort(key=lambda item: item["parsed_timestamp"])
    return sessions


def _nearest_session_for_commit(sessions: list[dict[str, Any]], authored_at: str | None) -> dict[str, Any] | None:
    authored = _parse_timestamp(authored_at)
    if authored is None:
        return None
    candidate: dict[str, Any] | None = None
    for session in sessions:
        delta = authored - session["parsed_timestamp"]
        if delta.total_seconds() < 0:
            continue
        if delta.total_seconds() > 86400:
            continue
        candidate = session
    return candidate


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None
