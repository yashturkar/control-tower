from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _base_args(
    project_root: Path,
    model: str | None,
    sandbox: str | None,
    approval: str | None,
    search: bool,
    dangerous: bool,
) -> list[str]:
    args = ["codex", "-C", str(project_root)]
    if model:
        args.extend(["-m", model])
    if dangerous:
        args.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        if sandbox:
            args.extend(["-s", sandbox])
        if approval:
            args.extend(["-a", approval])
    if search:
        args.append("--search")
    return args


def _codex_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("OTEL_SDK_DISABLED", "true")
    return env


def run_interactive(
    project_root: Path,
    prompt: str,
    resume: bool = False,
    session_id: str | None = None,
    model: str | None = None,
    sandbox: str | None = None,
    approval: str | None = None,
    search: bool = False,
    dangerous: bool = False,
) -> int:
    args = _base_args(project_root, model, sandbox, approval, search, dangerous)
    if resume:
        args.append("resume")
        if session_id:
            args.append(session_id)
        else:
            args.append("--last")
    args.append(prompt)
    result = subprocess.run(args, cwd=project_root, env=_codex_env())
    return result.returncode


def run_exec(
    project_root: Path,
    prompt: str,
    output_schema: Path,
    output_path: Path,
    model: str | None = None,
    sandbox: str | None = None,
    dangerous: bool = False,
) -> int:
    args = ["codex", "exec", "-C", str(project_root), "--output-schema", str(output_schema), "-o", str(output_path)]
    if model:
        args.extend(["-m", model])
    if dangerous:
        args.append("--dangerously-bypass-approvals-and-sandbox")
    elif sandbox:
        args.extend(["-s", sandbox])
    args.append(prompt)
    result = subprocess.run(args, cwd=project_root, env=_codex_env())
    return result.returncode
