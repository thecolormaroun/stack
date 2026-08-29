"""Fixture-first tests for the dry-run-default x-bookmarks GBrain handoff."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "bookmark-sources" / "field-theory-pages.json"
RECONCILE_SPEC = importlib.util.spec_from_file_location("reconcile_for_import", ROOT / "scripts" / "reconcile-bookmark-sources.py")
assert RECONCILE_SPEC and RECONCILE_SPEC.loader
RECONCILE = importlib.util.module_from_spec(RECONCILE_SPEC)
RECONCILE_SPEC.loader.exec_module(RECONCILE)
SPEC = importlib.util.spec_from_file_location("import_bookmark_deltas", ROOT / "scripts" / "import-bookmark-deltas.py")
assert SPEC and SPEC.loader
SPEC_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SPEC_MODULE)


def install_fake_pinned_runtime(module, root: Path) -> dict[str, object]:
    """Install a private test-only copy of the exact pinned-path topology."""

    original = {
        name: getattr(module, name)
        for name in (
            "ACCOUNT_HOME",
            "DEFAULT_GBRAIN_CLI",
            "EXPECTED_GBRAIN_CLI",
            "DEFAULT_GBRAIN_CONFIG",
            "DEFAULT_BUN_CLI",
            "EXPECTED_BUN_CLI",
            "FIXED_PATH",
        )
    }
    account_home = root / "owner-home"
    gbrain_home = account_home / ".gbrain"
    gbrain_home.mkdir(parents=True)
    account_home.chmod(0o700)
    gbrain_home.chmod(0o700)

    bun_target = root / "pinned" / "bun" / "1.3.14" / "bin" / "bun"
    bun_target.parent.mkdir(parents=True)
    bun_target.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    bun_target.chmod(0o700)
    bun_launcher = root / "launcher" / "bin" / "bun"
    bun_launcher.parent.mkdir(parents=True)
    bun_launcher.symlink_to(bun_target)

    cli_target = account_home / ".bun" / "install" / "global" / "node_modules" / "gbrain" / "src" / "cli.ts"
    cli_target.parent.mkdir(parents=True)
    cli_target.write_text("export {};\n", encoding="utf-8")
    cli_target.chmod(0o700)
    package = cli_target.parents[1] / "package.json"
    package.write_text(json.dumps({"name": "gbrain", "version": "0.42.67.0"}), encoding="utf-8")
    package.chmod(0o600)
    cli_launcher = account_home / ".bun" / "bin" / "gbrain"
    cli_launcher.parent.mkdir(parents=True)
    cli_launcher.symlink_to(cli_target)

    module.ACCOUNT_HOME = account_home
    module.DEFAULT_GBRAIN_CLI = str(cli_launcher)
    module.EXPECTED_GBRAIN_CLI = cli_target
    module.DEFAULT_GBRAIN_CONFIG = gbrain_home / "config.json"
    module.DEFAULT_BUN_CLI = bun_launcher
    module.EXPECTED_BUN_CLI = bun_target
    module.FIXED_PATH = f"{cli_launcher.parent}:{bun_launcher.parent}:/usr/bin:/bin"
    return original


class FakeTransport:
    def __init__(self, canary: bool = False, failures: int = 0) -> None:
        self.canary = canary
        self.failures = failures
        self.calls: list[dict] = []

    def import_markdown_directory(self, *, source: str, documents: list[dict], idempotency_key: str) -> dict:
        self.calls.append({"source": source, "documents": documents, "idempotency_key": idempotency_key})
        if self.failures:
            self.failures -= 1
            return {"status": "rate_limited", "retry_after_seconds": 0}
        return {"status": "accepted", "accepted": [doc["identity"] for doc in documents], "rejected": []}

    def text_canary(self, *, source: str, identity: str) -> dict:
        return {"status": "indexed" if self.canary else "accepted", "source": source, "identity": identity}


class BookmarkGBrainImportTests(unittest.TestCase):
    def setUp(self) -> None:
        source = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.snapshot = RECONCILE.reconcile_sources(source, {"version": 1})
        self.private_runtime_directory = tempfile.TemporaryDirectory()
        runtime_root = Path(self.private_runtime_directory.name).resolve()
        runtime_root.chmod(0o700)
        self._runtime_constants = install_fake_pinned_runtime(SPEC_MODULE, runtime_root)
        self.private_config_directory = tempfile.TemporaryDirectory()
        config_root = Path(self.private_config_directory.name).resolve()
        config_root.chmod(0o700)
        self.config_path = config_root / "config.json"
        self.config_path.write_text(json.dumps({
            "engine": "postgres",
            "database_url": "postgresql://fixture:fixture@127.0.0.1:5432/gbrain_mookie",
        }), encoding="utf-8")
        self.config_path.chmod(0o600)
        self.approved_cli = SPEC_MODULE.DEFAULT_GBRAIN_CLI
        self.resolved_cli = str(Path(self.approved_cli).resolve(strict=True))

    def tearDown(self) -> None:
        for name, value in self._runtime_constants.items():
            setattr(SPEC_MODULE, name, value)
        self.private_config_directory.cleanup()
        self.private_runtime_directory.cleanup()

    def cli_transport(self, **kwargs):
        kwargs.setdefault("bun_path", SPEC_MODULE.DEFAULT_BUN_CLI)
        return SPEC_MODULE.CliGBrainTransport(**kwargs)

    def test_transport_contract_is_versioned_and_dry_run_creates_no_markdown_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "receipt.json"
            result = SPEC_MODULE.import_deltas(
                self.snapshot, output_dir=root / "markdown", apply=False,
                approval_contract="x-bookmarks-import-approved-v1",
                transport=FakeTransport(),
            )
            self.assertEqual(result["status"], "prepared")
            self.assertEqual(result["transport"]["contract_version"], "gbrain-cli-markdown-v1")
            self.assertEqual(result["source"], "x-bookmarks")
            self.assertFalse((root / "markdown").exists())
            self.assertNotIn("example.invalid", json.dumps(result))

    def test_apply_requires_exact_approval_contract_and_rejects_wrong_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(SPEC_MODULE.ImportError, "approval"):
                SPEC_MODULE.import_deltas(
                    self.snapshot, output_dir=Path(directory) / "markdown", apply=True,
                    approval_contract="wrong", transport=FakeTransport(),
                )

    def test_accepted_is_distinct_from_indexed_until_source_scoped_canary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_transport = FakeTransport(canary=False)
            first = SPEC_MODULE.import_deltas(
                self.snapshot, output_dir=root / "markdown", apply=True,
                approval_contract="x-bookmarks-import-approved-v1", transport=first_transport,
            )
            self.assertEqual(first["status"], "accepted")
            self.assertEqual(first["canary"]["state"], "accepted")
            self.assertNotEqual(first["canary"]["state"], "indexed")

            indexed = SPEC_MODULE.import_deltas(
                self.snapshot, output_dir=root / "markdown", apply=True,
                approval_contract="x-bookmarks-import-approved-v1", transport=FakeTransport(canary=True),
            )
            self.assertEqual(indexed["canary"]["state"], "indexed")

    def test_idempotency_and_retries_are_visible_and_no_live_cli_is_needed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transport = FakeTransport(canary=True, failures=1)
            first = SPEC_MODULE.import_deltas(
                self.snapshot, output_dir=root / "markdown", apply=True,
                approval_contract="x-bookmarks-import-approved-v1", transport=transport,
                max_attempts=3,
            )
            second = SPEC_MODULE.import_deltas(
                self.snapshot, output_dir=root / "markdown", apply=True,
                approval_contract="x-bookmarks-import-approved-v1", transport=transport,
                max_attempts=3,
            )
            self.assertEqual(first["status"], "indexed")
            self.assertGreaterEqual(first["retry"]["attempts"], 2)
            self.assertRegex(first["idempotency"]["key"], r"^x-bookmarks:[a-f0-9]{64}$")
            self.assertEqual(second["status"], "no_action")
            self.assertTrue(second["idempotency"]["duplicate"])

    def test_duplicate_accepted_checkpoint_cannot_become_no_action_before_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transport = FakeTransport(canary=False)
            first = SPEC_MODULE.import_deltas(
                self.snapshot, output_dir=root / "markdown", apply=True,
                approval_contract="x-bookmarks-import-approved-v1", transport=transport,
            )
            second = SPEC_MODULE.import_deltas(
                self.snapshot, output_dir=root / "markdown", apply=True,
                approval_contract="x-bookmarks-import-approved-v1", transport=transport,
            )

            self.assertEqual("accepted", first["status"])
            self.assertEqual("accepted", second["status"])
            self.assertEqual("accepted", second["canary"]["state"])
            self.assertEqual({"reason": "canary_not_indexed"}, second["failure"])
            self.assertTrue(second["idempotency"]["duplicate"])

            transport.canary = True
            indexed = SPEC_MODULE.import_deltas(
                self.snapshot, output_dir=root / "markdown", apply=True,
                approval_contract="x-bookmarks-import-approved-v1", transport=transport,
            )
            self.assertEqual("indexed", indexed["status"])
            self.assertEqual("indexed", indexed["canary"]["state"])

    def test_partial_import_resumes_only_unaccepted_identities(self) -> None:
        class PartialTransport(FakeTransport):
            def __init__(self) -> None:
                super().__init__(canary=True)
                self.calls_count = 0

            def import_markdown_directory(self, *, source: str, documents: list[dict], idempotency_key: str) -> dict:
                self.calls_count += 1
                self.calls.append({"source": source, "documents": documents, "idempotency_key": idempotency_key})
                if self.calls_count == 1:
                    return {"status": "partial", "accepted": [documents[0]["identity"]], "rejected": []}
                return {"status": "accepted", "accepted": [doc["identity"] for doc in documents], "rejected": []}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transport = PartialTransport()
            first = SPEC_MODULE.import_deltas(
                self.snapshot, output_dir=root / "markdown", apply=True,
                approval_contract="x-bookmarks-import-approved-v1", transport=transport,
            )
            second = SPEC_MODULE.import_deltas(
                self.snapshot, output_dir=root / "markdown", apply=True,
                approval_contract="x-bookmarks-import-approved-v1", transport=transport,
            )
            self.assertEqual(first["status"], "partial")
            self.assertEqual(second["status"], "indexed")
            self.assertEqual(len(transport.calls), 2)
            self.assertEqual(len(transport.calls[1]["documents"]), 1)
            self.assertNotEqual(
                transport.calls[0]["documents"][0]["_directory"],
                transport.calls[1]["documents"][0]["_directory"],
            )

    def test_existing_native_source_filters_already_indexed_documents(self) -> None:
        existing_url = "https://example.invalid/status/one"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = root / "native"
            native.mkdir()
            (native / "existing.md").write_text(
                "---\nsource_url: " + existing_url + "\n---\nExisting evidence\n",
                encoding="utf-8",
            )
            transport = FakeTransport(canary=True)

            result = SPEC_MODULE.import_deltas(
                self.snapshot,
                output_dir=root / "markdown",
                existing_source_root=native,
                apply=True,
                approval_contract="x-bookmarks-import-approved-v1",
                transport=transport,
            )

            self.assertEqual(result["preexisting"]["matched_count"], 1)
            self.assertEqual(result["pending_count"], 0)
            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(len(transport.calls[0]["documents"]), 1)
            imported = transport.calls[0]["documents"][0]["identity"]
            existing = "bookmark:" + SPEC_MODULE.canonical_json_digest(existing_url)[:32]
            self.assertIn(existing, {
                row["canonical_source_identity"]
                for row in self.snapshot["observations"]
            })
            self.assertNotEqual(imported, existing)

    def test_all_preexisting_imports_still_require_an_indexed_canary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = root / "native"
            native.mkdir()
            for index, url in enumerate((
                "https://example.invalid/status/one",
                "https://example.invalid/status/two",
            )):
                (native / f"existing-{index}.md").write_text(
                    f"---\nsource_url: {url}\n---\nExisting evidence\n",
                    encoding="utf-8",
                )
            transport = FakeTransport(canary=False)

            result = SPEC_MODULE.import_deltas(
                self.snapshot,
                output_dir=root / "markdown",
                existing_source_root=native,
                apply=True,
                approval_contract="x-bookmarks-import-approved-v1",
                transport=transport,
            )

            self.assertEqual("accepted", result["status"])
            self.assertEqual("accepted", result["canary"]["state"])
            self.assertEqual([], transport.calls)

    def test_public_receipt_contains_only_opaque_identities_and_digests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = SPEC_MODULE.import_deltas(
                self.snapshot, output_dir=Path(directory) / "markdown", apply=False,
                approval_contract="x-bookmarks-import-approved-v1", transport=FakeTransport(),
            )
            encoded = json.dumps(result, sort_keys=True)
            self.assertNotIn("example.invalid", encoded)
            self.assertNotIn("Synthetic", encoded)

    def test_installed_cli_import_argv_and_result_mapping_are_exact_and_redacted(self) -> None:
        calls: list[dict] = []

        def runner(argv, **kwargs):
            calls.append({"argv": argv, "kwargs": kwargs})
            return SimpleNamespace(
                returncode=0,
                stdout="Found 4 markdown files\n" + json.dumps({"status": "success", "imported": 2, "skipped": 1, "errors": [], "chunks": 3, "total_files": 4}) + "\n",
                stderr="token=should-not-escape",
            )

        transport = self.cli_transport(
            cli_path=self.approved_cli, runner=runner, config_path=self.config_path,
        )
        result = transport.import_markdown_directory(
            source="x-bookmarks",
            documents=[{"identity": "bookmark:opaque", "_directory": "/tmp/owner-markdown"}],
            idempotency_key="x-bookmarks:" + "a" * 64,
        )
        expected_bun = str(SPEC_MODULE.DEFAULT_BUN_CLI.resolve(strict=True))
        self.assertEqual(calls[0]["argv"], [expected_bun, "--no-env-file", str(SPEC_MODULE.PINNED_OPERATION_HELPER)])
        self.assertEqual("import", json.loads(calls[0]["kwargs"]["input"])["operation"])
        self.assertEqual(calls[0]["kwargs"]["env"]["GBRAIN_SOURCE"], "x-bookmarks")
        self.assertEqual(calls[0]["kwargs"]["cwd"], str(SPEC_MODULE.ACCOUNT_HOME / ".gbrain"))
        self.assertEqual(
            set(calls[0]["kwargs"]["env"]),
            {"GBRAIN_CLI_PATH", "GBRAIN_CONFIG_SHA256", "GBRAIN_SOURCE", "HOME", "PATH", "TMPDIR"},
        )
        self.assertNotIn("--markdown-dir", calls[0]["argv"])
        self.assertNotIn("--idempotency-key", calls[0]["argv"])
        self.assertEqual(result["status"], "accepted")
        self.assertEqual((result["imported_count"], result["accepted_count"], result["skipped_count"], result["chunks"], result["total_files"]), (2, 3, 1, 3, 4))
        self.assertNotIn("token=should-not-escape", json.dumps(result))

    def test_installed_cli_import_errors_are_partial_or_failed_without_output_leak(self) -> None:
        partial = self.cli_transport(
            cli_path=self.approved_cli,
            config_path=self.config_path,
            runner=lambda *_args, **_kwargs: SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"status": "success", "imported": 1, "skipped": 0, "errors": [{"message": "secret"}], "chunks": 1, "total_files": 2}),
                stderr="secret",
            ),
        ).import_markdown_directory(
            source="x-bookmarks", documents=[{"identity": "bookmark:opaque", "_directory": "/tmp/owner-markdown"}], idempotency_key="x-bookmarks:" + "b" * 64,
        )
        failed = self.cli_transport(
            cli_path=self.approved_cli,
            config_path=self.config_path,
            runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=9, stdout="{}", stderr="raw provider failure"),
        ).import_markdown_directory(
            source="x-bookmarks", documents=[{"identity": "bookmark:opaque", "_directory": "/tmp/owner-markdown"}], idempotency_key="x-bookmarks:" + "c" * 64,
        )
        self.assertEqual((partial["status"], partial["error_count"]), ("partial", 1))
        self.assertEqual(failed, {"status": "failed"})
        self.assertNotIn("secret", json.dumps(partial))

    def test_installed_cli_canary_uses_source_scoped_env_and_identity_match(self) -> None:
        calls: list[dict] = []
        identity = "bookmark:" + "d" * 32

        def runner(argv, **kwargs):
            calls.append({"argv": argv, "kwargs": kwargs})
            self.assertEqual(kwargs["env"]["GBRAIN_SOURCE"], "x-bookmarks")
            self.assertEqual(kwargs["env"]["GBRAIN_CLI_PATH"], self.resolved_cli)
            self.assertRegex(kwargs["env"]["GBRAIN_CONFIG_SHA256"], r"^[a-f0-9]{64}$")
            self.assertEqual(kwargs["cwd"], str(SPEC_MODULE.ACCOUNT_HOME / ".gbrain"))
            return SimpleNamespace(returncode=0, stdout=json.dumps([{
                "source_id": "x-bookmarks",
                "slug": "bookmark-" + "d" * 32,
                "chunk_text": "Evidence identity: " + identity,
            }]), stderr="")

        transport = self.cli_transport(
            cli_path=self.approved_cli, runner=runner, config_path=self.config_path,
        )
        self.assertEqual(transport.text_canary(source="x-bookmarks", identity=identity)["status"], "indexed")
        self.assertEqual(calls[0]["argv"][0:2], [str(SPEC_MODULE.DEFAULT_BUN_CLI.resolve(strict=True)), "--no-env-file"])
        self.assertTrue(calls[0]["argv"][2].endswith("gbrain-pinned-operation.ts"))

        missing = self.cli_transport(
            cli_path=self.approved_cli,
            config_path=self.config_path,
            runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=json.dumps([{
                "source_id": "other-source",
                "slug": "bookmark-" + "d" * 32,
                "chunk_text": "Evidence identity: " + identity,
            }]), stderr=""),
        ).text_canary(source="x-bookmarks", identity=identity)
        self.assertEqual(missing["status"], "pending")

    def test_cli_source_write_and_preexisting_canary_ignore_ambient_overrides(self) -> None:
        calls: list[dict] = []
        identity = sorted(
            row["canonical_source_identity"] for row in self.snapshot["observations"]
        )[0]

        def runner(argv, **kwargs):
            calls.append({"argv": argv, "kwargs": kwargs})
            if json.loads(kwargs["input"]).get("operation") == "import":
                payload = {
                    "status": "success",
                    "imported": 1,
                    "skipped": 0,
                    "errors": [],
                    "chunks": 1,
                    "total_files": 1,
                }
            else:
                suffix = identity.removeprefix("bookmark:")
                payload = [{
                    "source_id": "x-bookmarks",
                    "slug": "bookmark-" + suffix,
                    "chunk_text": "Evidence identity: " + identity,
                }]
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

        transport = self.cli_transport(
            cli_path=self.approved_cli, runner=runner, config_path=self.config_path,
        )
        ambient_overrides = {
            "GBRAIN_HOME": "/tmp/hostile-home",
            "GBRAIN_DATABASE_URL": "postgresql://remote.invalid/other",
            "DATABASE_URL": "postgresql://remote.invalid/other",
            "PATH": "/tmp/hostile-path",
            "TMPDIR": "/tmp/hostile-tmp",
        }
        with mock.patch.dict(os.environ, ambient_overrides, clear=False):
            write_result = transport.import_markdown_directory(
                source="x-bookmarks",
                documents=[{"identity": identity, "_directory": "/tmp/owner-markdown"}],
                idempotency_key="x-bookmarks:" + "e" * 64,
            )
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                native = root / "native"
                native.mkdir()
                for index, url in enumerate((
                    "https://example.invalid/status/one",
                    "https://example.invalid/status/two",
                )):
                    (native / f"existing-{index}.md").write_text(
                        f"---\nsource_url: {url}\n---\nExisting evidence\n",
                        encoding="utf-8",
                    )
                canary_result = SPEC_MODULE.import_deltas(
                    self.snapshot,
                    output_dir=root / "markdown",
                    existing_source_root=native,
                    apply=True,
                    approval_contract="x-bookmarks-import-approved-v1",
                    transport=transport,
                )

        self.assertEqual("accepted", write_result["status"])
        self.assertEqual("no_action", canary_result["status"])
        self.assertEqual("indexed", canary_result["canary"]["state"])
        self.assertEqual(2, len(calls))
        for call in calls:
            environment = call["kwargs"]["env"]
            self.assertTrue({"GBRAIN_HOME", "GBRAIN_DATABASE_URL", "DATABASE_URL"}.isdisjoint(environment))
            self.assertEqual(SPEC_MODULE.FIXED_PATH, environment["PATH"])
            self.assertEqual("/private/tmp", environment["TMPDIR"])
            self.assertEqual(str(SPEC_MODULE.ACCOUNT_HOME / ".gbrain"), call["kwargs"]["cwd"])
            self.assertEqual([str(SPEC_MODULE.DEFAULT_BUN_CLI.resolve(strict=True)), "--no-env-file"], call["argv"][0:2])

    def test_cli_rejects_unpinned_bun_before_any_subprocess(self) -> None:
        calls = []
        transport = self.cli_transport(
            cli_path=self.approved_cli,
            bun_path="bun",
            config_path=self.config_path,
            runner=lambda *args, **kwargs: calls.append((args, kwargs)),
        )
        result = transport.import_markdown_directory(
            source="x-bookmarks",
            documents=[{"identity": "bookmark:opaque", "_directory": "/tmp/owner-markdown"}],
            idempotency_key="x-bookmarks:" + "f" * 64,
        )
        self.assertEqual({"status": "failed"}, result)
        self.assertEqual([], calls)

    def test_cli_rejects_absolute_alternate_bun_before_any_subprocess(self) -> None:
        alternate = Path(self.private_config_directory.name) / "bun"
        alternate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        alternate.chmod(0o700)
        calls = []
        transport = self.cli_transport(
            cli_path=self.approved_cli,
            bun_path=str(alternate),
            config_path=self.config_path,
            runner=lambda *args, **kwargs: calls.append((args, kwargs)),
        )
        result = transport.import_markdown_directory(
            source="x-bookmarks",
            documents=[{"identity": "bookmark:opaque", "_directory": "/tmp/owner-markdown"}],
            idempotency_key="x-bookmarks:" + "2" * 64,
        )
        self.assertEqual({"status": "failed"}, result)
        self.assertEqual([], calls)

    def test_cli_rejects_default_launcher_redirected_to_unexpected_script(self) -> None:
        unexpected = Path(self.private_config_directory.name) / "unexpected.ts"
        unexpected.write_text("process.exit(0)\n", encoding="utf-8")
        unexpected.chmod(0o700)
        launcher = Path(self.private_config_directory.name) / "gbrain"
        launcher.symlink_to(unexpected)
        calls = []
        with mock.patch.object(SPEC_MODULE, "DEFAULT_GBRAIN_CLI", str(launcher)):
            transport = self.cli_transport(
                config_path=self.config_path,
                runner=lambda *args, **kwargs: calls.append((args, kwargs)),
            )
            result = transport.import_markdown_directory(
                source="x-bookmarks",
                documents=[{"identity": "bookmark:opaque", "_directory": "/tmp/owner-markdown"}],
                idempotency_key="x-bookmarks:" + "1" * 64,
            )
        self.assertEqual({"status": "failed"}, result)
        self.assertEqual([], calls)

    def test_cli_rejects_nonapproved_gbrain_script_before_any_subprocess(self) -> None:
        calls = []
        transport = self.cli_transport(
            cli_path="/tmp/not-gbrain.ts",
            config_path=self.config_path,
            runner=lambda *args, **kwargs: calls.append((args, kwargs)),
        )
        result = transport.import_markdown_directory(
            source="x-bookmarks",
            documents=[{"identity": "bookmark:opaque", "_directory": "/tmp/owner-markdown"}],
            idempotency_key="x-bookmarks:" + "0" * 64,
        )
        self.assertEqual({"status": "failed"}, result)
        self.assertEqual([], calls)

    def test_apply_rejects_private_markdown_directory_inside_repository_before_creation(self) -> None:
        path = ROOT / ".u15-test-private-markdown"
        try:
            with self.assertRaisesRegex(SPEC_MODULE.ImportError, "outside the repository"):
                SPEC_MODULE.import_deltas(
                    self.snapshot, output_dir=path, apply=True,
                    approval_contract="x-bookmarks-import-approved-v1", transport=FakeTransport(),
                )
            self.assertFalse(path.exists())
        finally:
            if path.exists():
                raise AssertionError("private test path was unexpectedly created")

    def test_cli_exit_is_nonzero_when_apply_does_not_reach_indexed_state(self) -> None:
        class FailedTransport(FakeTransport):
            def import_markdown_directory(self, **_kwargs):
                return {"status": "failed"}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            snapshot.write_text(json.dumps(self.snapshot), encoding="utf-8")
            output = root / "receipt.json"
            native = root / "native"
            native.mkdir()
            with mock.patch.object(
                SPEC_MODULE,
                "CliGBrainTransport",
                return_value=FailedTransport(),
            ):
                exit_code = SPEC_MODULE.main([
                    "--snapshot", str(snapshot),
                    "--markdown-dir", str(root / "markdown"),
                    "--out", str(output),
                    "--existing-source-root", str(native),
                    "--apply",
                    "--approval-contract", "x-bookmarks-import-approved-v1",
                ])

            self.assertEqual(1, exit_code)
            self.assertEqual("failed", json.loads(output.read_text())["status"])

    def test_cli_apply_requires_existing_native_source_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot.json"
            snapshot.write_text(json.dumps(self.snapshot), encoding="utf-8")
            exit_code = SPEC_MODULE.main([
                "--snapshot", str(snapshot),
                "--markdown-dir", str(root / "markdown"),
                "--apply",
                "--approval-contract", "x-bookmarks-import-approved-v1",
            ])
            self.assertEqual(2, exit_code)
            self.assertFalse((root / "markdown").exists())

    def test_programmatic_live_cli_transport_requires_existing_native_inventory(self) -> None:
        calls = []
        transport = self.cli_transport(
            cli_path=self.approved_cli,
            config_path=self.config_path,
            runner=lambda *args, **kwargs: calls.append((args, kwargs)),
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(SPEC_MODULE.ImportError, "existing native source inventory"):
                SPEC_MODULE.import_deltas(
                    self.snapshot,
                    output_dir=Path(directory) / "markdown",
                    apply=True,
                    approval_contract="x-bookmarks-import-approved-v1",
                    transport=transport,
                )
        self.assertEqual([], calls)


if __name__ == "__main__":
    unittest.main()
