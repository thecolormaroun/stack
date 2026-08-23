"""Fixture-first tests for the dry-run-default x-bookmarks GBrain handoff."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path


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
                stdout=json.dumps({"status": "success", "imported": 2, "skipped": 1, "errors": [], "chunks": 3, "total_files": 4}),
                stderr="token=should-not-escape",
            )

        transport = SPEC_MODULE.CliGBrainTransport(cli_path="gbrain-test", runner=runner)
        result = transport.import_markdown_directory(
            source="x-bookmarks",
            documents=[{"identity": "bookmark:opaque", "_directory": "/tmp/owner-markdown"}],
            idempotency_key="x-bookmarks:" + "a" * 64,
        )
        self.assertEqual(calls[0]["argv"], ["gbrain-test", "import", "/tmp/owner-markdown", "--source-id", "x-bookmarks", "--json"])
        self.assertEqual(calls[0]["kwargs"]["env"]["GBRAIN_SOURCE"], "x-bookmarks")
        self.assertNotIn("--markdown-dir", calls[0]["argv"])
        self.assertNotIn("--idempotency-key", calls[0]["argv"])
        self.assertEqual(result["status"], "accepted")
        self.assertEqual((result["imported_count"], result["accepted_count"], result["skipped_count"], result["chunks"], result["total_files"]), (2, 3, 1, 3, 4))
        self.assertNotIn("token=should-not-escape", json.dumps(result))

    def test_installed_cli_import_errors_are_partial_or_failed_without_output_leak(self) -> None:
        partial = SPEC_MODULE.CliGBrainTransport(
            cli_path="gbrain-test",
            runner=lambda *_args, **_kwargs: SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"status": "success", "imported": 1, "skipped": 0, "errors": [{"message": "secret"}], "chunks": 1, "total_files": 2}),
                stderr="secret",
            ),
        ).import_markdown_directory(
            source="x-bookmarks", documents=[{"identity": "bookmark:opaque", "_directory": "/tmp/owner-markdown"}], idempotency_key="x-bookmarks:" + "b" * 64,
        )
        failed = SPEC_MODULE.CliGBrainTransport(
            cli_path="gbrain-test",
            runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=9, stdout="{}", stderr="raw provider failure"),
        ).import_markdown_directory(
            source="x-bookmarks", documents=[{"identity": "bookmark:opaque", "_directory": "/tmp/owner-markdown"}], idempotency_key="x-bookmarks:" + "c" * 64,
        )
        self.assertEqual((partial["status"], partial["error_count"]), ("partial", 1))
        self.assertEqual(failed, {"status": "failed"})
        self.assertNotIn("secret", json.dumps(partial))

    def test_installed_cli_canary_uses_source_scoped_env_and_identity_match(self) -> None:
        calls: list[list[str]] = []
        identity = "bookmark:" + "d" * 32

        def runner(argv, **kwargs):
            calls.append(argv)
            self.assertEqual(kwargs["env"]["GBRAIN_SOURCE"], "x-bookmarks")
            return SimpleNamespace(returncode=0, stdout="result contains " + identity + "\n", stderr="")

        transport = SPEC_MODULE.CliGBrainTransport(cli_path="gbrain-test", runner=runner)
        self.assertEqual(transport.text_canary(source="x-bookmarks", identity=identity)["status"], "indexed")
        self.assertEqual(calls, [["gbrain-test", "search", identity, "--limit", "1"]])

        missing = SPEC_MODULE.CliGBrainTransport(
            cli_path="gbrain-test",
            runner=lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="other result", stderr=""),
        ).text_canary(source="x-bookmarks", identity=identity)
        self.assertEqual(missing["status"], "pending")

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


if __name__ == "__main__":
    unittest.main()
