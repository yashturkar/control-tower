from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path
from typing import Any

DEFAULT_DOC_ROOTS = ["docs"]
DEFAULT_ROOT_MAP_FILES = ["AGENTS.md"]
DEFAULT_INDEX_FILES = [
    "docs/index.md",
    "docs/design-docs/index.md",
    "docs/product-specs/index.md",
]
DEFAULT_AUTO_SCRIBE_AGENTS = ["builder", "inspector", "git-master"]

MANAGED_SECTION_START = "<!-- control-tower-docs-harness:start -->"
MANAGED_SECTION_END = "<!-- control-tower-docs-harness:end -->"


def default_docs_harness() -> dict[str, Any]:
    return {
        "enabled": False,
        "mode": "disabled",
        "doc_roots": [],
        "root_map_files": [],
        "index_files": [],
        "auto_scribe_mode": "after-most-work",
        "auto_scribe_agents": list(DEFAULT_AUTO_SCRIBE_AGENTS),
        "scaffolded_by_init": False,
    }


def detect_docs_harness(project_root: Path, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = existing or {}
    config = default_docs_harness()
    config["auto_scribe_mode"] = existing.get("auto_scribe_mode", config["auto_scribe_mode"])
    config["auto_scribe_agents"] = list(existing.get("auto_scribe_agents", config["auto_scribe_agents"]))

    docs_root = project_root / "docs"
    if not docs_root.is_dir():
        return config

    scaffolded = bool(existing.get("scaffolded_by_init", False))
    config["enabled"] = True
    config["mode"] = "scaffolded" if scaffolded else "adopted"
    config["doc_roots"] = list(DEFAULT_DOC_ROOTS)
    config["root_map_files"] = _existing_paths(project_root, DEFAULT_ROOT_MAP_FILES)
    config["index_files"] = _existing_paths(project_root, DEFAULT_INDEX_FILES)
    config["scaffolded_by_init"] = scaffolded
    return config


def scaffold_minimal_docs_harness(project_root: Path) -> list[Path]:
    created: list[Path] = []
    for source in _docs_template_root().rglob("*"):
        relative = source.relative_to(_docs_template_root())
        target = project_root / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        created.append(target)

    agents_path = project_root / "AGENTS.md"
    prior = agents_path.read_text() if agents_path.exists() else ""
    rendered = render_root_map(prior)
    if rendered != prior:
        agents_path.write_text(rendered)
        created.append(agents_path)
    return created


def ensure_docs_harness(project_root: Path, existing: dict[str, Any] | None = None, scaffold_missing: bool = False) -> dict[str, Any]:
    existing = existing or {}
    if scaffold_missing and not (project_root / "docs").is_dir():
        scaffold_minimal_docs_harness(project_root)
        existing = dict(existing)
        existing["scaffolded_by_init"] = True
    return detect_docs_harness(project_root, existing)


def docs_harness_context_refs(project_root: Path, config: dict[str, Any] | None = None) -> list[str]:
    config = config or detect_docs_harness(project_root)
    refs = list(config.get("root_map_files", [])) + list(config.get("index_files", []))
    if (project_root / "ARCHITECTURE.md").exists():
        refs.append("ARCHITECTURE.md")
    refs.append(".control-tower/docs/state/current-status.md")
    return _dedupe(refs)


def render_root_map(existing_text: str) -> str:
    managed = "\n".join(
        [
            MANAGED_SECTION_START,
            "## Control Tower Docs Harness",
            "",
            "- Durable system and product knowledge lives in `docs/`.",
            "- `.control-tower/` holds operational memory, task state, packets, and session context.",
            "- Start from `docs/index.md`, then follow the domain indices under `docs/design-docs/` and `docs/product-specs/`.",
            "- Keep the repo docs harness current when behavior, interfaces, or operational workflows change.",
            MANAGED_SECTION_END,
        ]
    )

    stripped = existing_text.strip()
    if not stripped:
        return managed + "\n"

    if MANAGED_SECTION_START in existing_text and MANAGED_SECTION_END in existing_text:
        prefix, rest = existing_text.split(MANAGED_SECTION_START, 1)
        _, suffix = rest.split(MANAGED_SECTION_END, 1)
        body = prefix.rstrip()
        if body:
            body += "\n\n"
        return body + managed + suffix.rstrip() + "\n"

    return existing_text.rstrip() + "\n\n" + managed + "\n"


def _existing_paths(project_root: Path, candidates: list[str]) -> list[str]:
    return [candidate for candidate in candidates if (project_root / candidate).exists()]


def _dedupe(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            ordered.append(value)
            seen.add(value)
    return ordered


def _docs_template_root() -> Path:
    return Path(str(resources.files("control_tower"))) / "templates" / "docs_harness"
