from __future__ import annotations

import argparse
import json
import tempfile
import webbrowser
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .bootstrap import init_project
from .codex_cli import run_exec
from .docs_harness import docs_harness_context_refs
from .graph import (
    append_graph_events,
    create_decision_event,
    explain_commit,
    explain_decision,
    export_graph_json,
    filter_graph_payload,
    graph_status,
    neighborhood_view,
    sync_decision_graph,
)
from .layout import find_project_root, tower_dir
from .memory import import_project_sessions, mark_runtime_sync, refresh_memory_views
from .packets import (
    create_task_packet,
    load_packet,
    new_scribe_docs_followup_packet,
    new_scribe_memory_sync_packet,
    slugify,
    validate_result_packet,
    validate_task_packet,
)
from .project import load_agent_registry, load_graph_edges, load_graph_indexes, load_graph_nodes, load_project_config, load_runtime_state, write_json
from .prompts import build_subagent_prompt
from .sessions import sync_and_capture_latest, update_git_branch


DEFAULT_TASK_TYPES = {
    "builder": "implementation",
    "inspector": "review",
    "scout": "research",
    "git-master": "git-operations",
    "scribe": "documentation",
}


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="tower-run")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync-memory", help="Import Codex sessions into Beacon memory")
    sync_parser.add_argument("--emit-scribe-packet", action="store_true", help="Emit a Scribe task packet for curated memory/docs updates")

    log_decision_parser = subparsers.add_parser("log-decision", help="Create an explicit decision record in the decision graph")
    log_decision_parser.add_argument("--title", required=True, help="Decision title")
    log_decision_parser.add_argument("--topic", required=True, help="Stable decision topic slug or label")
    log_decision_parser.add_argument("--summary", required=True, help="One-line summary of the decision")
    log_decision_parser.add_argument("--rationale", action="append", default=[], help="Rationale line, repeatable")
    log_decision_parser.add_argument("--status", default="accepted", choices=["proposed", "accepted", "rejected", "superseded", "deprecated"])
    log_decision_parser.add_argument("--importance", default="major", choices=["minor", "normal", "major", "critical"])
    log_decision_parser.add_argument("--source-ref", action="append", default=[], help="Source reference path, repeatable")
    log_decision_parser.add_argument("--related-ref", action="append", default=[], help="Related artifact ref, repeatable")
    log_decision_parser.add_argument("--created-by", default="tower", help="Actor creating the decision")

    subparsers.add_parser("graph-status", help="Report current decision graph status")
    graph_search_parser = subparsers.add_parser("graph-search", help="List or search decision graph nodes and edges")
    graph_search_parser.add_argument("--query", help="Case-insensitive text filter across graph records")
    graph_search_parser.add_argument("--type", help="Filter nodes by type (for example: decision, commit, session)")
    graph_search_parser.add_argument("--include-edges", action="store_true", help="Include edge listings in output")
    graph_search_parser.add_argument("--limit", type=_positive_int, default=50, help="Maximum number of results to print per section")

    graph_view_parser = subparsers.add_parser("graph-view", help="View decision graph")
    graph_view_mode = graph_view_parser.add_mutually_exclusive_group(required=True)
    graph_view_mode.add_argument("--web", action="store_true", help="Open interactive graph view in browser")
    graph_view_mode.add_argument("--tui", action="store_true", help="Open terminal graph view")
    graph_view_parser.add_argument("--focus", help="Focus on a specific node id")
    graph_view_parser.add_argument("--radius", type=int, default=1, help="Neighborhood radius for focused view")
    graph_view_parser.add_argument("--query", help="Filter nodes by id/title/type/commit/session/task text")
    graph_view_parser.add_argument("--node-type", action="append", default=[], help="Filter to node type(s), repeatable")

    graph_export_parser = subparsers.add_parser("graph-export", help="Export decision graph")
    graph_export_parser.add_argument("--format", required=True, choices=["json", "dot", "svg"], help="Export format")
    graph_export_parser.add_argument("--output", help="Output file path. If omitted, writes to stdout")
    graph_export_parser.add_argument("--query", help="Filter nodes by id/title/type/commit/session/task text")
    graph_export_parser.add_argument("--node-type", action="append", default=[], help="Filter to node type(s), repeatable")

    explain_parser = subparsers.add_parser("explain", help="Explain graph provenance for a commit or decision")
    explain_target = explain_parser.add_mutually_exclusive_group(required=True)
    explain_target.add_argument("--commit", help="Commit SHA to explain")
    explain_target.add_argument("--decision", help="Decision id to explain")

    create_parser = subparsers.add_parser("create-packet", help="Create a TaskPacket for a subagent")
    create_parser.add_argument("agent", choices=["builder", "inspector", "scout", "git-master", "scribe"])
    create_parser.add_argument("--title", required=True, help="Short task title")
    create_parser.add_argument("--objective", required=True, help="Task objective")
    create_parser.add_argument("--task-type", help="Task type label")
    create_parser.add_argument("--priority", default="normal", choices=["low", "normal", "high", "critical"], help="Task priority")
    create_parser.add_argument("--instruction", action="append", default=[], help="Instruction line, repeatable")
    create_parser.add_argument("--constraint", action="append", default=[], help="Constraint line, repeatable")
    create_parser.add_argument("--file", action="append", default=[], help="Input file path, repeatable")
    create_parser.add_argument("--artifact", action="append", default=[], help="Input artifact ref, repeatable")
    create_parser.add_argument("--reference", action="append", default=[], help="Input reference ref, repeatable")
    create_parser.add_argument("--expected-output", action="append", default=[], help="Expected output, repeatable")
    create_parser.add_argument("--definition-of-done", action="append", default=[], help="Definition of done line, repeatable")
    create_parser.add_argument("--memory-ref", action="append", default=[], help="Memory context ref, repeatable")
    create_parser.add_argument("--doc-ref", action="append", default=[], help="Doc context ref, repeatable")
    create_parser.add_argument("--soft-seconds", type=int, default=900, help="Soft time budget in seconds")
    create_parser.add_argument("--hard-seconds", type=int, default=3600, help="Hard time budget in seconds")
    create_parser.add_argument("--requires-review", action=argparse.BooleanOptionalAction, default=True, help="Whether the task requires review")
    create_parser.add_argument("--allow-partial", action=argparse.BooleanOptionalAction, default=False, help="Whether partial completion is acceptable")
    create_parser.add_argument("--session-id", help="Session id to stamp onto the packet")
    create_parser.add_argument("--trace-id", help="Trace id to reuse across chained packets")
    create_parser.add_argument("--parent-packet-id", help="Parent packet id for chaining")
    create_parser.add_argument("--from-agent", default="tower", help="Source agent name")
    create_parser.add_argument("--from-result", help="Path to a ResultPacket JSON file to seed trace, parent, and artifacts")
    create_parser.add_argument(
        "--include-graph-context",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include relevant decision-graph context in packet metadata",
    )
    create_parser.add_argument("--output", help="Path to write the TaskPacket JSON file")

    delegate_parser = subparsers.add_parser("delegate", help="Run a subagent through codex exec")
    delegate_parser.add_argument("agent", choices=["builder", "inspector", "scout", "git-master", "scribe"])
    delegate_parser.add_argument("--packet", required=True, help="Path to a TaskPacket JSON file")
    delegate_parser.add_argument("--output", help="Path for the ResultPacket JSON output")
    delegate_parser.add_argument("--model", help="Optional Codex model override")
    delegate_parser.add_argument("--sandbox", help="Codex sandbox mode for the subagent")
    delegate_parser.add_argument(
        "--dangerous",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Run the subagent with --dangerously-bypass-approvals-and-sandbox",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    project_root = find_project_root()
    init_project(project_root, force=False)
    update_git_branch(project_root)

    if args.command == "sync-memory":
        return cmd_sync_memory(project_root, emit_scribe_packet=args.emit_scribe_packet)

    if args.command == "log-decision":
        return cmd_log_decision(project_root, args)

    if args.command == "graph-status":
        return cmd_graph_status(project_root)

    if args.command == "graph-view":
        return cmd_graph_view(project_root, args)

    if args.command == "graph-export":
        return cmd_graph_export(project_root, args)

    if args.command == "graph-search":
        return cmd_graph_search(project_root, args)

    if args.command == "explain":
        return cmd_explain(project_root, args)

    if args.command == "create-packet":
        return cmd_create_packet(project_root, args)

    if args.command == "delegate":
        return cmd_delegate(
            project_root,
            agent=args.agent,
            packet_path=Path(args.packet),
            output=Path(args.output).expanduser().resolve() if args.output else None,
            model=args.model,
            sandbox=args.sandbox,
            dangerous=args.dangerous,
        )

    raise RuntimeError(f"Unhandled command: {args.command}")


def cmd_create_packet(project_root: Path, args: argparse.Namespace) -> int:
    registry = load_agent_registry(project_root)
    agent_config = registry.get("agents", {}).get(args.agent)
    if not agent_config:
        raise SystemExit(f"Agent `{args.agent}` is not configured for this project.")
    if not agent_config.get("enabled"):
        raise SystemExit(f"Agent `{args.agent}` is disabled for this project.")

    runtime = load_runtime_state(project_root)
    project_id = load_project_config(project_root).get("project_name", project_root.name)
    session_id = args.session_id or runtime.get("last_tower_session_id") or runtime.get("last_imported_session_id") or "tower-session"

    seeded_files: list[str] = []
    seeded_artifacts: list[str] = []
    seeded_references: list[str] = []
    seeded_memory_refs: list[str] = []
    trace_id = args.trace_id
    parent_packet_id = args.parent_packet_id
    metadata: dict[str, object] = {}

    if args.from_result:
        result_path = Path(args.from_result).expanduser().resolve()
        result_ref = _project_ref(project_root, result_path)
        result_packet = load_packet(result_path)
        validate_result_packet(result_packet)
        trace_id = trace_id or result_packet.get("trace_id")
        parent_packet_id = parent_packet_id or result_packet.get("packet_id")
        seeded_files = list(result_packet.get("artifacts_changed", [])) + list(result_packet.get("artifacts_created", []))
        seeded_artifacts = list(result_packet.get("memory_worthy", []))
        seeded_references = [result_ref]
        seeded_memory_refs = [result_ref]
        metadata["seed_result_packet"] = result_ref
        metadata["seed_result_agent"] = result_packet.get("from_agent")
        metadata["seed_result_status"] = result_packet.get("status")

    files = _dedupe_strings(args.file + seeded_files)
    artifacts = _dedupe_strings(args.artifact + seeded_artifacts)
    references = _dedupe_strings(args.reference + seeded_references)
    memory_refs = _dedupe_strings(args.memory_ref + seeded_memory_refs)
    if args.include_graph_context:
        indexes = load_graph_indexes(project_root)
        nodes = load_graph_nodes(project_root).get("nodes", {})
        recent_result_packets = [
            node.get("id")
            for node in sorted(
                (
                    node
                    for node in nodes.values()
                    if node.get("type") == "packet" and node.get("packet_type") == "result"
                ),
                key=lambda node: str(node.get("created_at", "")),
                reverse=True,
            )
            if node.get("id")
        ][:3]
        metadata["graph_context"] = {
            "active_decisions": list(indexes.get("active_decisions", []))[:3],
            "open_questions": list(indexes.get("open_questions", []))[:3],
            "known_risks": list(indexes.get("known_risks", []))[:3],
            "current_tasks": list(indexes.get("current_tasks", []))[:3],
            "recent_result_packets": recent_result_packets,
            "unexplained_commits": list(indexes.get("unexplained_commits", []))[:3],
            "current_branch": indexes.get("current_branch", "unknown"),
        }
        metadata["graph_context_note"] = "Seeded from decision graph indexes/nodes at packet creation time."

    packet = create_task_packet(
        from_agent=args.from_agent,
        to_agent=args.agent,
        task_type=args.task_type or DEFAULT_TASK_TYPES[args.agent],
        priority=args.priority,
        project_id=project_id,
        session_id=session_id,
        title=args.title,
        objective=args.objective,
        instructions=args.instruction,
        constraints=args.constraint,
        files=files,
        artifacts=artifacts,
        references=references,
        expected_outputs=args.expected_output,
        definition_of_done=args.definition_of_done,
        memory_context_refs=memory_refs,
        doc_context_refs=args.doc_ref,
        soft_seconds=args.soft_seconds,
        hard_seconds=args.hard_seconds,
        requires_review=args.requires_review,
        allow_partial=args.allow_partial,
        metadata=metadata,
        trace_id=trace_id,
        parent_packet_id=parent_packet_id,
    )
    validate_task_packet(packet)
    output_path = Path(args.output).expanduser().resolve() if args.output else default_packet_output(project_root, args.agent, args.title)
    write_json(output_path, packet)
    print(str(output_path))
    return 0


def cmd_sync_memory(project_root: Path, emit_scribe_packet: bool) -> int:
    new_sessions = import_project_sessions(project_root)
    runtime_updates = {"last_sync_time": _iso_now()}
    if new_sessions:
        runtime_updates["last_imported_session_id"] = new_sessions[-1].session_id
    mark_runtime_sync(project_root, **runtime_updates)
    graph_state = sync_decision_graph(project_root)
    print(f"Imported {len(new_sessions)} session(s) into {tower_dir(project_root) / 'memory' / 'l2' / 'sessions'}")
    print(f"Graph nodes: {len(graph_state.get('nodes', {}))}")

    if emit_scribe_packet:
        runtime = load_runtime_state(project_root)
        project_id = load_project_config(project_root).get("project_name", project_root.name)
        session_id = runtime.get("last_tower_session_id") or runtime.get("last_imported_session_id") or "tower-sync"
        trace_id = str(uuid.uuid4())
        refs = [str(session.session_copy_path.relative_to(project_root)) for session in new_sessions]
        if not refs:
            refs = [
                ".control-tower/memory/l1.md",
                ".control-tower/memory/l0.md",
                ".control-tower/state/decision-graph/indexes.json",
                ".control-tower/docs/state/decisions.md",
            ]
        packet = new_scribe_memory_sync_packet(project_id, session_id, trace_id, refs)
        packet_path = tower_dir(project_root) / "packets" / "outbox" / f"scribe-memory-sync-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        write_json(packet_path, packet)
        print(f"Created Scribe packet: {packet_path}")
    return 0


def cmd_log_decision(project_root: Path, args: argparse.Namespace) -> int:
    source_refs = _dedupe_strings(args.source_ref)
    related_refs = _dedupe_strings(args.related_ref + source_refs)
    events = create_decision_event(
        topic=args.topic,
        title=args.title,
        summary=args.summary,
        rationale=args.rationale or ["No rationale provided."],
        status=args.status,
        importance=args.importance,
        source_refs=source_refs,
        created_by=args.created_by,
        inferred=False,
        related_refs=related_refs,
    )
    append_graph_events(project_root, events)
    sync_decision_graph(project_root)
    refresh_memory_views(project_root)
    print(events[0]["payload"]["id"])
    return 0


def cmd_graph_status(project_root: Path) -> int:
    sync_decision_graph(project_root)
    status = graph_status(project_root)
    print(f"Active decisions: {status['active_decisions']}")
    print(f"Inferred decisions: {status['inferred_decisions']}")
    print(f"Unexplained commits: {status['unexplained_commits']}")
    print(f"Open questions: {status['open_questions']}")
    print(f"Known risks: {status['known_risks']}")
    print(f"Nodes: {status['nodes']}")
    print(f"Edges: {status['edges']}")
    print(f"Last graph sync: {status['last_graph_sync']}")
    return 0


def cmd_graph_export(project_root: Path, args: argparse.Namespace) -> int:
    sync_decision_graph(project_root)
    query = getattr(args, "query", None)
    node_types = getattr(args, "node_type", [])
    graph_payload = export_graph_json(project_root)
    graph_payload = filter_graph_payload(graph_payload, query=query, node_types=node_types)
    if args.format == "json":
        payload = json.dumps(graph_payload, indent=2) + "\n"
    elif args.format == "dot":
        payload = _graph_payload_to_dot(graph_payload)
    elif args.format == "svg":
        payload = _graph_payload_to_svg(graph_payload)
    else:
        raise SystemExit(f"Unsupported graph export format: {args.format}")
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload)
        print(str(output_path))
    else:
        print(payload, end="")
    return 0


def cmd_graph_view(project_root: Path, args: argparse.Namespace) -> int:
    sync_decision_graph(project_root)
    query = getattr(args, "query", None)
    node_types = getattr(args, "node_type", [])
    if args.web:
        with tempfile.NamedTemporaryFile("w", delete=False, prefix="tower-graph-view-", suffix=".html") as output_file:
            output_file.write(
                _build_graph_view_html(
                    project_root,
                    focus=args.focus,
                    radius=args.radius,
                    query=query,
                    node_types=node_types,
                )
            )
            output_path = Path(output_file.name)
        webbrowser.open(output_path.as_uri())
        print(str(output_path))
        return 0
    return _print_tui_graph_view(
        project_root,
        focus=args.focus,
        radius=args.radius,
        query=query,
        node_types=node_types,
    )

def cmd_graph_search(project_root: Path, args: argparse.Namespace) -> int:
    sync_decision_graph(project_root)
    all_nodes = list(load_graph_nodes(project_root).get("nodes", {}).values())
    all_edges = list(load_graph_edges(project_root).get("edges", []))
    limit = args.limit
    query = (args.query or "").strip().lower()
    node_type = (args.type or "").strip().lower()

    nodes = all_nodes
    if node_type:
        nodes = [node for node in nodes if str(node.get("type", "")).lower() == node_type]
    if query:
        nodes = [node for node in nodes if query in json.dumps(node, sort_keys=True).lower()]

    print(f"Nodes ({len(nodes)}):")
    for node in nodes[:limit]:
        label = _node_display_label(node)
        print(f"- {node.get('id')} [{node.get('type')}] {label}")
    if len(nodes) > limit:
        print(f"... {len(nodes) - limit} more node(s)")

    if args.include_edges:
        edges = all_edges
        if query:
            edges = [edge for edge in edges if query in json.dumps(edge, sort_keys=True).lower()]
        print(f"Edges ({len(edges)}):")
        for edge in edges[:limit]:
            print(f"- {edge.get('id')} [{edge.get('type')}] {edge.get('from')} -> {edge.get('to')}")
        if len(edges) > limit:
            print(f"... {len(edges) - limit} more edge(s)")
    return 0


def _node_display_label(node: dict[str, object]) -> str:
    label = node.get("title") or node.get("subject") or node.get("summary") or node.get("ref") or node.get("id")
    return str(label) if label is not None else ""


def cmd_explain(project_root: Path, args: argparse.Namespace) -> int:
    sync_decision_graph(project_root)
    if args.commit:
        explanation = explain_commit(project_root, args.commit)
        commit = explanation.get("commit")
        if not commit:
            raise SystemExit(f"Commit `{args.commit}` was not found in the decision graph.")
        print(f"Commit: {commit.get('sha')} {commit.get('subject')}")
        linked_decisions = explanation.get("linked_decisions", [])
        if linked_decisions:
            print("Linked decisions:")
            for decision in linked_decisions:
                print(f"- {decision.get('id')}: {decision.get('title')}")
        else:
            print("Linked decisions: none")
        linked_sessions = explanation.get("linked_sessions", [])
        if linked_sessions:
            print("Linked sessions:")
            for session in linked_sessions:
                print(f"- {session.get('session_id')}")
        else:
            print("Linked sessions: none")
        return 0

    explanation = explain_decision(project_root, args.decision)
    decision = explanation.get("decision")
    if not decision:
        raise SystemExit(f"Decision `{args.decision}` was not found in the decision graph.")
    print(f"Decision: {decision.get('id')} {decision.get('title')}")
    print(f"Status: {decision.get('status')}")
    print(f"Summary: {decision.get('summary')}")
    related_nodes = explanation.get("related_nodes", [])
    if related_nodes:
        print("Related nodes:")
        for node in related_nodes:
            label = node.get("title") or node.get("subject") or node.get("id")
            print(f"- {node.get('type')}: {label}")
    else:
        print("Related nodes: none")
    return 0


def cmd_delegate(
    project_root: Path,
    agent: str,
    packet_path: Path,
    output: Path | None,
    model: str | None,
    sandbox: str | None,
    dangerous: bool | None = None,
) -> int:
    resolved_packet_path = packet_path.expanduser().resolve()
    packet = load_packet(resolved_packet_path)
    validate_task_packet(packet)
    if packet.get("to_agent") != agent:
        raise SystemExit(
            f"Packet target `{packet.get('to_agent')}` does not match requested delegate agent `{agent}`."
        )
    registry = load_agent_registry(project_root)
    agent_config = registry.get("agents", {}).get(agent)
    if not agent_config:
        raise SystemExit(f"Agent `{agent}` is not configured for this project.")
    if not agent_config.get("enabled"):
        raise SystemExit(f"Agent `{agent}` is disabled for this project.")
    output_path = output if output else default_delegate_output(project_root, agent, packet)
    prompt = build_subagent_prompt(project_root, agent, json.dumps(packet, indent=2))
    schema_path = tower_dir(project_root) / "schemas" / "packets" / "result.schema.json"
    effective_model = model or agent_config.get("model")
    effective_dangerous = dangerous if dangerous is not None else bool(agent_config.get("dangerously_bypass", False))
    effective_sandbox = None if effective_dangerous else (sandbox or agent_config.get("sandbox") or "workspace-write")
    exit_code = run_exec(
        project_root,
        prompt,
        output_schema=schema_path,
        output_path=output_path,
        model=effective_model,
        sandbox=effective_sandbox,
        dangerous=effective_dangerous,
    )
    if exit_code == 0:
        try:
            result_packet = load_packet(output_path)
            validate_result_packet(result_packet)
        except Exception as exc:
            raise SystemExit(
                "codex exec did not produce a valid ResultPacket. "
                f"Expected JSON at `{output_path}` but got an invalid or empty file. "
                "This usually means the Codex subprocess failed before writing its final message."
            ) from exc
        sync_and_capture_latest(project_root, role=agent)
        follow_up_path = maybe_emit_scribe_docs_followup(project_root, agent, result_packet, output_path)
        print(str(output_path))
        if follow_up_path is not None:
            print(f"Created Scribe docs packet: {follow_up_path}")
    return exit_code


def default_delegate_output(project_root: Path, agent: str, packet: dict[str, object]) -> Path:
    packet_id = str(packet.get("packet_id", "result"))
    return tower_dir(project_root) / "packets" / "inbox" / f"{agent}-{packet_id}-result.json"


def default_packet_output(project_root: Path, agent: str, title: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = slugify(title)
    return tower_dir(project_root) / "packets" / "outbox" / f"{timestamp}-{agent}-{slug}.json"


def _dedupe_strings(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            ordered.append(value)
            seen.add(value)
    return ordered


def _project_ref(project_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _print_tui_graph_view(
    project_root: Path,
    focus: str | None,
    radius: int,
    query: str | None,
    node_types: list[str],
) -> int:
    graph = filter_graph_payload(export_graph_json(project_root), query=query, node_types=node_types)
    nodes = graph["nodes"]
    edges = graph["edges"]
    print("Decision graph (TUI)")
    print(f"Nodes: {len(nodes)}")
    print(f"Edges: {len(edges)}")
    if not focus:
        print("Use --focus <node-id> to inspect a local neighborhood.")
        type_counts: dict[str, int] = {}
        for node in nodes:
            node_type = str(node.get("type") or "unknown")
            type_counts[node_type] = type_counts.get(node_type, 0) + 1
        print("Node types:")
        for node_type, count in sorted(type_counts.items()):
            print(f"- {node_type}: {count}")
        return 0
    neighborhood = neighborhood_view(project_root, center_id=focus, radius=radius)
    neighborhood = filter_graph_payload(neighborhood, query=query, node_types=node_types)
    center = neighborhood.get("center")
    if not center:
        raise SystemExit(f"Node `{focus}` was not found in the decision graph.")
    print(f"Focus: {center.get('id')} ({center.get('type')})")
    print(f"Radius: {radius}")
    print("Neighborhood nodes:")
    for node in neighborhood.get("nodes", []):
        label = node.get("title") or node.get("subject") or node.get("id")
        print(f"- {node.get('id')} [{node.get('type')}] {label}")
    print("Neighborhood edges:")
    for edge in neighborhood.get("edges", []):
        print(f"- {edge.get('from')} -[{edge.get('type')}]-> {edge.get('to')}")
    return 0


def _build_graph_view_html(
    project_root: Path,
    focus: str | None,
    radius: int,
    query: str | None,
    node_types: list[str],
) -> str:
    graph = filter_graph_payload(export_graph_json(project_root), query=query, node_types=node_types)
    if focus:
        neighborhood = neighborhood_view(project_root, center_id=focus, radius=radius)
        if neighborhood.get("center"):
            graph = filter_graph_payload(
                {"nodes": neighborhood["nodes"], "edges": neighborhood["edges"]},
                query=query,
                node_types=node_types,
            )
    data_json = json.dumps(graph)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Control Tower Decision Graph</title>
  <style>
    body {{ margin: 0; font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; }}
    .toolbar {{ padding: 12px 16px; border-bottom: 1px solid #334155; display: flex; gap: 12px; align-items: center; }}
    #search {{ min-width: 260px; padding: 6px 10px; border-radius: 6px; border: 1px solid #475569; background: #0b1222; color: #e2e8f0; }}
    #graph {{ width: 100vw; height: calc(100vh - 58px); display: block; }}
    .meta {{ font-size: 12px; color: #93c5fd; }}
  </style>
</head>
<body>
  <div class="toolbar">
    <strong>Decision Graph</strong>
    <input id="search" placeholder="Search node id/title/type..." />
    <span class="meta">Drag nodes • Scroll to zoom • Click node to inspect</span>
    <span class="meta" id="counts"></span>
  </div>
  <svg id="graph"></svg>
  <script>
    const data = {data_json};
    const svg = document.getElementById("graph");
    const counts = document.getElementById("counts");
    const NS = "http://www.w3.org/2000/svg";
    const nodes = data.nodes || [];
    const edges = data.edges || [];
    counts.textContent = `nodes: ${{nodes.length}} - edges: ${{edges.length}}`;
    const nodeMap = new Map(nodes.map((n) => [n.id, n]));
    const width = window.innerWidth;
    const height = window.innerHeight - 58;
    svg.setAttribute("viewBox", `0 0 ${{width}} ${{height}}`);
    const g = document.createElementNS(NS, "g");
    svg.appendChild(g);
    const edgeLayer = document.createElementNS(NS, "g");
    const nodeLayer = document.createElementNS(NS, "g");
    g.appendChild(edgeLayer);
    g.appendChild(nodeLayer);

    nodes.forEach((node, i) => {{
      node.x = width / 2 + Math.cos((2 * Math.PI * i) / Math.max(nodes.length, 1)) * Math.min(width, height) * 0.3;
      node.y = height / 2 + Math.sin((2 * Math.PI * i) / Math.max(nodes.length, 1)) * Math.min(width, height) * 0.3;
      node.vx = 0;
      node.vy = 0;
    }});

    function linkEndpoints(edge) {{
      const from = nodeMap.get(edge.from);
      const to = nodeMap.get(edge.to);
      return from && to ? [from, to] : null;
    }}

    function render() {{
      edgeLayer.innerHTML = "";
      nodeLayer.innerHTML = "";
      edges.forEach((edge) => {{
        const pts = linkEndpoints(edge);
        if (!pts) return;
        const [a, b] = pts;
        const line = document.createElementNS(NS, "line");
        line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
        line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
        line.setAttribute("stroke", "#334155");
        line.setAttribute("stroke-width", "1.4");
        edgeLayer.appendChild(line);
      }});
      nodes.forEach((node) => {{
        const circle = document.createElementNS(NS, "circle");
        circle.setAttribute("cx", node.x); circle.setAttribute("cy", node.y);
        circle.setAttribute("r", "7");
        circle.setAttribute("fill", "#60a5fa");
        circle.setAttribute("data-node-id", node.id);
        circle.style.cursor = "pointer";
        nodeLayer.appendChild(circle);

        const label = document.createElementNS(NS, "text");
        label.setAttribute("x", node.x + 10); label.setAttribute("y", node.y + 4);
        label.setAttribute("fill", "#e2e8f0");
        label.setAttribute("font-size", "11");
        label.textContent = (node.title || node.subject || node.id);
        nodeLayer.appendChild(label);

        circle.addEventListener("click", () => {{
          counts.textContent = `selected: ${{node.id}} (${{node.type || "unknown"}}) - nodes: ${{nodes.length}} - edges: ${{edges.length}}`;
        }});
        dragNode(circle, node);
      }});
    }}

    function tick() {{
      for (const a of nodes) {{
        for (const b of nodes) {{
          if (a === b) continue;
          const dx = a.x - b.x, dy = a.y - b.y;
          const d2 = Math.max(dx * dx + dy * dy, 1);
          const repulse = 2200 / d2;
          a.vx += (dx / Math.sqrt(d2)) * repulse;
          a.vy += (dy / Math.sqrt(d2)) * repulse;
        }}
      }}
      for (const edge of edges) {{
        const pts = linkEndpoints(edge);
        if (!pts) continue;
        const [a, b] = pts;
        const dx = b.x - a.x, dy = b.y - a.y;
        const dist = Math.max(Math.hypot(dx, dy), 1);
        const target = 120;
        const spring = (dist - target) * 0.0025;
        const ux = dx / dist, uy = dy / dist;
        a.vx += spring * ux; a.vy += spring * uy;
        b.vx -= spring * ux; b.vy -= spring * uy;
      }}
      for (const node of nodes) {{
        node.vx *= 0.88; node.vy *= 0.88;
        node.x = Math.min(width - 10, Math.max(10, node.x + node.vx));
        node.y = Math.min(height - 10, Math.max(10, node.y + node.vy));
      }}
      render();
      requestAnimationFrame(tick);
    }}

    function dragNode(el, node) {{
      let dragging = false;
      el.addEventListener("pointerdown", () => {{ dragging = true; }});
      window.addEventListener("pointerup", () => {{ dragging = false; }});
      window.addEventListener("pointermove", (e) => {{
        if (!dragging) return;
        const pt = svg.createSVGPoint();
        pt.x = e.clientX; pt.y = e.clientY;
        const ctm = g.getScreenCTM();
        if (!ctm) return;
        const local = pt.matrixTransform(ctm.inverse());
        node.x = local.x; node.y = local.y;
      }});
    }}

    let scale = 1, tx = 0, ty = 0, panning = false, panStart = null;
    function applyTransform() {{ g.setAttribute("transform", `translate(${{tx}},${{ty}}) scale(${{scale}})`); }}
    svg.addEventListener("wheel", (e) => {{
      e.preventDefault();
      const delta = e.deltaY < 0 ? 1.1 : 0.9;
      scale = Math.max(0.2, Math.min(3, scale * delta));
      applyTransform();
    }}, {{ passive: false }});
    svg.addEventListener("pointerdown", (e) => {{ if (e.target === svg) {{ panning = true; panStart = [e.clientX - tx, e.clientY - ty]; }} }});
    window.addEventListener("pointerup", () => {{ panning = false; }});
    window.addEventListener("pointermove", (e) => {{
      if (!panning || !panStart) return;
      tx = e.clientX - panStart[0];
      ty = e.clientY - panStart[1];
      applyTransform();
    }});
    document.getElementById("search").addEventListener("input", (e) => {{
      const q = e.target.value.toLowerCase().trim();
      for (const el of nodeLayer.querySelectorAll("circle")) {{
        const id = el.getAttribute("data-node-id");
        const node = nodeMap.get(id);
        const text = `${{node?.id || ""}} ${{node?.title || ""}} ${{node?.subject || ""}} ${{node?.type || ""}}`.toLowerCase();
        el.setAttribute("fill", q && text.includes(q) ? "#f59e0b" : "#60a5fa");
      }}
    }});
    applyTransform();
    tick();
  </script>
</body>
</html>
"""


def _graph_payload_to_dot(payload: dict[str, object]) -> str:
    nodes = payload.get("nodes", [])
    edges = payload.get("edges", [])
    lines = ["digraph decision_graph {", "  rankdir=LR;"]
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id", ""))
        if not node_id:
            continue
        label = str(node.get("title") or node.get("subject") or node_id).replace('"', '\\"')
        node_type = str(node.get("type") or "node").replace('"', '\\"')
        lines.append(f'  "{node_id}" [label="{label}\\n({node_type})"];')
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        from_id = edge.get("from")
        to_id = edge.get("to")
        if not from_id or not to_id:
            continue
        edge_type = str(edge.get("type") or "edge").replace('"', '\\"')
        lines.append(f'  "{from_id}" -> "{to_id}" [label="{edge_type}"];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def _graph_payload_to_svg(payload: dict[str, object]) -> str:
    import math

    nodes = sorted([node for node in payload.get("nodes", []) if isinstance(node, dict)], key=lambda node: str(node.get("id", "")))
    edges = [edge for edge in payload.get("edges", []) if isinstance(edge, dict)]
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


def maybe_emit_scribe_docs_followup(
    project_root: Path,
    agent: str,
    result_packet: dict[str, object],
    result_path: Path,
) -> Path | None:
    config = load_project_config(project_root)
    docs_harness = config.get("docs_harness", {}) if isinstance(config, dict) else {}
    if not docs_harness.get("enabled"):
        return None
    if docs_harness.get("auto_scribe_mode") != "after-most-work":
        return None
    if agent not in docs_harness.get("auto_scribe_agents", []):
        return None
    if result_packet.get("status") != "success":
        return None

    changed_files = _dedupe_strings(
        list(result_packet.get("artifacts_changed", [])) + list(result_packet.get("artifacts_created", []))
    )
    result_ref = _project_ref(project_root, result_path)
    runtime = load_runtime_state(project_root)
    project_id = config.get("project_name", project_root.name)
    session_id = runtime.get("last_tower_session_id") or runtime.get("last_imported_session_id") or "tower-session"
    packet = new_scribe_docs_followup_packet(
        project_id,
        session_id,
        str(result_packet.get("trace_id") or uuid.uuid4()),
        agent,
        result_ref,
        changed_files,
        docs_harness_context_refs(project_root, docs_harness),
    )
    validate_task_packet(packet)
    packet_path = (
        tower_dir(project_root)
        / "packets"
        / "outbox"
        / f"scribe-docs-followup-{agent}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_json(packet_path, packet)
    return packet_path


if __name__ == "__main__":
    raise SystemExit(main())
