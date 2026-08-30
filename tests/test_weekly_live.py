from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("stack_weekly_live", ROOT / "scripts" / "run-stack-weekly-live.py")
assert SPEC and SPEC.loader
LIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIVE)


class WeeklyLiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root.chmod(0o700)
        self.live_root = self.root / "live"
        self.live_root.mkdir(mode=0o700)
        for name in ("tmp", "gbrain-import", "coordinator", "live-receipts"):
            (self.live_root / name).mkdir(mode=0o700)
        self.field_theory = self.root / "bookmarks.db"
        self.field_theory.write_bytes(b"fixture")
        self.field_theory.chmod(0o600)
        self.gbrain_root = self.root / "x-bookmarks"
        self.gbrain_root.mkdir(mode=0o700)
        self.gbrain_cli = self.root / "gbrain"
        self.gbrain_cli.write_text("#!/bin/sh\n", encoding="utf-8")
        self.gbrain_cli.chmod(0o700)
        for name, value in (
            ("bookmarks-ledger.sqlite3", "fixture"),
            ("local-adapter-config.json", "{}"),
            ("maintenance.json", "{}"),
        ):
            path = self.live_root / name
            path.write_text(value, encoding="utf-8")
            path.chmod(0o600)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_live_scheduler_binding_uses_saved_project_not_execution_checkout(self) -> None:
        self.assertEqual(
            LIVE.ACCOUNT_HOME / "Projects" / "stack",
            LIVE.WEEKLY.DEFAULT_AUTOMATION_WORKDIR,
        )

    def test_saved_primary_execution_is_rejected_before_any_subprocess(self) -> None:
        primary = self.root / "Projects" / "stack"
        primary.mkdir(parents=True, mode=0o700)
        checkout = self.root / ".local" / "share" / "stack" / "weekly-intelligence-source"
        checkout.mkdir(parents=True, mode=0o700)
        commands = mock.Mock()
        with (
            mock.patch.multiple(
                LIVE,
                ROOT=primary,
                ACCOUNT_HOME=self.root,
                AUTOMATION_CHECKOUT=checkout,
            ),
            mock.patch.object(LIVE.subprocess, "run", commands),
            self.assertRaisesRegex(LIVE.LiveLoopError, "execution_checkout_wrong_root"),
        ):
            LIVE.run()
        commands.assert_not_called()

    def test_execution_checkout_requires_clean_detached_fetched_origin_main(self) -> None:
        checkout = self.root / ".local" / "share" / "stack" / "weekly-intelligence-source"
        git_dir = checkout / ".git"
        git_dir.mkdir(parents=True, mode=0o700)
        checkout.chmod(0o700)
        responses = iter((
            str(checkout),
            LIVE.CANONICAL_ORIGIN,
            "",
            "",
            "H README.md\0H scripts/run-stack-weekly-live.py\0",
            "",
            "",
            "HEAD",
            "a" * 40,
            "a" * 40,
        ))
        with (
            mock.patch.multiple(
                LIVE,
                ROOT=checkout.resolve(),
                ACCOUNT_HOME=self.root,
                AUTOMATION_CHECKOUT=checkout,
                _git=mock.Mock(side_effect=lambda argv: next(responses)),
            ),
        ):
            self.assertEqual("a" * 40, LIVE._validate_execution_checkout())

    def test_execution_checkout_stale_commit_blocks(self) -> None:
        checkout = self.root / ".local" / "share" / "stack" / "weekly-intelligence-source"
        git_dir = checkout / ".git"
        git_dir.mkdir(parents=True, mode=0o700)
        checkout.chmod(0o700)
        responses = iter((
            str(checkout),
            LIVE.CANONICAL_ORIGIN,
            "",
            "",
            "H README.md\0H scripts/run-stack-weekly-live.py\0",
            "",
            "",
            "HEAD",
            "a" * 40,
            "b" * 40,
        ))
        with (
            mock.patch.multiple(
                LIVE,
                ROOT=checkout.resolve(),
                ACCOUNT_HOME=self.root,
                AUTOMATION_CHECKOUT=checkout,
                _git=mock.Mock(side_effect=lambda argv: next(responses)),
            ),
            self.assertRaisesRegex(LIVE.LiveLoopError, "execution_checkout_stale"),
        ):
            LIVE._validate_execution_checkout()

    def test_execution_checkout_rejects_hidden_index_flags_before_fetch(self) -> None:
        checkout = self.root / ".local" / "share" / "stack" / "weekly-intelligence-source"
        git_dir = checkout / ".git"
        git_dir.mkdir(parents=True, mode=0o700)
        checkout.chmod(0o700)
        git = mock.Mock(side_effect=(
            str(checkout),
            LIVE.CANONICAL_ORIGIN,
            "",
            "",
            "h scripts/run-stack-weekly-live.py\0S config/weekly-intelligence.json\0",
        ))
        with (
            mock.patch.multiple(
                LIVE,
                ROOT=checkout.resolve(),
                ACCOUNT_HOME=self.root,
                AUTOMATION_CHECKOUT=checkout,
                _git=git,
            ),
            self.assertRaisesRegex(LIVE.LiveLoopError, "execution_checkout_index_flags"),
        ):
            LIVE._validate_execution_checkout()
        self.assertEqual(5, git.call_count)

    def test_direct_nonisolated_execution_is_explicitly_unsupported(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run-stack-weekly-live.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(1, result.returncode)
        self.assertIn('"reason_code":"isolated_no_bytecode_python_required"', result.stderr)

    def test_isolated_no_bytecode_entrypoint_leaves_checkout_free_of_python_artifacts(self) -> None:
        checkout = self.root / "copied-checkout"
        scripts = checkout / "scripts"
        scripts.mkdir(parents=True, mode=0o700)
        for name in ("run-stack-weekly-live.py", "run-stack-weekly-intelligence.py"):
            shutil.copy2(ROOT / "scripts" / name, scripts / name)
        for _attempt in range(2):
            result = subprocess.run(
                [sys.executable, "-I", "-B", str(scripts / "run-stack-weekly-live.py")],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertEqual([], list(checkout.rglob("*.pyc")))
            self.assertEqual([], list(checkout.rglob("__pycache__")))

    def test_prompt_requires_isolated_no_bytecode_mode_for_every_python_command(self) -> None:
        prompt = (ROOT / "config" / "weekly-intelligence-automation-prompt.md").read_text(encoding="utf-8")
        executable = "/opt/homebrew/bin/python3.11"
        matches = list(re.finditer(re.escape(executable), prompt))
        self.assertGreaterEqual(len(matches), 5)
        for match in matches:
            self.assertTrue(
                prompt.startswith(f"{executable} -I -B ", match.start()),
                prompt[match.start():match.start() + 100],
            )

    def test_operations_commands_use_isolated_no_bytecode_python(self) -> None:
        operations = (ROOT / "docs" / "weekly-intelligence-operations.md").read_text(encoding="utf-8")
        for command in (
            "scripts/run-stack-weekly-live.py",
            "scripts/bootstrap-stack.py",
            "scripts/stack-doctor.py",
            "scripts/record-weekly-design-promotion.py",
        ):
            self.assertIn(f"/opt/homebrew/bin/python3.11 -I -B {command}", operations)

    def test_execution_checkout_rejects_ignored_files_before_fetch(self) -> None:
        checkout = self.root / ".local" / "share" / "stack" / "weekly-intelligence-source"
        git_dir = checkout / ".git"
        git_dir.mkdir(parents=True, mode=0o700)
        checkout.chmod(0o700)
        git = mock.Mock(side_effect=(
            str(checkout),
            LIVE.CANONICAL_ORIGIN,
            "",
            "scripts/json.pyc\0",
        ))
        with (
            mock.patch.multiple(
                LIVE,
                ROOT=checkout.resolve(),
                ACCOUNT_HOME=self.root,
                AUTOMATION_CHECKOUT=checkout,
                _git=git,
            ),
            self.assertRaisesRegex(LIVE.LiveLoopError, "execution_checkout_ignored_files"),
        ):
            LIVE._validate_execution_checkout()
        self.assertEqual(4, git.call_count)

    def automation_file(self, account_home: Path, *, mode: int = 0o644, symlink_codex: bool = False) -> Path:
        config = LIVE.WEEKLY.load_config()
        scheduler = config["scheduler"]
        prompt = (ROOT / scheduler["prompt_path"]).read_text(encoding="utf-8")
        persisted_prompt = prompt.removesuffix("\n")
        if symlink_codex:
            real_codex = account_home / "real-codex"
            real_codex.mkdir(mode=0o700)
            (account_home / ".codex").symlink_to(real_codex, target_is_directory=True)
            automation_root = real_codex / "automations"
        else:
            automation_root = account_home / ".codex" / "automations"
        path = automation_root / scheduler["automation_id"] / "automation.toml"
        path.parent.mkdir(parents=True, mode=0o700)
        path.write_text("\n".join((
            f'id = {json.dumps(scheduler["automation_id"])}',
            'kind = "cron"',
            f'prompt = {json.dumps(persisted_prompt)}',
            'status = "ACTIVE"',
            f'rrule = {json.dumps(scheduler["rrule"])}',
            f'model = {json.dumps(scheduler["model"])}',
            f'reasoning_effort = {json.dumps(scheduler["reasoning_effort"])}',
            f'execution_environment = {json.dumps(scheduler["execution_environment"])}',
            f'target = {{ type = "project", project_id = {json.dumps(scheduler["project_id"])} }}',
            f'cwds = [{json.dumps(str(ROOT))}]',
        )) + "\n", encoding="utf-8")
        path.chmod(mode)
        return path

    def test_live_entrypoint_sequences_reconcile_import_and_campaign(self) -> None:
        calls: list[list[str]] = []

        def command(argv, *, timeout=180, receipt_path=None):
            calls.append(argv)
            if receipt_path is not None and receipt_path.name == "source-snapshot-current.json":
                value = {"observations": [{}, {}], "zero_delta": {"state": "passed"}}
            elif receipt_path is not None:
                value = {"status": "no_action", "accepted_count": 2}
            else:
                value = {
                    "run_id": "weekly-fixture",
                    "terminal_state": "no_action",
                    "reason_code": "no_action",
                    "scheduler": {"status": "approved_and_persisted"},
                    "receipt_persisted": True,
                }
                receipts = self.live_root / "coordinator" / "receipts"
                receipts.mkdir(mode=0o700)
                campaign_receipt = receipts / "weekly-fixture.json"
                campaign_receipt.write_text(json.dumps(value), encoding="utf-8")
                campaign_receipt.chmod(0o600)
            if receipt_path is not None:
                receipt_path.write_text(json.dumps(value), encoding="utf-8")
                receipt_path.chmod(0o600)
            return value

        with (
            mock.patch.multiple(
                LIVE,
                LIVE_ROOT=self.live_root,
                FIELD_THEORY_DB=self.field_theory,
                GBRAIN_SOURCE_ROOT=self.gbrain_root,
                GBRAIN_CLI=self.gbrain_cli,
                ACCOUNT_HOME=self.root,
                FIXED_PATH=f"{self.root}/.bun/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                _run=command,
                _validate_execution_checkout=mock.Mock(return_value="a" * 40),
                _preflight=mock.Mock(return_value=self.live_root / "maintenance.json"),
            ),
        ):
            result = LIVE.run()

        self.assertEqual("no_action", result["campaign_terminal_state"])
        self.assertEqual("approved_and_persisted", result["scheduler_status"])
        self.assertEqual(
            "live/coordinator/receipts/weekly-fixture.json",
            result["campaign_receipt_relative_path"],
        )
        self.assertRegex(result["campaign_receipt_digest"], r"^[a-f0-9]{64}$")
        self.assertEqual(
            "live/live-receipts/weekly-fixture.json",
            result["live_binding_receipt_relative_path"],
        )
        self.assertRegex(result["live_binding_receipt_digest"], r"^[a-f0-9]{64}$")
        binding = json.loads((self.live_root / "live-receipts" / "weekly-fixture.json").read_text())
        self.assertEqual(result["campaign_receipt_digest"], binding["campaign_receipt_digest"])
        self.assertIn("u15-source-sync-approved-v1", calls[0])
        self.assertIn("x-bookmarks-import-approved-v1", calls[1])
        self.assertEqual("-I", calls[0][1])
        self.assertEqual("-B", calls[0][2])
        self.assertEqual("-I", calls[1][1])
        self.assertEqual("-B", calls[1][2])
        self.assertEqual("-I", calls[2][1])
        self.assertEqual("-B", calls[2][2])
        self.assertIn("--existing-source-root", calls[1])
        self.assertNotIn("--cli", calls[1])
        self.assertIn("--local-adapter-config", calls[2])

    def test_campaign_receipt_binding_rejects_ambiguous_matches(self) -> None:
        campaign = {
            "run_id": "weekly-fixture",
            "terminal_state": "no_action",
            "reason_code": "no_action",
            "scheduler": {"status": "approved_and_persisted"},
            "receipt_persisted": True,
        }
        receipts = self.live_root / "coordinator" / "receipts"
        receipts.mkdir(mode=0o700)
        for name in ("weekly-fixture.json", "weekly-fixture-2.json"):
            path = receipts / name
            path.write_text(json.dumps(campaign), encoding="utf-8")
            path.chmod(0o600)

        with (
            mock.patch.multiple(LIVE, LIVE_ROOT=self.live_root, ACCOUNT_HOME=self.root),
            self.assertRaisesRegex(LIVE.LiveLoopError, "campaign_receipt_ambiguous"),
        ):
            LIVE._campaign_receipt(campaign, self.live_root / "coordinator")

    def test_subprocess_failure_never_returns_raw_stderr(self) -> None:
        with mock.patch.object(
            LIVE.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=9, stdout="", stderr="credential-value"),
        ):
            with self.assertRaisesRegex(LIVE.LiveLoopError, "local_command_failed") as caught:
                LIVE._run(["fixture"])
        self.assertNotIn("credential-value", str(caught.exception))

    def test_preflight_blocks_all_mutation_on_scheduler_or_maintenance_failure(self) -> None:
        for scheduler_status, maintenance_status, reason in (
            ("mismatch", "linked", "scheduler_contract_not_persisted"),
            ("approved_and_persisted", "alert_stale", "maintenance_receipt_not_linked"),
        ):
            with self.subTest(reason=reason):
                commands: list[list[str]] = []
                with (
                    mock.patch.object(LIVE.WEEKLY, "load_config", return_value={}),
                    mock.patch.object(LIVE.WEEKLY, "scheduler_contract_status", return_value=scheduler_status),
                    mock.patch.object(LIVE, "_latest_maintenance_receipt", return_value=self.live_root / "maintenance.json"),
                    mock.patch.object(LIVE.WEEKLY, "read_latest_maintenance_receipt", return_value={"status": maintenance_status}),
                    mock.patch.object(LIVE, "_validate_execution_checkout", return_value="a" * 40),
                    mock.patch.object(LIVE, "_run", side_effect=lambda argv, **kwargs: commands.append(argv)),
                ):
                    with self.assertRaisesRegex(LIVE.LiveLoopError, reason):
                        LIVE.run()
                self.assertEqual([], commands)

    def test_symlinked_live_root_blocks_before_any_subprocess(self) -> None:
        alias = self.root / "live-alias"
        alias.symlink_to(self.live_root, target_is_directory=True)
        commands: list[list[str]] = []
        with (
            mock.patch.multiple(
                LIVE,
                LIVE_ROOT=alias,
                ACCOUNT_HOME=self.root,
                _validate_execution_checkout=mock.Mock(return_value="a" * 40),
                _preflight=mock.Mock(return_value=self.live_root / "maintenance.json"),
                _run=mock.Mock(side_effect=lambda argv, **kwargs: commands.append(argv)),
            ),
            self.assertRaisesRegex(LIVE.LiveLoopError, "owner_local_symlink_detected"),
        ):
            LIVE.run()
        self.assertEqual([], commands)

    def test_environment_is_fixed_even_when_parent_environment_is_contaminated(self) -> None:
        with (
            mock.patch.multiple(LIVE, ACCOUNT_HOME=self.root, LIVE_ROOT=self.live_root, FIXED_PATH="/fixed/bin"),
            mock.patch.dict(os.environ, {"HOME": "/attacker", "PATH": "/attacker/bin", "TMPDIR": "/attacker/tmp"}),
        ):
            environment = LIVE._environment()
        self.assertEqual(str(self.root), environment["HOME"])
        self.assertEqual("/fixed/bin", environment["PATH"])
        self.assertEqual(str(self.live_root / "tmp"), environment["TMPDIR"])

    def test_scheduler_symlink_ancestor_or_writable_toml_blocks_all_subprocesses(self) -> None:
        for label, mode, symlink_codex in (
            ("symlink-ancestor", 0o644, True),
            ("writable-toml", 0o660, False),
        ):
            with self.subTest(label=label):
                account = self.root / label
                account.mkdir(mode=0o700)
                self.automation_file(account, mode=mode, symlink_codex=symlink_codex)
                automation_root = account / ".codex" / "automations"
                commands: list[list[str]] = []
                with (
                    mock.patch.object(LIVE.WEEKLY, "ACCOUNT_HOME", account),
                    mock.patch.object(LIVE.WEEKLY, "DEFAULT_AUTOMATION_ROOT", automation_root),
                    mock.patch.object(LIVE, "_validate_execution_checkout", return_value="a" * 40),
                    mock.patch.object(LIVE, "_run", side_effect=lambda argv, **kwargs: commands.append(argv)),
                    self.assertRaisesRegex(LIVE.LiveLoopError, "scheduler_contract_not_persisted"),
                ):
                    LIVE.run()
                self.assertEqual([], commands)


if __name__ == "__main__":
    unittest.main()
