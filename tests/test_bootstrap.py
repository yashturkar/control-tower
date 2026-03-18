import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from control_tower.bootstrap import init_project
from control_tower.config_ui import configure_project_interactively
from control_tower.layout import tower_dir
from control_tower.memory import import_project_sessions
from control_tower.packets import validate_task_packet
from control_tower.project import load_agent_registry
from control_tower.prompts import build_tower_prompt
from control_tower.runtime_cli import cmd_delegate


class BootstrapTests(unittest.TestCase):
    def test_init_project_creates_control_tower_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            tower = tower_dir(root)
            self.assertTrue((tower / "agents" / "tower" / "prompt.md").exists())
            self.assertTrue((tower / "schemas" / "packets" / "task.schema.json").exists())
            self.assertTrue((tower / "memory" / "l0.md").exists())
            self.assertTrue((tower / "state" / "agent-registry.json").exists())

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

    def test_import_project_sessions_creates_l2_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_home = Path(tmp) / "codex-home"
            session_dir = codex_home / "sessions" / "2026" / "03" / "17"
            session_dir.mkdir(parents=True)
            (root / ".git").mkdir()
            init_project(root)

            session_path = session_dir / "session.jsonl"
            events = [
                {
                    "timestamp": "2026-03-18T00:00:00Z",
                    "type": "session_meta",
                    "payload": {
                        "id": "session-1",
                        "timestamp": "2026-03-18T00:00:00Z",
                        "cwd": str(root),
                        "originator": "Codex CLI",
                        "source": "cli",
                    },
                },
                {
                    "timestamp": "2026-03-18T00:00:01Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": "Implement the bootstrap",
                    },
                },
            ]
            session_path.write_text("\n".join(json.dumps(event) for event in events) + "\n")

            old = None
            try:
                import os

                old = os.environ.get("CONTROL_TOWER_CODEX_HOME")
                os.environ["CONTROL_TOWER_CODEX_HOME"] = str(codex_home)
                new_sessions = import_project_sessions(root)
            finally:
                import os

                if old is None:
                    os.environ.pop("CONTROL_TOWER_CODEX_HOME", None)
                else:
                    os.environ["CONTROL_TOWER_CODEX_HOME"] = old

            self.assertEqual(1, len(new_sessions))
            copied = tower_dir(root) / "memory" / "l2" / "sessions" / "session-1.jsonl"
            self.assertTrue(copied.exists())
            l0 = (tower_dir(root) / "memory" / "l0.md").read_text()
            self.assertIn("Most recent user goal", l0)

    def test_interactive_config_can_disable_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            init_project(root)

            prompts = [""] * 18
            prompts[5] = "n"
            responses = iter(prompts)

            with patch("builtins.input", side_effect=lambda _: next(responses)):
                configure_project_interactively(root)

            registry = load_agent_registry(root)
            self.assertFalse(registry["agents"]["inspector"]["enabled"])
            self.assertTrue(registry["agents"]["builder"]["enabled"])

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
                with self.assertRaises(ValueError):
                    cmd_delegate(root, "builder", packet_path, output_path, None, "workspace-write", False)

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


if __name__ == "__main__":
    unittest.main()
