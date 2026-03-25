from __future__ import annotations

import os
import subprocess
from pathlib import Path

VALID_BACKENDS = ("codex", "gemini", "cursor")

DEFAULT_BACKEND = "codex"


def _common_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("OTEL_SDK_DISABLED", "true")
    return env


# ---------------------------------------------------------------------------
# Codex
# ---------------------------------------------------------------------------

def _codex_base_args(
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


def _codex_interactive(
    project_root: Path,
    prompt: str | None,
    resume: bool = False,
    session_id: str | None = None,
    model: str | None = None,
    sandbox: str | None = None,
    approval: str | None = None,
    search: bool = False,
    dangerous: bool = False,
) -> int:
    args = _codex_base_args(project_root, model, sandbox, approval, search, dangerous)
    if resume:
        args.append("resume")
        if session_id:
            args.append(session_id)
        else:
            args.append("--last")
    if prompt:
        args.append(prompt)
    result = subprocess.run(args, cwd=project_root, env=_common_env())
    return result.returncode


def _codex_exec(
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
    result = subprocess.run(args, cwd=project_root, env=_common_env())
    return result.returncode


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def _gemini_interactive(
    project_root: Path,
    prompt: str | None,
    model: str | None = None,
    sandbox: str | None = None,
    **_kwargs: object,
) -> int:
    args = ["gemini"]
    if model:
        args.extend(["--model", model])
    if sandbox:
        args.extend(["--sandbox", sandbox])
    if prompt:
        args.append(prompt)
    result = subprocess.run(args, cwd=project_root, env=_common_env())
    return result.returncode


def _gemini_exec(
    project_root: Path,
    prompt: str,
    output_schema: Path,
    output_path: Path,
    model: str | None = None,
    sandbox: str | None = None,
    **_kwargs: object,
) -> int:
    args = ["gemini", "exec", "--output-schema", str(output_schema), "-o", str(output_path)]
    if model:
        args.extend(["--model", model])
    if sandbox:
        args.extend(["--sandbox", sandbox])
    args.append(prompt)
    result = subprocess.run(args, cwd=project_root, env=_common_env())
    return result.returncode


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------

def _cursor_interactive(
    project_root: Path,
    prompt: str | None,
    model: str | None = None,
    sandbox: str | None = None,
    **_kwargs: object,
) -> int:
    args = ["cursor", "--headless"]
    if model:
        args.extend(["--model", model])
    if sandbox:
        args.extend(["--sandbox", sandbox])
    if prompt:
        args.append(prompt)
    result = subprocess.run(args, cwd=project_root, env=_common_env())
    return result.returncode


def _cursor_exec(
    project_root: Path,
    prompt: str,
    output_schema: Path,
    output_path: Path,
    model: str | None = None,
    sandbox: str | None = None,
    **_kwargs: object,
) -> int:
    args = ["cursor", "--headless", "exec", "--output-schema", str(output_schema), "-o", str(output_path)]
    if model:
        args.extend(["--model", model])
    if sandbox:
        args.extend(["--sandbox", sandbox])
    args.append(prompt)
    result = subprocess.run(args, cwd=project_root, env=_common_env())
    return result.returncode


# ---------------------------------------------------------------------------
# Public dispatch
# ---------------------------------------------------------------------------

def run_interactive(
    project_root: Path,
    prompt: str | None,
    backend: str = DEFAULT_BACKEND,
    resume: bool = False,
    session_id: str | None = None,
    model: str | None = None,
    sandbox: str | None = None,
    approval: str | None = None,
    search: bool = False,
    dangerous: bool = False,
) -> int:
    if backend == "codex":
        return _codex_interactive(
            project_root, prompt, resume=resume, session_id=session_id,
            model=model, sandbox=sandbox, approval=approval,
            search=search, dangerous=dangerous,
        )
    if backend == "gemini":
        return _gemini_interactive(
            project_root, prompt, model=model, sandbox=sandbox,
        )
    if backend == "cursor":
        return _cursor_interactive(
            project_root, prompt, model=model, sandbox=sandbox,
        )
    raise ValueError(f"Unknown backend: {backend!r}. Valid backends: {', '.join(VALID_BACKENDS)}")


def run_exec(
    project_root: Path,
    prompt: str,
    output_schema: Path,
    output_path: Path,
    backend: str = DEFAULT_BACKEND,
    model: str | None = None,
    sandbox: str | None = None,
    dangerous: bool = False,
) -> int:
    if backend == "codex":
        return _codex_exec(
            project_root, prompt, output_schema, output_path,
            model=model, sandbox=sandbox, dangerous=dangerous,
        )
    if backend == "gemini":
        return _gemini_exec(
            project_root, prompt, output_schema, output_path,
            model=model, sandbox=sandbox,
        )
    if backend == "cursor":
        return _cursor_exec(
            project_root, prompt, output_schema, output_path,
            model=model, sandbox=sandbox,
        )
    raise ValueError(f"Unknown backend: {backend!r}. Valid backends: {', '.join(VALID_BACKENDS)}")
