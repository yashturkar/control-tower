from __future__ import annotations

import argparse
import sys

from .config_ui import configure_project_interactively, should_prompt_for_init_ui
from .bootstrap import init_project
from .codex_cli import run_interactive
from .layout import find_project_root, tower_dir
from .project import load_agent_registry, load_project_config, load_runtime_state
from .prompts import build_tower_prompt
from .sessions import sync_and_capture_latest, update_git_branch


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="tower")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize .control-tower in the current repo")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing bootstrap files")
    init_parser.add_argument("--defaults", action="store_true", help="Skip the interactive init UI and keep default agent settings")

    start_parser = subparsers.add_parser("start", help="Start a Tower Codex session")
    _add_codex_options(start_parser)
    start_parser.add_argument("prompt", nargs="*", help="Optional initial Tower prompt")

    resume_parser = subparsers.add_parser("resume", help="Resume the last Tower Codex session")
    _add_codex_options(resume_parser)
    resume_parser.add_argument("prompt", nargs="*", help="Optional resume prompt")

    subparsers.add_parser("status", help="Show Control Tower project status")

    return parser.parse_args(argv)


def _add_codex_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", help="Optional Codex model override")
    parser.add_argument("--sandbox", default="workspace-write", help="Codex sandbox mode")
    parser.add_argument("--approval", default="on-request", help="Codex approval policy")
    parser.add_argument("--search", action="store_true", help="Enable Codex web search")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    project_root = find_project_root()

    if args.command == "init":
        init_project(project_root, force=args.force)
        if not args.defaults and should_prompt_for_init_ui():
            configure_project_interactively(project_root)
        update_git_branch(project_root)
        sync_and_capture_latest(project_root)
        print(f"Initialized Control Tower in {tower_dir(project_root)}")
        return 0

    if args.command == "status":
        return cmd_status(project_root)

    if args.command == "start":
        init_project(project_root, force=False)
        update_git_branch(project_root)
        sync_and_capture_latest(project_root)
        prompt = " ".join(args.prompt).strip() or None
        assembled = build_tower_prompt(project_root, prompt)
        exit_code = run_interactive(
            project_root,
            assembled,
            model=args.model,
            sandbox=args.sandbox,
            approval=args.approval,
            search=args.search,
        )
        sync_and_capture_latest(project_root, role="tower")
        return exit_code

    if args.command == "resume":
        init_project(project_root, force=False)
        update_git_branch(project_root)
        sync_and_capture_latest(project_root)
        runtime = load_runtime_state(project_root)
        prompt = " ".join(args.prompt).strip() or "Resume Tower control for this repository, reconcile memory, and continue the current workstream."
        assembled = build_tower_prompt(project_root, prompt)
        exit_code = run_interactive(
            project_root,
            assembled,
            resume=True,
            session_id=runtime.get("last_tower_session_id"),
            model=args.model,
            sandbox=args.sandbox,
            approval=args.approval,
            search=args.search,
        )
        sync_and_capture_latest(project_root, role="tower")
        return exit_code

    raise RuntimeError(f"Unhandled command: {args.command}")


def cmd_status(project_root: Path) -> int:
    base = tower_dir(project_root)
    if not base.exists():
        print("Control Tower is not initialized in this repository.")
        return 1

    config = load_project_config(project_root)
    registry = load_agent_registry(project_root)
    runtime = load_runtime_state(project_root)
    active_agents = [
        agent_config.get("name", agent_key)
        for agent_key, agent_config in registry.get("agents", {}).items()
        if agent_config.get("enabled")
    ]
    l0 = (base / "memory" / "l0.md").read_text().strip() if (base / "memory" / "l0.md").exists() else "No L0 snapshot"
    print(f"Project: {config.get('project_name', project_root.name)}")
    print(f"Root: {project_root}")
    print(f"Tower dir: {base}")
    print(f"Branch: {runtime.get('git_branch', 'unknown')}")
    print(f"Last Tower session: {runtime.get('last_tower_session_id', 'none')}")
    print(f"Last sync: {runtime.get('last_sync_time', 'never')}")
    print(f"Enabled agents: {', '.join(active_agents) if active_agents else 'none'}")
    print("")
    print("L0")
    print(l0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
