import json
import os
import shutil
import subprocess
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from control_tower.bootstrap import init_project
from control_tower.cli import main as tower_main
from control_tower.config_ui import configure_project_interactively
from control_tower.layout import tower_dir
from control_tower.memory import import_project_sessions
from control_tower.packets import validate_task_packet
from control_tower.project import load_agent_registry
from control_tower.prompts import build_tower_prompt
from control_tower.runtime_cli import cmd_delegate
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
    ) -> list:
        codex_home = project_root / ".codex-home-fixture"
        session_dir = codex_home / "sessions" / "2026" / "03" / "17"
        session_dir.mkdir(parents=True, exist_ok=True)

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
            self.assertTrue((tower / "memory" / "l0.md").exists())
            self.assertTrue((tower / "state" / "agent-registry.json").exists())

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
            (root / ".git").mkdir()
            init_project(root)
            new_sessions = self._import_sessions_with_messages(
                root,
                [("session-1", "2026-03-18T00:00:00Z", ["Implement the bootstrap"])],
            )

            self.assertEqual(1, len(new_sessions))
            copied = tower_dir(root) / "memory" / "l2" / "sessions" / "session-1.jsonl"
            self.assertTrue(copied.exists())
            l0 = (tower_dir(root) / "memory" / "l0.md").read_text()
            self.assertIn("Most recent user goal", l0)

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
            self.assertNotIn("You are Scout", l1)
            self.assertNotIn("You are Tower", l1)

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
                "",
                "",
                "",
                "n",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
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
                "",
                "",
                "n",
                "danger-full-access",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            ]
            responses = iter(prompts)

            with patch("builtins.input", side_effect=lambda _: next(responses)):
                configure_project_interactively(root)

            registry = load_agent_registry(root)
            self.assertFalse(registry["agents"]["builder"]["dangerously_bypass"])
            self.assertEqual("danger-full-access", registry["agents"]["builder"]["sandbox"])

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


if __name__ == "__main__":
    unittest.main()
