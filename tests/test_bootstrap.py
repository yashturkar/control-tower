import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from control_tower.bootstrap import init_project
from control_tower.cli import cmd_status, main as tower_main
from control_tower.config_ui import configure_project_interactively
from control_tower.docs_harness import MANAGED_SECTION_START
from control_tower.graph import explain_commit, explain_decision
from control_tower.layout import tower_dir
from control_tower.memory import _load_jsonl, import_project_sessions
from control_tower.packets import validate_task_packet
from control_tower.project import load_agent_registry, load_graph_indexes, load_graph_nodes, load_project_config, load_runtime_state, save_runtime_state
from control_tower.prompts import build_tower_prompt
from control_tower.runtime_cli import cmd_delegate, cmd_graph_export, cmd_graph_status, cmd_graph_view, cmd_log_decision
from control_tower.runtime_cli import cmd_graph_search, parse_args
from control_tower.sessions import find_latest_session_id_for_project, sync_and_capture_latest


class BootstrapTests(unittest.TestCase):
    def _write_codex_session(
        self,
        session_dir: Path,
        project_root: Path,
        session_id: str,
        timestamp: str,
        messages: list[str],
    ) -> None:
        events = [
            {
                "timestamp": timestamp,
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "timestamp": timestamp,
                    "cwd": str(project_root),
                    "originator": "Codex CLI",
                    "source": "cli",
                },
            }
        ]
        for message in messages:
            events.append(
                {
                    "timestamp": timestamp,
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": message,
                    },
                }
            )

        (session_dir / f"{session_id}.jsonl").write_text("\n".join(json.dumps(event) for event in events) + "\n")

    def _import_sessions_with_messages(
        self,
        project_root: Path,
        sessions: list[tuple[str, str, list[str]]],
        *,
        preserve_cutoff: bool = False,
    ) -> list:
        codex_home = project_root / ".codex-home-fixture"
        session_dir = codex_home / "sessions" / "2026" / "03" / "17"
        session_dir.mkdir(parents=True, exist_ok=True)

        runtime = load_runtime_state(project_root)
        if not preserve_cutoff:
            runtime["session_import_cutoff"] = "1970-01-01T00:00:00Z"
            save_runtime_state(project_root, runtime)

        for session_id, timestamp, messages in sessions:
            self._write_codex_session(session_dir, project_root, session_id, timestamp, messages)

        old = os.environ.get("CONTROL_TOWER_CODEX_HOME")
        try:
            os.environ["CONTROL_TOWER_CODEX_HOME"] = str(codex_home)
            return import_project_sessions(project_root)
        finally:
            if old is None:
                os.environ.pop("CONTROL_TOWER_CODEX_HOME", None)
            else:
                os.environ["CONTROL_TOWER_CODEX_HOME"] = old

    def test_init_project_creates_control_tower_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            tower = tower_dir(root)
            self.assertTrue((tower / "agents" / "tower" / "prompt.md").exists())
            self.assertTrue((tower / "schemas" / "packets" / "task.schema.json").exists())
            self.assertTrue((tower / "schemas" / "decision-graph" / "decision.schema.json").exists())
            self.assertTrue((tower / "memory" / "l0.md").exists())
            self.assertTrue((tower / "state" / "agent-registry.json").exists())
            self.assertTrue((tower / "state" / "decision-graph" / "indexes.json").exists())
            self.assertTrue((tower / "docs" / "state" / "decisions.md").exists())
            self.assertTrue(load_runtime_state(root)["session_import_cutoff"])

    def test_init_project_refreshes_managed_packet_schemas_for_existing_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            result_schema_path = tower_dir(root) / "schemas" / "packets" / "result.schema.json"
            stale_schema = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "packet_type": {"const": "result"},
                    "metadata": {"type": "object"},
                },
            }
            result_schema_path.write_text(json.dumps(stale_schema, indent=2) + "\n")

            init_project(root, force=False)

            refreshed_schema = json.loads(result_schema_path.read_text())
            self.assertFalse(refreshed_schema["additionalProperties"])
            self.assertEqual("string", refreshed_schema["properties"]["packet_type"]["type"])
            self.assertEqual({}, refreshed_schema["properties"]["metadata"]["properties"])

    def test_init_project_adopts_existing_docs_harness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / "docs" / "design-docs").mkdir(parents=True)
            (root / "docs" / "product-specs").mkdir(parents=True)
            (root / "docs" / "index.md").write_text("# Docs\n")
            (root / "docs" / "design-docs" / "index.md").write_text("# Design\n")
            (root / "docs" / "product-specs" / "index.md").write_text("# Product\n")
            (root / "AGENTS.md").write_text("# Agent Map\n")
            init_project(root)

            config = load_project_config(root)
            docs_harness = config["docs_harness"]
            self.assertTrue(docs_harness["enabled"])
            self.assertEqual("adopted", docs_harness["mode"])
            self.assertEqual(["docs"], docs_harness["doc_roots"])
            self.assertEqual(["AGENTS.md"], docs_harness["root_map_files"])
            self.assertEqual(
                ["docs/index.md", "docs/design-docs/index.md", "docs/product-specs/index.md"],
                docs_harness["index_files"],
            )

    def test_init_defaults_scaffolds_minimal_docs_harness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sample-project"
            root.mkdir()
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")

            subprocess.run(
                ["python3", "-m", "control_tower.cli", "init", "--defaults"],
                cwd=root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

            config = load_project_config(root)
            docs_harness = config["docs_harness"]
            self.assertTrue(docs_harness["enabled"])
            self.assertEqual("scaffolded", docs_harness["mode"])
            self.assertTrue((root / "docs" / "index.md").exists())
            self.assertTrue((root / "docs" / "design-docs" / "index.md").exists())
            self.assertTrue((root / "docs" / "product-specs" / "index.md").exists())
            self.assertTrue((root / "docs" / "runbooks" / "README.md").exists())
            self.assertIn(MANAGED_SECTION_START, (root / "AGENTS.md").read_text())

    def test_build_tower_prompt_contains_memory_and_delegate_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            prompt = build_tower_prompt(root, "Review current work")
            self.assertIn("Tower does not directly implement product code.", prompt)
            self.assertIn("tower-run create-packet <agent> ...", prompt)
            self.assertIn("tower-run delegate <agent> --packet <path>", prompt)
            self.assertIn("## Configured Agents", prompt)
            self.assertIn("Builder (builder)", prompt)
            self.assertIn("Review current work", prompt)

    def test_build_tower_prompt_includes_docs_harness_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / "docs" / "design-docs").mkdir(parents=True)
            (root / "docs" / "product-specs").mkdir(parents=True)
            (root / "docs" / "index.md").write_text("# Docs\n")
            (root / "docs" / "design-docs" / "index.md").write_text("# Design\n")
            (root / "docs" / "product-specs" / "index.md").write_text("# Product\n")
            (root / "AGENTS.md").write_text("# Agents\n")
            init_project(root)

            prompt = build_tower_prompt(root, "Document current work")
            self.assertIn("## Repo Docs Harness", prompt)
            self.assertIn("Repo `docs/` is the durable knowledge store", prompt)
            self.assertIn("After most successful Builder, Inspector, and Git-master steps", prompt)

    def test_build_tower_prompt_omits_docs_harness_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            prompt = build_tower_prompt(root, "Document current work")
            self.assertNotIn("## Repo Docs Harness", prompt)

    def test_import_project_sessions_creates_l2_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)
            runtime = load_runtime_state(root)
            runtime["session_import_cutoff"] = "2026-03-17T00:00:00Z"
            save_runtime_state(root, runtime)
            new_sessions = self._import_sessions_with_messages(
                root,
                [("session-1", "2026-03-18T00:00:00Z", ["Implement the bootstrap"])],
            )

            self.assertEqual(1, len(new_sessions))
            copied = tower_dir(root) / "memory" / "l2" / "sessions" / "session-1.jsonl"
            self.assertTrue(copied.exists())
            l0 = (tower_dir(root) / "memory" / "l0.md").read_text()
            indexes = load_graph_indexes(root)
            self.assertIn("Most recent user goal", l0)
            self.assertIn("Top active decision", l0)
            self.assertIn("open_questions", indexes)

    def test_load_jsonl_skips_malformed_trailing_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            valid = {"type": "session_meta", "payload": {"id": "session-1", "cwd": "/tmp"}}
            path.write_text(json.dumps(valid) + "\n" + '{"type":"event_msg","payload":{"message":"unterminated' + "\n")

            with patch("sys.stderr", new=StringIO()) as stderr:
                items = _load_jsonl(path)

            self.assertEqual([valid], items)
            self.assertIn("skipped malformed JSONL entry", stderr.getvalue())

    def test_load_jsonl_skips_malformed_non_trailing_line_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            valid = {"type": "session_meta", "payload": {"id": "session-1", "cwd": "/tmp"}}
            path.write_text(
                '{"type":"event_msg","payload":{"message":"unterminated' + "\n" + json.dumps(valid) + "\n"
            )

            with patch("sys.stderr", new=StringIO()) as stderr:
                items = _load_jsonl(path)

            self.assertEqual([valid], items)
            self.assertIn("skipped malformed JSONL entry", stderr.getvalue())

    def test_import_project_sessions_skips_history_before_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)
            runtime = load_runtime_state(root)
            runtime["session_import_cutoff"] = "2026-03-18T00:00:00Z"
            save_runtime_state(root, runtime)

            new_sessions = self._import_sessions_with_messages(
                root,
                [
                    ("session-old", "2026-03-17T23:59:59Z", ["Old history that should stay out."]),
                    ("session-new", "2026-03-18T00:00:00Z", ["Start using Tower to build Tower."]),
                ],
                preserve_cutoff=True,
            )

            self.assertEqual(["session-new"], [session.session_id for session in new_sessions])
            l1 = (tower_dir(root) / "memory" / "l1.md").read_text()
            self.assertIn("- Start using Tower to build Tower.", l1)
            self.assertNotIn("Old history that should stay out.", l1)

    def test_init_defaults_does_not_back_import_preexisting_codex_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sample-project"
            root.mkdir()
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)

            codex_home = Path(tmp) / "codex-home"
            session_dir = codex_home / "sessions" / "2026" / "03" / "17"
            session_dir.mkdir(parents=True, exist_ok=True)
            self._write_codex_session(
                session_dir,
                root,
                "session-1",
                "2020-01-01T00:00:00Z",
                ["Pre-Tower history should not import on first init."],
            )

            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
            env["CONTROL_TOWER_CODEX_HOME"] = str(codex_home)

            subprocess.run(
                ["python3", "-m", "control_tower.cli", "init", "--defaults"],
                cwd=root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

            l1 = (tower_dir(root) / "memory" / "l1.md").read_text()
            runtime = load_runtime_state(root)
            self.assertIn("- No imported user goals yet", l1)
            self.assertNotEqual("never", runtime["last_sync_time"])
            self.assertTrue(runtime["session_import_cutoff"])

    def test_import_project_sessions_filters_bootstrap_role_prompts_from_recent_user_goals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            self._import_sessions_with_messages(
                root,
                [
                    (
                        "session-1",
                        "2026-03-18T00:00:00Z",
                        [
                            "# Scout  You are Scout, the research and discovery specialist.",
                            "You are Tower for the project `flight-deck`. # Tower You are Tower, the main orchestrator for this repository.",
                            "Investigate why memory sync is duplicating recent user goals.",
                        ],
                    )
                ],
            )

            l0 = (tower_dir(root) / "memory" / "l0.md").read_text()
            l1 = (tower_dir(root) / "memory" / "l1.md").read_text()

            self.assertIn("Investigate why memory sync is duplicating recent user goals.", l0)
            self.assertIn("- Investigate why memory sync is duplicating recent user goals.", l1)
            self.assertIn("## Active Decisions", l1)
            self.assertIn("## Open Questions", l1)
            self.assertNotIn("You are Scout", l1)
            self.assertNotIn("You are Tower", l1)

    def test_import_project_sessions_salvages_plain_text_after_recent_goals_heading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            message = (
                "## Recent User Goals\n\n"
                "- Start with AGENTS.md, implement the plan at ~/.claude/plans/wondrous-rolling-crane.md "
                "and commit to a new branch, then create a relative PR to "
                "https://github.com/yashturkar/flight-deck/pull/6"
            )
            self._import_sessions_with_messages(
                root,
                [("session-1", "2026-03-18T00:00:00Z", [message])],
            )

            expected = (
                "Start with AGENTS.md, implement the plan at ~/.claude/plans/wondrous-rolling-crane.md "
                "and commit to a new branch, then create a relative PR to "
                "https://github.com/yashturkar/flight-deck/pull/6"
            )
            l0 = (tower_dir(root) / "memory" / "l0.md").read_text()
            l1 = (tower_dir(root) / "memory" / "l1.md").read_text()

            self.assertIn(f"Most recent user goal: {expected}", l0)
            self.assertIn(f"- {expected}", l1)
            self.assertNotIn("Most recent user goal: ## Recent User Goals", l0)
            self.assertNotIn("- ## Recent User Goals", l1)

    def test_import_project_sessions_filters_full_bootstrap_prompt_from_recent_user_goals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            bootstrap_prompt = build_tower_prompt(root, "Resume control of the project.")
            self._import_sessions_with_messages(
                root,
                [("session-1", "2026-03-18T00:00:00Z", [bootstrap_prompt])],
            )

            l0 = (tower_dir(root) / "memory" / "l0.md").read_text()
            l1 = (tower_dir(root) / "memory" / "l1.md").read_text()

            self.assertIn("Most recent user goal: No captured user goal yet.", l0)
            self.assertIn("- No imported user goals yet", l1)
            self.assertNotIn("Bootstrap Files", l1)

    def test_import_project_sessions_filters_quoted_bootstrap_prompt_from_recent_user_goals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            bootstrap_prompt = build_tower_prompt(root, "Resume control of the project.")
            quoted_prompt = "\n".join(f"> {line}" if line else ">" for line in bootstrap_prompt.splitlines())
            self._import_sessions_with_messages(
                root,
                [("session-1", "2026-03-18T00:00:00Z", [quoted_prompt])],
            )

            l0 = (tower_dir(root) / "memory" / "l0.md").read_text()
            l1 = (tower_dir(root) / "memory" / "l1.md").read_text()

            self.assertIn("Most recent user goal: No captured user goal yet.", l0)
            self.assertIn("- No imported user goals yet", l1)
            self.assertNotIn("Resume control of the project.", l1)

    def test_import_project_sessions_filters_copied_l1_memory_from_recent_user_goals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            copied_memory = (
                "# L1 Working Memory\n\n"
                "## Recent User Goals\n\n"
                "- Start with AGENTS.md.\n\n"
                "## Memory Policy\n\n"
                "- L2 is the source of truth."
            )
            self._import_sessions_with_messages(
                root,
                [("session-1", "2026-03-18T00:00:00Z", [copied_memory])],
            )

            l0 = (tower_dir(root) / "memory" / "l0.md").read_text()
            l1 = (tower_dir(root) / "memory" / "l1.md").read_text()

            self.assertIn("Most recent user goal: No captured user goal yet.", l0)
            self.assertIn("- No imported user goals yet", l1)
            self.assertNotIn("- # L1 Working Memory", l1)
            self.assertNotIn("Start with AGENTS.md.", l1)

    def test_import_project_sessions_dedupes_repeated_recent_user_goals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            self._import_sessions_with_messages(
                root,
                [
                    ("session-1", "2026-03-18T00:00:00Z", ["Document the packet lifecycle."]),
                    ("session-2", "2026-03-18T01:00:00Z", ["Audit memory goal extraction."]),
                    ("session-3", "2026-03-18T02:00:00Z", ["Audit memory goal extraction."]),
                ],
            )

            l1 = (tower_dir(root) / "memory" / "l1.md").read_text()

            self.assertEqual(1, l1.count("- Audit memory goal extraction."))
            self.assertLess(
                l1.index("- Audit memory goal extraction."),
                l1.index("- Document the packet lifecycle."),
            )

    def test_import_project_sessions_materializes_graph_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            self._import_sessions_with_messages(
                root,
                [("session-1", "2026-03-18T00:00:00Z", ["Document graph-backed memory."])],
            )

            nodes = load_graph_nodes(root)["nodes"]
            indexes = load_graph_indexes(root)
            self.assertIn("session:session-1", nodes)
            self.assertIn("question:which-repo-conventions-should-scribe-treat-as-canonical", nodes)
            self.assertGreaterEqual(len(indexes["known_risks"]), 1)

    def test_sync_memory_tracks_git_commits_in_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sample-project"
            root.mkdir()
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True, capture_output=True)
            init_project(root)
            (root / "README.md").write_text("hello\n")
            subprocess.run(["git", "add", "README.md"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Add README"], cwd=root, check=True, capture_output=True)

            import_project_sessions(root)

            indexes = load_graph_indexes(root)
            nodes = load_graph_nodes(root)["nodes"]
            self.assertTrue(indexes["recent_commits"])
            commit = nodes[indexes["recent_commits"][0]]
            self.assertEqual("Add README", commit["subject"])

    def test_log_decision_creates_active_decision_and_register(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            args = type(
                "Args",
                (),
                {
                    "title": "Use graph-backed memory",
                    "topic": "memory-architecture",
                    "summary": "Decision graph sits between L2 and L1/L0.",
                    "rationale": ["Preserves provenance."],
                    "status": "accepted",
                    "importance": "major",
                    "source_ref": [".control-tower/memory/l1.md"],
                    "related_ref": [".control-tower/memory/l1.md"],
                    "created_by": "tower",
                },
            )()
            cmd_log_decision(root, args)

            indexes = load_graph_indexes(root)
            self.assertEqual(1, len(indexes["active_decisions"]))
            register = (tower_dir(root) / "docs" / "state" / "decisions.md").read_text()
            self.assertIn("Use graph-backed memory", register)

    def test_log_decision_refreshes_l1_and_keeps_ref_traversable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            args = type(
                "Args",
                (),
                {
                    "title": "Use graph-backed memory",
                    "topic": "memory-architecture",
                    "summary": "Decision graph sits between L2 and L1/L0.",
                    "rationale": ["Preserves provenance."],
                    "status": "accepted",
                    "importance": "major",
                    "source_ref": [".control-tower/memory/l1.md"],
                    "related_ref": [".control-tower/memory/l1.md"],
                    "created_by": "tower",
                },
            )()
            cmd_log_decision(root, args)

            l1 = (tower_dir(root) / "memory" / "l1.md").read_text()
            decision_id = load_graph_indexes(root)["active_decisions"][0]
            explanation = explain_decision(root, decision_id)
            self.assertIn("Use graph-backed memory", l1)
            self.assertTrue(any(node.get("type") == "artifact" for node in explanation["related_nodes"]))

    def test_graph_status_reports_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)
            output = StringIO()
            with patch("sys.stdout", output):
                exit_code = cmd_graph_status(root)
            self.assertEqual(0, exit_code)
            self.assertIn("Active decisions:", output.getvalue())

    def test_parse_args_accepts_graph_search_flags(self) -> None:
        args = parse_args(
            [
                "graph-search",
                "--query",
                "memory",
                "--type",
                "decision",
                "--include-edges",
                "--limit",
                "3",
            ]
        )
        self.assertEqual("graph-search", args.command)
        self.assertEqual("memory", args.query)
        self.assertEqual("decision", args.type)
        self.assertTrue(args.include_edges)
        self.assertEqual(3, args.limit)

    def test_parse_args_rejects_non_positive_graph_search_limit(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["graph-search", "--limit", "0"])

    def test_graph_search_lists_nodes_and_edges_with_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            args = type(
                "Args",
                (),
                {
                    "title": "Use graph-backed memory",
                    "topic": "memory-architecture",
                    "summary": "Decision graph sits between L2 and L1/L0.",
                    "rationale": ["Preserves provenance."],
                    "status": "accepted",
                    "importance": "major",
                    "source_ref": [".control-tower/memory/l1.md"],
                    "related_ref": [".control-tower/memory/l1.md"],
                    "created_by": "tower",
                },
            )()
            cmd_log_decision(root, args)

            output = StringIO()
            with patch("sys.stdout", output):
                exit_code = cmd_graph_search(
                    root,
                    type(
                        "Args",
                        (),
                        {
                            "query": "memory",
                            "type": "decision",
                            "include_edges": True,
                            "limit": 10,
                        },
                    )(),
                )
            self.assertEqual(0, exit_code)
            rendered = output.getvalue()
            self.assertIn("Nodes (", rendered)
            self.assertIn("Edges (", rendered)
            self.assertIn("[decision]", rendered)
            self.assertIn("dec_", rendered)

    def test_graph_export_supports_json_dot_and_svg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            args = type(
                "Args",
                (),
                {
                    "title": "Use graph-backed memory",
                    "topic": "memory-architecture",
                    "summary": "Decision graph sits between L2 and L1/L0.",
                    "rationale": ["Preserves provenance."],
                    "status": "accepted",
                    "importance": "major",
                    "source_ref": [".control-tower/memory/l1.md"],
                    "related_ref": [".control-tower/memory/l1.md"],
                    "created_by": "tower",
                },
            )()
            cmd_log_decision(root, args)

            json_out = root / "graph.json"
            dot_out = root / "graph.dot"
            svg_out = root / "graph.svg"

            self.assertEqual(0, cmd_graph_export(root, type("Args", (), {"format": "json", "output": str(json_out)})()))
            self.assertEqual(0, cmd_graph_export(root, type("Args", (), {"format": "dot", "output": str(dot_out)})()))
            self.assertEqual(0, cmd_graph_export(root, type("Args", (), {"format": "svg", "output": str(svg_out)})()))

            json_payload = json.loads(json_out.read_text())
            self.assertIn("nodes", json_payload)
            self.assertIn("edges", json_payload)
            self.assertIn("digraph decision_graph", dot_out.read_text())
            self.assertIn("<svg", svg_out.read_text())

    def test_graph_view_tui_and_web_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            args = type(
                "Args",
                (),
                {
                    "title": "Use graph-backed memory",
                    "topic": "memory-architecture",
                    "summary": "Decision graph sits between L2 and L1/L0.",
                    "rationale": ["Preserves provenance."],
                    "status": "accepted",
                    "importance": "major",
                    "source_ref": [".control-tower/memory/l1.md"],
                    "related_ref": [".control-tower/memory/l1.md"],
                    "created_by": "tower",
                },
            )()
            cmd_log_decision(root, args)
            decision_id = load_graph_indexes(root)["active_decisions"][0]

            tui_output = StringIO()
            with patch("sys.stdout", tui_output):
                self.assertEqual(0, cmd_graph_view(root, type("Args", (), {"web": False, "tui": True, "focus": decision_id, "radius": 1})()))
            self.assertIn("Decision graph (TUI)", tui_output.getvalue())
            self.assertIn(f"Focus: {decision_id}", tui_output.getvalue())

            web_output = StringIO()
            opened: list[str] = []
            with patch("sys.stdout", web_output), patch(
                "control_tower.runtime_cli.webbrowser.open",
                side_effect=lambda uri: opened.append(uri) or True,
            ):
                self.assertEqual(0, cmd_graph_view(root, type("Args", (), {"web": True, "tui": False, "focus": decision_id, "radius": 1})()))
            html_path = Path(web_output.getvalue().strip())
            self.assertTrue(html_path.exists())
            self.assertEqual(".html", html_path.suffix)
            self.assertIn("Decision Graph", html_path.read_text())
            self.assertTrue(opened and opened[0].startswith("file://"))

    def test_explain_commit_supports_short_sha_and_links_session_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sample-project"
            root.mkdir()
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True, capture_output=True)
            init_project(root)
            session_timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

            self._import_sessions_with_messages(
                root,
                [("session-1", session_timestamp, ["Implement graph provenance."])],
            )

            (root / "README.md").write_text("hello\n")
            subprocess.run(["git", "add", "README.md"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Add README"], cwd=root, check=True, capture_output=True)

            import_project_sessions(root)

            full_sha = load_graph_indexes(root)["recent_commits"][0].split(":", 1)[1]
            explanation = explain_commit(root, full_sha[:7])
            self.assertEqual(full_sha, explanation["commit"]["sha"])
            self.assertEqual("session-1", explanation["linked_sessions"][0]["session_id"])

    def test_import_project_sessions_uses_existing_fallback_when_all_recent_messages_are_filtered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            self._import_sessions_with_messages(
                root,
                [
                    (
                        "session-1",
                        "2026-03-18T00:00:00Z",
                        [
                            "# Tower",
                            "You are Scout, the research and discovery specialist.",
                        ],
                    )
                ],
            )

            l0 = (tower_dir(root) / "memory" / "l0.md").read_text()
            l1 = (tower_dir(root) / "memory" / "l1.md").read_text()

            self.assertIn("Most recent user goal: No captured user goal yet.", l0)
            self.assertIn("- No imported user goals yet", l1)

    def test_import_project_sessions_keeps_non_meta_mentions_of_tower_or_scout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            message = "Use Scout to research memory drift and have Tower summarize the next step."
            self._import_sessions_with_messages(
                root,
                [("session-1", "2026-03-18T00:00:00Z", [message])],
            )

            l0 = (tower_dir(root) / "memory" / "l0.md").read_text()
            l1 = (tower_dir(root) / "memory" / "l1.md").read_text()

            self.assertIn(message, l0)
            self.assertIn(f"- {message}", l1)

    def test_interactive_config_can_disable_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            prompts = [
                "custom",
                "",       # builder: enable
                "",       # builder: backend
                "",       # builder: model
                "",       # builder: bypass
                "n",      # inspector: enable (disabled)
                "",       # scout: enable
                "",       # scout: backend
                "",       # scout: model
                "",       # scout: bypass
                "",       # scout: sandbox
                "",       # git-master: enable
                "",       # git-master: backend
                "",       # git-master: model
                "",       # git-master: bypass
                "",       # scribe: enable
                "",       # scribe: backend
                "",       # scribe: model
                "",       # scribe: bypass
                "n",      # add custom agent
                "",       # docs harness
            ]
            responses = iter(prompts)

            with patch("builtins.input", side_effect=lambda _: next(responses)):
                configure_project_interactively(root)

            registry = load_agent_registry(root)
            self.assertFalse(registry["agents"]["inspector"]["enabled"])
            self.assertTrue(registry["agents"]["builder"]["enabled"])

    def test_interactive_config_quick_mode_keeps_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            captured = StringIO()
            with patch("builtins.input", side_effect=["", ""]), patch("sys.stdout", new=captured):
                configure_project_interactively(root)

            registry = load_agent_registry(root)
            self.assertTrue(registry["agents"]["builder"]["enabled"])
            self.assertTrue(registry["agents"]["inspector"]["enabled"])
            self.assertTrue(registry["agents"]["builder"]["dangerously_bypass"])
            self.assertFalse(registry["agents"]["scout"]["dangerously_bypass"])
            self.assertTrue((root / "docs" / "index.md").exists())
            output = captured.getvalue()
            self.assertIn("!!! QUICK SETUP NOTICE !!!", output)
            self.assertIn("dangerous bypass mode by default", output)
            self.assertIn("@@@----@", output)

    def test_custom_config_can_set_sandboxed_builder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            prompts = [
                "custom",
                "",       # builder: enable
                "",       # builder: backend
                "",       # builder: model
                "n",      # builder: bypass=no
                "danger-full-access",  # builder: sandbox
                "",       # inspector: enable
                "",       # inspector: backend
                "",       # inspector: model
                "",       # inspector: bypass
                "",       # scout: enable
                "",       # scout: backend
                "",       # scout: model
                "",       # scout: bypass
                "",       # scout: sandbox
                "",       # git-master: enable
                "",       # git-master: backend
                "",       # git-master: model
                "",       # git-master: bypass
                "",       # scribe: enable
                "",       # scribe: backend
                "",       # scribe: model
                "",       # scribe: bypass
                "n",      # add custom agent
                "",       # docs harness
            ]
            responses = iter(prompts)

            with patch("builtins.input", side_effect=lambda _: next(responses)):
                configure_project_interactively(root)

            registry = load_agent_registry(root)
            self.assertFalse(registry["agents"]["builder"]["dangerously_bypass"])
            self.assertEqual("danger-full-access", registry["agents"]["builder"]["sandbox"])

    def test_interactive_config_scaffolds_docs_harness_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            with patch("builtins.input", side_effect=["", ""]):
                configure_project_interactively(root)
            with patch("builtins.input", side_effect=["", ""]):
                configure_project_interactively(root)

            agents_text = (root / "AGENTS.md").read_text()
            self.assertEqual(1, agents_text.count(MANAGED_SECTION_START))
            self.assertTrue((root / "docs" / "index.md").exists())
            self.assertEqual("scaffolded", load_project_config(root)["docs_harness"]["mode"])

    def test_start_syncs_tower_session_even_on_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            with patch("control_tower.cli.find_project_root", return_value=root), patch(
                "control_tower.cli.run_interactive", side_effect=KeyboardInterrupt()
            ), patch("control_tower.cli.sync_and_capture_latest") as sync_mock:
                with self.assertRaises(KeyboardInterrupt):
                    tower_main(["start"])

            self.assertGreaterEqual(sync_mock.call_count, 2)
            self.assertEqual(((root,), {"role": "tower"}), sync_mock.call_args_list[-1])

    def test_resume_syncs_tower_session_even_on_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            with patch("control_tower.cli.find_project_root", return_value=root), patch(
                "control_tower.cli.run_interactive", side_effect=KeyboardInterrupt()
            ), patch("control_tower.cli.sync_and_capture_latest") as sync_mock:
                with self.assertRaises(KeyboardInterrupt):
                    tower_main(["resume"])

            self.assertGreaterEqual(sync_mock.call_count, 2)
            self.assertEqual(((root,), {"role": "tower"}), sync_mock.call_args_list[-1])

    def test_resume_without_prompt_does_not_rebuild_bootstrap_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            with patch("control_tower.cli.find_project_root", return_value=root), patch(
                "control_tower.cli.run_interactive", return_value=0
            ) as run_mock, patch("control_tower.cli.sync_and_capture_latest"), patch(
                "control_tower.cli.build_tower_prompt"
            ) as prompt_mock:
                tower_main(["resume"])

            prompt_mock.assert_not_called()
            self.assertIsNone(run_mock.call_args.args[1])

    def test_update_refreshes_runtime_and_reinstalls_from_local_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "project"
            source_root = Path(tmp) / "control-tower-src"
            project_root.mkdir()
            source_root.mkdir()
            (project_root / ".git").mkdir()
            (source_root / ".git").mkdir()
            scripts_dir = source_root / "scripts"
            scripts_dir.mkdir()
            (scripts_dir / "install_tower.sh").write_text("#!/usr/bin/env bash\n")

            with patch("control_tower.cli.find_project_root", return_value=project_root), patch(
                "control_tower.cli._source_repo_root", return_value=source_root
            ), patch("control_tower.cli.subprocess.run") as run_mock, patch(
                "control_tower.cli.init_project"
            ) as init_mock, patch("control_tower.cli.update_git_branch") as branch_mock, patch(
                "control_tower.cli.sync_and_capture_latest"
            ) as sync_mock:
                exit_code = tower_main(["update"])

            self.assertEqual(0, exit_code)
            resolved_source_root = source_root.resolve()
            run_mock.assert_any_call(["git", "pull", "--ff-only"], cwd=resolved_source_root, check=True)
            run_mock.assert_any_call([str(resolved_source_root / "scripts" / "install_tower.sh")], cwd=resolved_source_root, check=True)
            init_mock.assert_called_with(project_root, force=False)
            branch_mock.assert_called_once_with(project_root)
            sync_mock.assert_called_once_with(project_root)

    def test_bootstrap_remote_install_handles_forced_remote_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            remote_root = tmp_root / "remote.git"
            author_root = tmp_root / "author"
            install_root = tmp_root / "install-root"
            bootstrap_script = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_remote_install.sh"

            subprocess.run(["git", "init", "--bare", remote_root], check=True, capture_output=True)
            subprocess.run(["git", "init", "-b", "main", author_root], check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Tower Tests"], cwd=author_root, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "tower-tests@example.com"],
                cwd=author_root,
                check=True,
                capture_output=True,
            )
            subprocess.run(["git", "remote", "add", "origin", str(remote_root)], cwd=author_root, check=True, capture_output=True)

            def commit_version(version: str, message: str, orphan: bool = False) -> str:
                if orphan:
                    subprocess.run(
                        ["git", "checkout", "--orphan", "rewritten-main"],
                        cwd=author_root,
                        check=True,
                        capture_output=True,
                    )
                    for child in author_root.iterdir():
                        if child.name == ".git":
                            continue
                        if child.is_dir():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
                    subprocess.run(["git", "add", "-A"], cwd=author_root, check=True, capture_output=True)
                    subprocess.run(
                        ["git", "commit", "--allow-empty", "-m", "reset history"],
                        cwd=author_root,
                        check=True,
                        capture_output=True,
                    )

                scripts_dir = author_root / "scripts"
                scripts_dir.mkdir(parents=True, exist_ok=True)
                install_script = scripts_dir / "install_tower.sh"
                install_script.write_text(
                    "#!/usr/bin/env bash\n"
                    "set -euo pipefail\n"
                    f"printf '%s\\n' '{version}' > \"$(dirname \"$0\")/../installed-version.txt\"\n"
                )
                install_script.chmod(0o755)
                (author_root / "version.txt").write_text(f"{version}\n")
                subprocess.run(["git", "add", "."], cwd=author_root, check=True, capture_output=True)
                subprocess.run(["git", "commit", "-m", message], cwd=author_root, check=True, capture_output=True)
                if orphan:
                    subprocess.run(["git", "branch", "-M", "main"], cwd=author_root, check=True, capture_output=True)
                subprocess.run(["git", "push", "--force", "origin", "main"], cwd=author_root, check=True, capture_output=True)
                return (
                    subprocess.run(
                        ["git", "rev-parse", "HEAD"],
                        cwd=author_root,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    .stdout.strip()
                )

            original_commit = commit_version("v1", "initial version")
            env = os.environ.copy()
            env["CONTROL_TOWER_REPO_URL"] = str(remote_root)
            env["CONTROL_TOWER_INSTALL_ROOT"] = str(install_root)

            subprocess.run([str(bootstrap_script)], check=True, capture_output=True, text=True, env=env)

            rewritten_commit = commit_version("v2", "rewritten version", orphan=True)

            subprocess.run([str(bootstrap_script)], check=True, capture_output=True, text=True, env=env)

            installed_repo = install_root / "repo"
            head_commit = (
                subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=installed_repo,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                .stdout.strip()
            )

            self.assertNotEqual(original_commit, rewritten_commit)
            self.assertEqual(rewritten_commit, head_commit)
            self.assertEqual("v2\n", (installed_repo / "installed-version.txt").read_text())

    def test_version_reports_package_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "control-tower-src"
            source_root.mkdir()
            (source_root / ".git").mkdir()
            with patch("control_tower.cli._source_repo_root", return_value=source_root), patch(
                "control_tower.cli._managed_install_repo_root", return_value=source_root
            ), patch("control_tower.cli._git_output", side_effect=["abc1234", "main"]):
                from io import StringIO
                import sys

                captured = StringIO()
                with patch.object(sys, "stdout", captured):
                    exit_code = tower_main(["--version"])

            self.assertEqual(0, exit_code)
            output = captured.getvalue()
            self.assertIn("tower 0.1.0+gabc1234", output)
            self.assertIn(f"source: {source_root.resolve()}", output)
            self.assertIn("commit: abc1234", output)
            self.assertIn("branch: main", output)
            self.assertIn("managed install active: True", output)

    def test_short_version_flag_reports_package_and_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "control-tower-src"
            source_root.mkdir()
            (source_root / ".git").mkdir()

            with patch("control_tower.cli._source_repo_root", return_value=source_root), patch(
                "control_tower.cli._managed_install_repo_root", return_value=source_root
            ), patch("control_tower.cli._git_output", side_effect=["abc1234", "main"]):
                from io import StringIO
                import sys

                captured = StringIO()
                with patch.object(sys, "stdout", captured):
                    exit_code = tower_main(["-v"])

            self.assertEqual(0, exit_code)
            self.assertIn("tower 0.1.0+gabc1234", captured.getvalue())

    def test_runtime_cli_create_packet_writes_task_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sample-project"
            root.mkdir()
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")

            subprocess.run(
                ["python3", "-m", "control_tower.cli", "init", "--defaults"],
                cwd=root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

            result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "control_tower.runtime_cli",
                    "create-packet",
                    "builder",
                    "--title",
                    "Implement feature X",
                    "--objective",
                    "Add feature X and tests",
                    "--instruction",
                    "Modify the relevant source and tests",
                    "--expected-output",
                    "Updated source and tests",
                    "--definition-of-done",
                    "Feature X works and tests pass",
                ],
                cwd=root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

            packet_path = Path(result.stdout.strip())
            self.assertTrue(packet_path.exists())
            packet = json.loads(packet_path.read_text())
            self.assertEqual("task", packet["packet_type"])
            self.assertEqual("builder", packet["to_agent"])
            self.assertEqual("Implement feature X", packet["title"])
            self.assertEqual(["Modify the relevant source and tests"], packet["instructions"])
            self.assertEqual("implementation", packet["task_type"])

    def test_task_packet_validation_requires_time_budget(self) -> None:
        packet = {
            "schema_version": "1.0.0",
            "packet_type": "task",
            "packet_id": "123",
            "trace_id": "456",
            "created_at": "2026-03-18T00:00:00Z",
            "from_agent": "tower",
            "to_agent": "builder",
            "task_type": "implementation",
            "priority": "normal",
            "project_id": "demo",
            "session_id": "session",
            "title": "Do work",
            "objective": "Do work",
            "instructions": [],
            "constraints": [],
            "inputs": {"files": [], "artifacts": [], "references": []},
            "expected_outputs": [],
            "definition_of_done": [],
            "memory_context_refs": [],
            "doc_context_refs": [],
            "requires_review": True,
            "allow_partial": False,
            "metadata": {},
        }
        with self.assertRaises(ValueError):
            validate_task_packet(packet)

    def test_runtime_cli_rejects_packet_target_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sample-project"
            root.mkdir()
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")

            subprocess.run(
                ["python3", "-m", "control_tower.cli", "init", "--defaults"],
                cwd=root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

            packet_path = tower_dir(root) / "packets" / "outbox" / "wrong-target.json"
            packet = {
                "schema_version": "1.0.0",
                "packet_type": "task",
                "packet_id": "packet-1",
                "trace_id": "trace-1",
                "parent_packet_id": None,
                "created_at": "2026-03-18T00:00:00Z",
                "from_agent": "tower",
                "to_agent": "scribe",
                "task_type": "documentation",
                "priority": "normal",
                "project_id": "sample-project",
                "session_id": "session-1",
                "title": "Write docs",
                "objective": "Update docs",
                "instructions": [],
                "constraints": [],
                "inputs": {"files": [], "artifacts": [], "references": []},
                "expected_outputs": [],
                "definition_of_done": [],
                "memory_context_refs": [],
                "doc_context_refs": [],
                "time_budget": {"soft_seconds": 10, "hard_seconds": 20},
                "requires_review": False,
                "allow_partial": False,
                "metadata": {},
            }
            packet_path.write_text(json.dumps(packet) + "\n")

            result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "control_tower.runtime_cli",
                    "delegate",
                    "builder",
                    "--packet",
                    str(packet_path),
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("does not match requested delegate agent", result.stderr)

    def test_cmd_delegate_rejects_invalid_result_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            packet_path = tower_dir(root) / "packets" / "outbox" / "builder-task.json"
            packet = {
                "schema_version": "1.0.0",
                "packet_type": "task",
                "packet_id": "packet-1",
                "trace_id": "trace-1",
                "parent_packet_id": None,
                "created_at": "2026-03-18T00:00:00Z",
                "from_agent": "tower",
                "to_agent": "builder",
                "task_type": "implementation",
                "priority": "normal",
                "project_id": "sample-project",
                "session_id": "session-1",
                "title": "Implement feature",
                "objective": "Add feature",
                "instructions": [],
                "constraints": [],
                "inputs": {"files": [], "artifacts": [], "references": []},
                "expected_outputs": [],
                "definition_of_done": [],
                "memory_context_refs": [],
                "doc_context_refs": [],
                "time_budget": {"soft_seconds": 10, "hard_seconds": 20},
                "requires_review": False,
                "allow_partial": False,
                "metadata": {},
            }
            packet_path.write_text(json.dumps(packet) + "\n")
            output_path = tower_dir(root) / "packets" / "inbox" / "builder-result.json"

            def fake_run_exec(*args, **kwargs):
                output_path.write_text(json.dumps({"packet_type": "result"}) + "\n")
                return 0

            with patch("control_tower.runtime_cli.run_exec", side_effect=fake_run_exec):
                with self.assertRaises(SystemExit) as exc:
                    cmd_delegate(root, "builder", packet_path, output_path, None, "workspace-write")
            self.assertIn("did not produce a valid ResultPacket", str(exc.exception))

    def test_cmd_delegate_uses_dangerous_bypass_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / "docs" / "design-docs").mkdir(parents=True)
            (root / "docs" / "product-specs").mkdir(parents=True)
            (root / "docs" / "index.md").write_text("# Docs\n")
            (root / "docs" / "design-docs" / "index.md").write_text("# Design\n")
            (root / "docs" / "product-specs" / "index.md").write_text("# Product\n")
            (root / "AGENTS.md").write_text("# Agents\n")
            init_project(root)

            packet_path = tower_dir(root) / "packets" / "outbox" / "builder-task.json"
            packet = {
                "schema_version": "1.0.0",
                "packet_type": "task",
                "packet_id": "packet-1",
                "trace_id": "trace-1",
                "parent_packet_id": None,
                "created_at": "2026-03-18T00:00:00Z",
                "from_agent": "tower",
                "to_agent": "builder",
                "task_type": "implementation",
                "priority": "normal",
                "project_id": "sample-project",
                "session_id": "session-1",
                "title": "Implement feature",
                "objective": "Add feature",
                "instructions": [],
                "constraints": [],
                "inputs": {"files": [], "artifacts": [], "references": []},
                "expected_outputs": [],
                "definition_of_done": [],
                "memory_context_refs": [],
                "doc_context_refs": [],
                "time_budget": {"soft_seconds": 10, "hard_seconds": 20},
                "requires_review": False,
                "allow_partial": False,
                "metadata": {},
            }
            packet_path.write_text(json.dumps(packet) + "\n")
            output_path = tower_dir(root) / "packets" / "inbox" / "builder-result.json"
            result_packet = {
                "schema_version": "1.0.0",
                "packet_type": "result",
                "packet_id": "result-1",
                "trace_id": "trace-1",
                "parent_packet_id": "packet-1",
                "created_at": "2026-03-18T00:00:00Z",
                "from_agent": "builder",
                "to_agent": "tower",
                "status": "success",
                "summary": "ok",
                "work_completed": [],
                "artifacts_changed": [],
                "artifacts_created": [],
                "artifacts_deleted": [],
                "findings": [],
                "follow_up_recommendations": [],
                "review_requested": False,
                "doc_update_needed": False,
                "memory_worthy": [],
                "metrics": {"tokens_used": 0, "files_touched": 0, "tests_added": 0, "tests_passed": 0},
                "raw_output_ref": None,
                "metadata": {},
            }

            def fake_run_exec(*args, **kwargs):
                self.assertTrue(kwargs["dangerous"])
                self.assertIsNone(kwargs["sandbox"])
                output_path.write_text(json.dumps(result_packet) + "\n")
                return 0

            with patch("control_tower.runtime_cli.run_exec", side_effect=fake_run_exec):
                exit_code = cmd_delegate(root, "builder", packet_path, output_path, None, "workspace-write")
            self.assertEqual(0, exit_code)
            follow_ups = list((tower_dir(root) / "packets" / "outbox").glob("scribe-docs-followup-builder-*.json"))
            self.assertEqual(1, len(follow_ups))
            follow_up = json.loads(follow_ups[0].read_text())
            self.assertEqual("documentation", follow_up["task_type"])
            self.assertIn("AGENTS.md", follow_up["doc_context_refs"])
            self.assertIn("docs/index.md", follow_up["doc_context_refs"])
            self.assertEqual([str(output_path.relative_to(root))], follow_up["memory_context_refs"])
            self.assertEqual([".control-tower/docs/state/current-status.md"], follow_up["doc_context_refs"][-1:])

    def test_cmd_delegate_does_not_emit_docs_followup_for_scout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / "docs" / "design-docs").mkdir(parents=True)
            (root / "docs" / "product-specs").mkdir(parents=True)
            (root / "docs" / "index.md").write_text("# Docs\n")
            (root / "docs" / "design-docs" / "index.md").write_text("# Design\n")
            (root / "docs" / "product-specs" / "index.md").write_text("# Product\n")
            init_project(root)

            packet_path = tower_dir(root) / "packets" / "outbox" / "scout-task.json"
            packet = {
                "schema_version": "1.0.0",
                "packet_type": "task",
                "packet_id": "packet-1",
                "trace_id": "trace-1",
                "parent_packet_id": None,
                "created_at": "2026-03-18T00:00:00Z",
                "from_agent": "tower",
                "to_agent": "scout",
                "task_type": "research",
                "priority": "normal",
                "project_id": "sample-project",
                "session_id": "session-1",
                "title": "Research feature",
                "objective": "Inspect options",
                "instructions": [],
                "constraints": [],
                "inputs": {"files": [], "artifacts": [], "references": []},
                "expected_outputs": [],
                "definition_of_done": [],
                "memory_context_refs": [],
                "doc_context_refs": [],
                "time_budget": {"soft_seconds": 10, "hard_seconds": 20},
                "requires_review": False,
                "allow_partial": False,
                "metadata": {},
            }
            packet_path.write_text(json.dumps(packet) + "\n")
            output_path = tower_dir(root) / "packets" / "inbox" / "scout-result.json"
            result_packet = {
                "schema_version": "1.0.0",
                "packet_type": "result",
                "packet_id": "result-1",
                "trace_id": "trace-1",
                "parent_packet_id": "packet-1",
                "created_at": "2026-03-18T00:00:00Z",
                "from_agent": "scout",
                "to_agent": "tower",
                "status": "success",
                "summary": "ok",
                "work_completed": [],
                "artifacts_changed": ["docs/index.md"],
                "artifacts_created": [],
                "artifacts_deleted": [],
                "findings": [],
                "follow_up_recommendations": [],
                "review_requested": False,
                "doc_update_needed": True,
                "memory_worthy": [],
                "metrics": {"tokens_used": 0, "files_touched": 0, "tests_added": 0, "tests_passed": 0},
                "raw_output_ref": None,
                "metadata": {},
            }

            def fake_run_exec(*args, **kwargs):
                output_path.write_text(json.dumps(result_packet) + "\n")
                return 0

            with patch("control_tower.runtime_cli.run_exec", side_effect=fake_run_exec):
                exit_code = cmd_delegate(root, "scout", packet_path, output_path, None, "workspace-write")
            self.assertEqual(0, exit_code)
            follow_ups = list((tower_dir(root) / "packets" / "outbox").glob("scribe-docs-followup-scout-*.json"))
            self.assertEqual([], follow_ups)

    def test_cmd_delegate_does_not_emit_docs_followup_for_blocked_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / "docs" / "design-docs").mkdir(parents=True)
            (root / "docs" / "product-specs").mkdir(parents=True)
            (root / "docs" / "index.md").write_text("# Docs\n")
            (root / "docs" / "design-docs" / "index.md").write_text("# Design\n")
            (root / "docs" / "product-specs" / "index.md").write_text("# Product\n")
            init_project(root)

            packet_path = tower_dir(root) / "packets" / "outbox" / "builder-task.json"
            packet = {
                "schema_version": "1.0.0",
                "packet_type": "task",
                "packet_id": "packet-1",
                "trace_id": "trace-1",
                "parent_packet_id": None,
                "created_at": "2026-03-18T00:00:00Z",
                "from_agent": "tower",
                "to_agent": "builder",
                "task_type": "implementation",
                "priority": "normal",
                "project_id": "sample-project",
                "session_id": "session-1",
                "title": "Implement feature",
                "objective": "Add feature",
                "instructions": [],
                "constraints": [],
                "inputs": {"files": [], "artifacts": [], "references": []},
                "expected_outputs": [],
                "definition_of_done": [],
                "memory_context_refs": [],
                "doc_context_refs": [],
                "time_budget": {"soft_seconds": 10, "hard_seconds": 20},
                "requires_review": False,
                "allow_partial": False,
                "metadata": {},
            }
            packet_path.write_text(json.dumps(packet) + "\n")
            output_path = tower_dir(root) / "packets" / "inbox" / "builder-result.json"
            result_packet = {
                "schema_version": "1.0.0",
                "packet_type": "result",
                "packet_id": "result-1",
                "trace_id": "trace-1",
                "parent_packet_id": "packet-1",
                "created_at": "2026-03-18T00:00:00Z",
                "from_agent": "builder",
                "to_agent": "tower",
                "status": "blocked",
                "summary": "blocked",
                "work_completed": [],
                "artifacts_changed": ["src/app.py"],
                "artifacts_created": [],
                "artifacts_deleted": [],
                "findings": [],
                "follow_up_recommendations": [],
                "review_requested": False,
                "doc_update_needed": True,
                "memory_worthy": [],
                "metrics": {"tokens_used": 0, "files_touched": 0, "tests_added": 0, "tests_passed": 0},
                "raw_output_ref": None,
                "metadata": {},
            }

            def fake_run_exec(*args, **kwargs):
                output_path.write_text(json.dumps(result_packet) + "\n")
                return 0

            with patch("control_tower.runtime_cli.run_exec", side_effect=fake_run_exec):
                exit_code = cmd_delegate(root, "builder", packet_path, output_path, None, "workspace-write")
            self.assertEqual(0, exit_code)
            follow_ups = list((tower_dir(root) / "packets" / "outbox").glob("scribe-docs-followup-builder-*.json"))
            self.assertEqual([], follow_ups)

    def test_runtime_delegate_help_does_not_expose_search_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")

            result = subprocess.run(
                ["python3", "-m", "control_tower.runtime_cli", "delegate", "--help"],
                cwd=tmp,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertNotIn("--search", result.stdout)

    def test_packet_schemas_are_strict_for_structured_output(self) -> None:
        base = Path(__file__).resolve().parents[1] / "src" / "control_tower" / "templates" / "project" / "schemas" / "packets"

        result_schema = json.loads((base / "result.schema.json").read_text())
        self.assertFalse(result_schema["additionalProperties"])
        self.assertEqual("string", result_schema["properties"]["packet_type"]["type"])
        self.assertFalse(result_schema["properties"]["metrics"]["additionalProperties"])
        self.assertFalse(result_schema["properties"]["findings"]["items"]["additionalProperties"])
        self.assertFalse(result_schema["properties"]["metadata"]["additionalProperties"])
        self.assertEqual({}, result_schema["properties"]["metadata"]["properties"])

        task_schema = json.loads((base / "task.schema.json").read_text())
        self.assertFalse(task_schema["additionalProperties"])
        self.assertEqual("string", task_schema["properties"]["packet_type"]["type"])
        self.assertFalse(task_schema["properties"]["inputs"]["additionalProperties"])
        self.assertFalse(task_schema["properties"]["time_budget"]["additionalProperties"])
        self.assertFalse(task_schema["properties"]["metadata"]["additionalProperties"])

    def test_create_packet_from_result_uses_relative_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sample-project"
            root.mkdir()
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")

            subprocess.run(
                ["python3", "-m", "control_tower.cli", "init", "--defaults"],
                cwd=root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

            result_packet = {
                "schema_version": "1.0.0",
                "packet_type": "result",
                "packet_id": "builder-result-1",
                "trace_id": "trace-123",
                "parent_packet_id": "builder-task-1",
                "created_at": "2026-03-18T00:00:00Z",
                "from_agent": "builder",
                "to_agent": "tower",
                "status": "success",
                "summary": "Implemented feature",
                "work_completed": ["feature done"],
                "artifacts_changed": ["src/app.py"],
                "artifacts_created": ["tests/test_app.py"],
                "artifacts_deleted": [],
                "findings": [],
                "follow_up_recommendations": ["commit changes"],
                "review_requested": False,
                "doc_update_needed": True,
                "memory_worthy": ["feature implemented"],
                "metrics": {"tokens_used": 1, "files_touched": 2, "tests_added": 1, "tests_passed": 1},
                "raw_output_ref": None,
                "metadata": {},
            }
            result_path = root / ".control-tower" / "packets" / "inbox" / "builder-result.json"
            result_path.write_text(json.dumps(result_packet) + "\n")

            proc = subprocess.run(
                [
                    "python3",
                    "-m",
                    "control_tower.runtime_cli",
                    "create-packet",
                    "git-master",
                    "--from-result",
                    str(result_path),
                    "--title",
                    "Commit builder changes",
                    "--objective",
                    "Stage and commit the builder output",
                    "--expected-output",
                    "Commit hash",
                    "--definition-of-done",
                    "Changes committed cleanly",
                ],
                cwd=root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

            packet = json.loads(Path(proc.stdout.strip()).read_text())
            self.assertEqual(
                [".control-tower/packets/inbox/builder-result.json"],
                packet["memory_context_refs"],
            )

    def test_status_reports_docs_harness_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            (root / "docs" / "design-docs").mkdir(parents=True)
            (root / "docs" / "product-specs").mkdir(parents=True)
            (root / "docs" / "index.md").write_text("# Docs\n")
            (root / "docs" / "design-docs" / "index.md").write_text("# Design\n")
            (root / "docs" / "product-specs" / "index.md").write_text("# Product\n")
            (root / "AGENTS.md").write_text("# Agents\n")
            init_project(root)

            captured = StringIO()
            with patch("sys.stdout", new=captured):
                exit_code = cmd_status(root)

            self.assertEqual(0, exit_code)
            output = captured.getvalue()
            self.assertIn("Docs harness: enabled", output)
            self.assertIn("Docs mode: adopted", output)
            self.assertIn("Docs roots: docs", output)
            self.assertIn("Auto Scribe docs: after-most-work", output)

    def test_find_latest_session_id_for_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sample-project"
            root.mkdir()
            (root / ".git").mkdir()
            codex_home = Path(tmp) / "codex-home"
            session_dir = codex_home / "sessions" / "2026" / "03" / "18"
            session_dir.mkdir(parents=True)

            older = session_dir / "older.jsonl"
            older.write_text(
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": "session-older",
                            "timestamp": "2026-03-18T00:00:00Z",
                            "cwd": str(root),
                        },
                    }
                )
                + "\n"
            )
            newer = session_dir / "newer.jsonl"
            newer.write_text(
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": "session-newer",
                            "timestamp": "2026-03-18T01:00:00Z",
                            "cwd": str(root),
                        },
                    }
                )
                + "\n"
            )

            old = os.environ.get("CONTROL_TOWER_CODEX_HOME")
            try:
                os.environ["CONTROL_TOWER_CODEX_HOME"] = str(codex_home)
                latest = find_latest_session_id_for_project(root)
            finally:
                if old is None:
                    os.environ.pop("CONTROL_TOWER_CODEX_HOME", None)
                else:
                    os.environ["CONTROL_TOWER_CODEX_HOME"] = old

            self.assertEqual("session-newer", latest)

    def test_find_latest_session_id_for_project_ignores_exec_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sample-project"
            root.mkdir()
            (root / ".git").mkdir()
            codex_home = Path(tmp) / "codex-home"
            session_dir = codex_home / "sessions" / "2026" / "03" / "18"
            session_dir.mkdir(parents=True)

            interactive = session_dir / "interactive.jsonl"
            interactive.write_text(
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": "session-interactive",
                            "timestamp": "2026-03-18T00:00:00Z",
                            "cwd": str(root),
                            "source": "cli",
                            "originator": "codex_cli_rs",
                        },
                    }
                )
                + "\n"
            )
            exec_session = session_dir / "exec.jsonl"
            exec_session.write_text(
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": "session-exec",
                            "timestamp": "2026-03-18T01:00:00Z",
                            "cwd": str(root),
                            "source": "exec",
                            "originator": "codex_exec",
                        },
                    }
                )
                + "\n"
            )

            old = os.environ.get("CONTROL_TOWER_CODEX_HOME")
            try:
                os.environ["CONTROL_TOWER_CODEX_HOME"] = str(codex_home)
                latest = find_latest_session_id_for_project(root)
            finally:
                if old is None:
                    os.environ.pop("CONTROL_TOWER_CODEX_HOME", None)
                else:
                    os.environ["CONTROL_TOWER_CODEX_HOME"] = old

            self.assertEqual("session-interactive", latest)

    def test_sync_and_capture_latest_tower_ignores_exec_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            class Session:
                def __init__(self, session_id: str, source: str, originator: str) -> None:
                    self.session_id = session_id
                    self.source = source
                    self.originator = originator

            with patch(
                "control_tower.sessions.import_project_sessions",
                return_value=[Session("exec-1", "exec", "codex_exec"), Session("tower-1", "cli", "codex_cli_rs")],
            ):
                latest = sync_and_capture_latest(root, role="tower")

            self.assertEqual("tower-1", latest)


class CustomAgentTests(unittest.TestCase):

    def test_custom_agent_entry_has_expected_fields(self) -> None:
        from control_tower.agents import make_custom_agent_entry
        entry = make_custom_agent_entry(
            name="Security Reviewer",
            role="security-review",
            description="Reviews code for security vulnerabilities.",
            backend="gemini",
            model="gemini-2.5-pro",
        )
        self.assertEqual("Security Reviewer", entry["name"])
        self.assertEqual("security-review", entry["role"])
        self.assertEqual("gemini", entry["backend"])
        self.assertEqual("gemini-2.5-pro", entry["model"])
        self.assertTrue(entry["custom"])

    def test_custom_agent_entry_rejects_invalid_backend(self) -> None:
        from control_tower.agents import make_custom_agent_entry
        with self.assertRaises(ValueError):
            make_custom_agent_entry(
                name="Bad Agent",
                role="test",
                description="test",
                backend="invalid-backend",
            )

    def test_custom_agent_persists_in_registry(self) -> None:
        from control_tower.agents import make_custom_agent_entry
        from control_tower.project import save_agent_registry
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            registry = load_agent_registry(root)
            registry["agents"]["security-reviewer"] = make_custom_agent_entry(
                name="Security Reviewer",
                role="security-review",
                description="Reviews code for security vulnerabilities.",
                backend="gemini",
                model="gemini-2.5-pro",
            )
            save_agent_registry(root, registry)

            reloaded = load_agent_registry(root)
            self.assertIn("security-reviewer", reloaded["agents"])
            self.assertEqual("gemini", reloaded["agents"]["security-reviewer"]["backend"])
            self.assertTrue(reloaded["agents"]["security-reviewer"]["custom"])

    def test_custom_agent_included_in_tower_prompt(self) -> None:
        from control_tower.agents import make_custom_agent_entry
        from control_tower.project import save_agent_registry
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            registry = load_agent_registry(root)
            registry["agents"]["security-reviewer"] = make_custom_agent_entry(
                name="Security Reviewer",
                role="security-review",
                description="Reviews code for security vulnerabilities.",
                backend="gemini",
            )
            save_agent_registry(root, registry)

            prompt = build_tower_prompt(root, "test prompt")
            self.assertIn("Security Reviewer", prompt)
            self.assertIn("[backend: gemini]", prompt)
            self.assertIn("[custom]", prompt)

    def test_custom_agent_subagent_prompt_uses_fallback(self) -> None:
        from control_tower.agents import make_custom_agent_entry
        from control_tower.project import save_agent_registry
        from control_tower.prompts import build_subagent_prompt
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            registry = load_agent_registry(root)
            registry["agents"]["migration-helper"] = make_custom_agent_entry(
                name="Migration Helper",
                role="migration",
                description="Handles database migrations.",
            )
            save_agent_registry(root, registry)

            packet_text = '{"task": "test"}'
            prompt = build_subagent_prompt(root, "migration-helper", packet_text)
            self.assertIn("Migration Helper", prompt)
            self.assertIn("migration", prompt)
            self.assertIn(packet_text, prompt)

    def test_custom_agent_with_prompt_file(self) -> None:
        from control_tower.agents import make_custom_agent_entry
        from control_tower.project import save_agent_registry
        from control_tower.prompts import build_subagent_prompt
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            prompt_file = ".control-tower/agents/infra-bot/prompt.md"
            prompt_path = root / prompt_file
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text("# Infra Bot\n\nYou manage infrastructure.\n")

            registry = load_agent_registry(root)
            registry["agents"]["infra-bot"] = make_custom_agent_entry(
                name="Infra Bot",
                role="infrastructure",
                description="Manages infrastructure.",
                prompt_file=prompt_file,
            )
            save_agent_registry(root, registry)

            prompt = build_subagent_prompt(root, "infra-bot", '{"task": "deploy"}')
            self.assertIn("You manage infrastructure.", prompt)

    def test_bootstrap_scaffolds_custom_agent_dirs(self) -> None:
        from control_tower.agents import make_custom_agent_entry
        from control_tower.project import save_agent_registry
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            registry = load_agent_registry(root)
            registry["agents"]["docs-bot"] = make_custom_agent_entry(
                name="Docs Bot",
                role="documentation",
                description="Writes documentation.",
                prompt_file=".control-tower/agents/docs-bot/prompt.md",
            )
            save_agent_registry(root, registry)

            # Re-init to trigger scaffolding
            init_project(root)

            prompt_path = root / ".control-tower" / "agents" / "docs-bot" / "prompt.md"
            self.assertTrue(prompt_path.exists())
            self.assertIn("Docs Bot", prompt_path.read_text())

    def test_list_registered_and_enabled_agents(self) -> None:
        from control_tower.agents import list_enabled_agents, list_registered_agents, make_custom_agent_entry
        from control_tower.project import save_agent_registry
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            registry = load_agent_registry(root)
            registry["agents"]["custom-agent"] = make_custom_agent_entry(
                name="Custom Agent",
                role="custom",
                description="A custom agent.",
                enabled=False,
            )
            save_agent_registry(root, registry)
            reloaded = load_agent_registry(root)

            all_agents = list_registered_agents(reloaded)
            enabled = list_enabled_agents(reloaded)

            self.assertIn("custom-agent", all_agents)
            self.assertNotIn("custom-agent", enabled)
            self.assertIn("builder", enabled)

    def test_default_registry_includes_backend_field(self) -> None:
        from control_tower.agents import default_agent_registry
        registry = default_agent_registry()
        for key, config in registry["agents"].items():
            self.assertEqual("codex", config["backend"], f"Agent {key} should default to codex backend")

    def test_interactive_custom_agent_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            prompts = [
                "custom",
                # Built-in agents: all default (enable + backend + model + bypass)
                # builder: enable, backend, model, bypass(Y)
                "", "", "", "",
                # inspector: enable, backend, model, bypass(Y)
                "", "", "", "",
                # scout: enable, backend, model, bypass(N), sandbox
                "", "", "", "", "",
                # git-master: enable, backend, model, bypass(Y)
                "", "", "", "",
                # scribe: enable, backend, model, bypass(Y)
                "", "", "", "",
                # Add custom agent? Yes
                "y",
                "Security Reviewer",   # name
                "security-review",     # role
                "Reviews code for security vulnerabilities.",  # description
                "gemini",              # backend
                "",                    # model
                "n",                   # bypass=no
                "read-only",           # sandbox
                "",                    # create prompt file (Y)
                # Add another custom agent? No
                "n",
                # docs harness
                "",
            ]
            responses = iter(prompts)

            with patch("builtins.input", side_effect=lambda _: next(responses)):
                configure_project_interactively(root)

            registry = load_agent_registry(root)
            self.assertIn("security-reviewer", registry["agents"])
            agent = registry["agents"]["security-reviewer"]
            self.assertEqual("Security Reviewer", agent["name"])
            self.assertEqual("gemini", agent["backend"])
            self.assertEqual("read-only", agent["sandbox"])
            self.assertTrue(agent["custom"])
            self.assertTrue((root / ".control-tower" / "agents" / "security-reviewer" / "prompt.md").exists())


class BackendTests(unittest.TestCase):

    def test_valid_backends(self) -> None:
        from control_tower.backends import VALID_BACKENDS
        self.assertIn("codex", VALID_BACKENDS)
        self.assertIn("gemini", VALID_BACKENDS)
        self.assertIn("cursor", VALID_BACKENDS)

    def test_run_exec_rejects_invalid_backend(self) -> None:
        from control_tower.backends import run_exec
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                run_exec(root, "test", Path("schema.json"), Path("out.json"), backend="invalid")

    def test_run_interactive_rejects_invalid_backend(self) -> None:
        from control_tower.backends import run_interactive
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                run_interactive(root, "test", backend="invalid")

    def test_codex_exec_builds_correct_args(self) -> None:
        from control_tower.backends import run_exec
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("control_tower.backends.subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
                run_exec(root, "test prompt", Path("schema.json"), Path("out.json"), backend="codex", model="gpt-4")
                args = mock_run.call_args[0][0]
                self.assertEqual("codex", args[0])
                self.assertEqual("exec", args[1])
                self.assertIn("-m", args)
                self.assertIn("gpt-4", args)

    def test_gemini_exec_builds_correct_args(self) -> None:
        from control_tower.backends import run_exec
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("control_tower.backends.subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
                run_exec(root, "test prompt", Path("schema.json"), Path("out.json"), backend="gemini", model="gemini-2.5-pro")
                args = mock_run.call_args[0][0]
                self.assertEqual("gemini", args[0])
                self.assertEqual("exec", args[1])
                self.assertIn("--model", args)
                self.assertIn("gemini-2.5-pro", args)

    def test_cursor_exec_builds_correct_args(self) -> None:
        from control_tower.backends import run_exec
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("control_tower.backends.subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout='{"ok": true}')
                run_exec(root, "test prompt", Path("schema.json"), Path("out.json"), backend="cursor")
                args = mock_run.call_args[0][0]
                self.assertEqual("agent", args[0])
                self.assertIn("-p", args)
                self.assertIn("--output-format", args)
                self.assertIn("json", args)

    def test_cursor_exec_tolerates_missing_stdout(self) -> None:
        from control_tower.backends import run_exec
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_path = root / "out.json"
            with patch("control_tower.backends.subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout=None)
                exit_code = run_exec(root, "test prompt", Path("schema.json"), output_path, backend="cursor")

            self.assertEqual(0, exit_code)
            self.assertFalse(output_path.exists())

    def test_delegate_uses_agent_backend(self) -> None:
        from control_tower.agents import make_custom_agent_entry
        from control_tower.project import save_agent_registry
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            registry = load_agent_registry(root)
            registry["agents"]["gemini-agent"] = make_custom_agent_entry(
                name="Gemini Agent",
                role="implementation",
                description="Builds with Gemini.",
                backend="gemini",
                enabled=True,
                dangerously_bypass=True,
            )
            save_agent_registry(root, registry)

            # Create a valid task packet
            from control_tower.packets import create_task_packet
            packet = create_task_packet(
                from_agent="tower",
                to_agent="gemini-agent",
                task_type="implementation",
                priority="normal",
                project_id="test",
                session_id="test-session",
                title="Test task",
                objective="Test objective",
                instructions=["Do the thing"],
                constraints=[],
                files=[],
                artifacts=[],
                references=[],
                expected_outputs=[],
                definition_of_done=["Done"],
                memory_context_refs=[],
                doc_context_refs=[],
                soft_seconds=900,
                hard_seconds=3600,
                requires_review=False,
                allow_partial=False,
            )
            packet_path = root / ".control-tower" / "packets" / "outbox" / "test.json"
            packet_path.parent.mkdir(parents=True, exist_ok=True)
            packet_path.write_text(json.dumps(packet, indent=2))

            with patch("control_tower.runtime_cli.run_exec") as mock_exec:
                mock_exec.return_value = 1  # non-zero to skip result validation
                cmd_delegate(root, "gemini-agent", packet_path, output=None, model=None, sandbox=None)

            self.assertEqual("gemini", mock_exec.call_args[1].get("backend", mock_exec.call_args.kwargs.get("backend")))

    def test_cli_resolve_options_includes_backend(self) -> None:
        from control_tower.cli import resolve_codex_options
        config = {"codex_defaults": {"backend": "gemini"}}
        args = type("Args", (), {"model": None, "sandbox": None, "approval": None, "search": None, "dangerous": None, "backend": None})()
        options = resolve_codex_options(config, args)
        self.assertEqual("gemini", options["backend"])

    def test_cli_resolve_options_cli_overrides_config_backend(self) -> None:
        from control_tower.cli import resolve_codex_options
        config = {"codex_defaults": {"backend": "gemini"}}
        args = type("Args", (), {"model": None, "sandbox": None, "approval": None, "search": None, "dangerous": None, "backend": "cursor"})()
        options = resolve_codex_options(config, args)
        self.assertEqual("cursor", options["backend"])

    def test_status_shows_custom_agents(self) -> None:
        from control_tower.agents import make_custom_agent_entry
        from control_tower.project import save_agent_registry
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            registry = load_agent_registry(root)
            registry["agents"]["my-agent"] = make_custom_agent_entry(
                name="My Agent",
                role="custom",
                description="A custom agent.",
                backend="cursor",
            )
            save_agent_registry(root, registry)

            captured = StringIO()
            with patch("control_tower.cli.find_project_root", return_value=root), patch("sys.stdout", new=captured):
                cmd_status(root)

            output = captured.getvalue()
            self.assertIn("My Agent (cursor)", output)
            self.assertIn("Custom agents: My Agent", output)


if __name__ == "__main__":
    unittest.main()
