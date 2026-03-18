from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .bootstrap import init_project
from .codex_cli import run_exec
from .layout import find_project_root, tower_dir
from .memory import import_project_sessions, mark_runtime_sync
from .packets import (
    create_task_packet,
    load_packet,
    new_scribe_memory_sync_packet,
    slugify,
    validate_result_packet,
    validate_task_packet,
)
from .project import load_agent_registry, load_project_config, load_runtime_state, write_json
from .prompts import build_subagent_prompt
from .sessions import sync_and_capture_latest, update_git_branch


DEFAULT_TASK_TYPES = {
    "builder": "implementation",
    "inspector": "review",
    "scout": "research",
    "git-master": "git-operations",
    "scribe": "documentation",
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="tower-run")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync-memory", help="Import Codex sessions into Beacon memory")
    sync_parser.add_argument("--emit-scribe-packet", action="store_true", help="Emit a Scribe task packet for curated memory/docs updates")

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
    create_parser.add_argument("--output", help="Path to write the TaskPacket JSON file")

    delegate_parser = subparsers.add_parser("delegate", help="Run a subagent through codex exec")
    delegate_parser.add_argument("agent", choices=["builder", "inspector", "scout", "git-master", "scribe"])
    delegate_parser.add_argument("--packet", required=True, help="Path to a TaskPacket JSON file")
    delegate_parser.add_argument("--output", help="Path for the ResultPacket JSON output")
    delegate_parser.add_argument("--model", help="Optional Codex model override")
    delegate_parser.add_argument("--sandbox", help="Codex sandbox mode for the subagent")
    delegate_parser.add_argument(
        "--search",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable Codex web search for the subagent",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    project_root = find_project_root()
    init_project(project_root, force=False)
    update_git_branch(project_root)

    if args.command == "sync-memory":
        return cmd_sync_memory(project_root, emit_scribe_packet=args.emit_scribe_packet)

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
            search=args.search,
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
    print(f"Imported {len(new_sessions)} session(s) into {tower_dir(project_root) / 'memory' / 'l2' / 'sessions'}")

    if emit_scribe_packet:
        runtime = load_runtime_state(project_root)
        project_id = load_project_config(project_root).get("project_name", project_root.name)
        session_id = runtime.get("last_tower_session_id") or runtime.get("last_imported_session_id") or "tower-sync"
        trace_id = str(uuid.uuid4())
        refs = [str(session.session_copy_path.relative_to(project_root)) for session in new_sessions]
        if not refs:
            refs = [".control-tower/memory/l1.md", ".control-tower/memory/l0.md"]
        packet = new_scribe_memory_sync_packet(project_id, session_id, trace_id, refs)
        packet_path = tower_dir(project_root) / "packets" / "outbox" / f"scribe-memory-sync-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        write_json(packet_path, packet)
        print(f"Created Scribe packet: {packet_path}")
    return 0


def cmd_delegate(
    project_root: Path,
    agent: str,
    packet_path: Path,
    output: Path | None,
    model: str | None,
    sandbox: str | None,
    search: bool | None,
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
    effective_sandbox = sandbox or agent_config.get("sandbox") or "workspace-write"
    effective_search = search if search is not None else bool(agent_config.get("search", False))
    exit_code = run_exec(
        project_root,
        prompt,
        output_schema=schema_path,
        output_path=output_path,
        model=effective_model,
        sandbox=effective_sandbox,
        search=effective_search,
    )
    if exit_code == 0:
        result_packet = load_packet(output_path)
        validate_result_packet(result_packet)
        sync_and_capture_latest(project_root, role=agent)
        print(str(output_path))
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


if __name__ == "__main__":
    raise SystemExit(main())
