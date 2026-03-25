from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import __version__
from .backends import VALID_BACKENDS, run_interactive
from .config_ui import configure_project_interactively, should_prompt_for_init_ui
from .bootstrap import init_project
from .docs_harness import ensure_docs_harness
from .layout import find_project_root, tower_dir
from .memory import mark_runtime_sync
from .project import load_agent_registry, load_project_config, load_runtime_state
from .prompts import build_tower_prompt
from .sessions import find_latest_session_id_for_project, sync_and_capture_latest, update_git_branch


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="tower")
    parser.add_argument("-v", "--version", action="store_true", help="Show installed Tower version and source information")
    subparsers = parser.add_subparsers(dest="command")

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
    subparsers.add_parser("update", help="Update the installed Tower CLI and refresh this repo's .control-tower runtime")

    args = parser.parse_args(argv)
    if not args.version and not args.command:
        parser.error("the following arguments are required: command")
    return args


def _add_codex_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", help="Optional model override")
    parser.add_argument("--sandbox", help="Sandbox mode")
    parser.add_argument("--approval", help="Approval policy")
    parser.add_argument("--backend", choices=list(VALID_BACKENDS), help="Execution backend (codex, gemini, cursor)")
    parser.add_argument(
        "--search",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable web search",
    )
    parser.add_argument(
        "--dangerous",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Run Tower with --dangerously-bypass-approvals-and-sandbox",
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.version:
        return cmd_version()
    project_root = find_project_root()

    if args.command == "init":
        init_project(project_root, force=args.force)
        if not args.defaults and should_prompt_for_init_ui():
            configure_project_interactively(project_root)
        elif args.defaults:
            project_state = tower_dir(project_root) / "state" / "project.json"
            config = load_project_config(project_root)
            config["docs_harness"] = ensure_docs_harness(
                project_root,
                config.get("docs_harness", {}),
                scaffold_missing=True,
            )
            project_state.write_text(json.dumps(config, indent=2) + "\n")
        update_git_branch(project_root)
        sync_and_capture_latest(project_root)
        print(f"Initialized Control Tower in {tower_dir(project_root)}")
        return 0

    if args.command == "status":
        return cmd_status(project_root)

    if args.command == "update":
        return cmd_update(project_root)

    if args.command == "start":
        init_project(project_root, force=False)
        update_git_branch(project_root)
        sync_and_capture_latest(project_root)
        config = load_project_config(project_root)
        codex_options = resolve_codex_options(config, args)
        prompt = " ".join(args.prompt).strip() or None
        assembled = build_tower_prompt(project_root, prompt)
        try:
            return run_interactive(
                project_root,
                assembled,
                backend=codex_options["backend"],
                model=codex_options["model"],
                sandbox=codex_options["sandbox"],
                approval=codex_options["approval"],
                search=codex_options["search"],
                dangerous=codex_options["dangerous"],
            )
        finally:
            sync_and_capture_latest(project_root, role="tower")

    if args.command == "resume":
        init_project(project_root, force=False)
        update_git_branch(project_root)
        sync_and_capture_latest(project_root)
        config = load_project_config(project_root)
        codex_options = resolve_codex_options(config, args)
        runtime = load_runtime_state(project_root)
        session_id = runtime.get("last_tower_session_id") or find_latest_session_id_for_project(project_root)
        if session_id:
            mark_runtime_sync(project_root, last_tower_session_id=session_id)
        resume_prompt = " ".join(args.prompt).strip() or None
        try:
            return run_interactive(
                project_root,
                resume_prompt,
                backend=codex_options["backend"],
                resume=True,
                session_id=session_id,
                model=codex_options["model"],
                sandbox=codex_options["sandbox"],
                approval=codex_options["approval"],
                search=codex_options["search"],
                dangerous=codex_options["dangerous"],
            )
        finally:
            sync_and_capture_latest(project_root, role="tower")

    raise RuntimeError(f"Unhandled command: {args.command}")


def cmd_status(project_root: Path) -> int:
    base = tower_dir(project_root)
    if not base.exists():
        print("Control Tower is not initialized in this repository.")
        return 1

    config = load_project_config(project_root)
    registry = load_agent_registry(project_root)
    runtime = load_runtime_state(project_root)
    codex_defaults = config.get("codex_defaults", {})
    active_agents = []
    custom_agents = []
    for agent_key, agent_config in registry.get("agents", {}).items():
        if agent_config.get("enabled"):
            name = agent_config.get("name", agent_key)
            backend = agent_config.get("backend", "codex")
            label = f"{name} ({backend})" if backend != "codex" else name
            active_agents.append(label)
            if agent_config.get("custom"):
                custom_agents.append(name)
    l0 = (base / "memory" / "l0.md").read_text().strip() if (base / "memory" / "l0.md").exists() else "No L0 snapshot"
    print(f"Project: {config.get('project_name', project_root.name)}")
    print(f"Root: {project_root}")
    print(f"Tower dir: {base}")
    print(f"Branch: {runtime.get('git_branch', 'unknown')}")
    print(f"Last Tower session: {runtime.get('last_tower_session_id', 'none')}")
    print(f"Last sync: {runtime.get('last_sync_time', 'never')}")
    print(f"Enabled agents: {', '.join(active_agents) if active_agents else 'none'}")
    if custom_agents:
        print(f"Custom agents: {', '.join(custom_agents)}")
    print(f"Default backend: {codex_defaults.get('backend', 'codex')}")
    print(f"Tower dangerous mode: {codex_defaults.get('dangerously_bypass', False)}")
    docs_harness = config.get("docs_harness", {}) if isinstance(config, dict) else {}
    print(f"Docs harness: {'enabled' if docs_harness.get('enabled') else 'disabled'}")
    if docs_harness.get("enabled"):
        print(f"Docs mode: {docs_harness.get('mode', 'unknown')}")
        print(f"Docs roots: {', '.join(docs_harness.get('doc_roots', [])) or 'none'}")
        print(f"Auto Scribe docs: {docs_harness.get('auto_scribe_mode', 'disabled')}")
    print("")
    print("L0")
    print(l0)
    return 0


def cmd_version() -> int:
    source_root = _source_repo_root().resolve()
    git_commit = _git_output(source_root, ["rev-parse", "--short", "HEAD"])
    display_version = __version__
    if git_commit:
        display_version = f"{display_version}+g{git_commit}"

    print(f"tower {display_version}")
    print(f"source: {source_root}")
    if git_commit:
        print(f"commit: {git_commit}")
    git_branch = _git_output(source_root, ["rev-parse", "--abbrev-ref", "HEAD"])
    if git_branch:
        print(f"branch: {git_branch}")
    managed_repo = _managed_install_repo_root().resolve()
    print(f"managed install repo: {managed_repo}")
    print(f"managed install active: {source_root == managed_repo}")
    return 0


def cmd_update(project_root: Path) -> int:
    source_repo_root = _source_repo_root()
    updated_source_root = _update_installed_control_tower(source_repo_root)
    init_project(project_root, force=False)
    update_git_branch(project_root)
    sync_and_capture_latest(project_root)
    print(f"Updated Tower installation from {updated_source_root}")
    print(f"Refreshed Control Tower runtime in {tower_dir(project_root)}")
    return 0


def resolve_codex_options(config: dict[str, object], args: argparse.Namespace) -> dict[str, object]:
    defaults = config.get("codex_defaults", {}) if isinstance(config, dict) else {}
    backend_arg = getattr(args, "backend", None)
    return {
        "model": args.model,
        "sandbox": args.sandbox if args.sandbox is not None else defaults.get("sandbox", "workspace-write"),
        "approval": args.approval if args.approval is not None else defaults.get("approval", "on-request"),
        "search": args.search if args.search is not None else bool(defaults.get("search", False)),
        "dangerous": args.dangerous if args.dangerous is not None else bool(defaults.get("dangerously_bypass", True)),
        "backend": backend_arg if backend_arg is not None else str(defaults.get("backend", "codex")),
    }


def _source_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _managed_install_repo_root() -> Path:
    install_base = Path(
        os.environ.get("CONTROL_TOWER_INSTALL_ROOT")
        or os.environ.get("XDG_DATA_HOME")
        or (Path.home() / ".local" / "share")
    )
    if install_base.name != "control-tower":
        install_base = install_base / "control-tower"
    return install_base / "repo"


def _update_installed_control_tower(source_repo_root: Path) -> Path:
    source_repo_root = source_repo_root.resolve()
    managed_repo_root = _managed_install_repo_root().resolve()

    if source_repo_root == managed_repo_root:
        bootstrap_script = source_repo_root / "scripts" / "bootstrap_remote_install.sh"
        subprocess.run([str(bootstrap_script)], cwd=source_repo_root, check=True)
        return managed_repo_root

    install_script = source_repo_root / "scripts" / "install_tower.sh"
    if (source_repo_root / ".git").exists():
        subprocess.run(["git", "pull", "--ff-only"], cwd=source_repo_root, check=True)
    subprocess.run([str(install_script)], cwd=source_repo_root, check=True)
    return source_repo_root


def _git_output(repo_root: Path, args: list[str]) -> str | None:
    if not (repo_root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    value = result.stdout.strip()
    return value or None


if __name__ == "__main__":
    raise SystemExit(main())
