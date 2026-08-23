"""Fixture-first tests for the private bookmark completeness contract."""

from __future__ import annotations

import copy
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "bookmark-sources" / "field-theory-pages.json"
PARITY = ROOT / "tests" / "fixtures" / "bookmark-sources" / "x-parity-snapshot.json"
SPEC = importlib.util.spec_from_file_location("reconcile_bookmark_sources", ROOT / "scripts" / "reconcile-bookmark-sources.py")
assert SPEC and SPEC.loader
RECONCILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECONCILE)


class BookmarkCompletenessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.policy = {"version": 1, "source_contract": {"media_roots": [], "network": "disabled"}}

    def test_canonical_json_digest_is_order_independent_and_sha256(self) -> None:
        self.assertEqual(
            RECONCILE.canonical_json_digest({"b": 2, "a": 1}),
            RECONCILE.canonical_json_digest({"a": 1, "b": 2}),
        )
        self.assertRegex(RECONCILE.canonical_json_digest({"a": 1}), r"^[a-f0-9]{64}$")

    def test_complete_snapshot_proves_pages_folders_revisions_media_and_opaque_projection(self) -> None:
        snapshot = RECONCILE.reconcile_sources(self.source, self.policy)

        self.assertEqual(snapshot["completeness_state"], "complete")
        self.assertEqual(snapshot["page_count"], 2)
        self.assertEqual(snapshot["observation_count"], 2)
        self.assertTrue(snapshot["cursor_exhausted"])
        self.assertEqual(snapshot["folder_coverage"]["state"], "complete")
        self.assertEqual(snapshot["revision_coverage"]["state"], "complete")
        self.assertEqual(snapshot["media_coverage"]["state"], "complete")
        self.assertEqual(snapshot["zero_delta"]["state"], "not_run")
        encoded = json.dumps(snapshot, sort_keys=True)
        self.assertNotIn("example.invalid", encoded)
        self.assertNotIn("Synthetic", encoded)
        self.assertNotIn("tweet-one", encoded)

    def test_page_receipts_and_dispositions_are_opaque_for_unavailable_media_and_deleted_rows(self) -> None:
        source = copy.deepcopy(self.source)
        source["pages"][0]["rows"][0]["media"] = [{"id": "private-media", "unavailable_reason": "owner-only"}]
        source["pages"][1]["rows"][0]["disposition"] = "deleted"
        snapshot = RECONCILE.reconcile_sources(source, self.policy)

        receipt = snapshot["page_receipts"][0]
        self.assertRegex(receipt["source_identity"], r"^source:[a-f0-9]{16,64}$")
        self.assertRegex(receipt["query_contract_digest"], r"^[a-f0-9]{64}$")
        self.assertEqual(snapshot["observations"][0]["media"]["state"], "unavailable")
        deleted = snapshot["observations"][1]["canonical_source_identity"]
        self.assertIn(deleted, snapshot["dispositions"]["deleted"])
        encoded = json.dumps(receipt, sort_keys=True)
        self.assertNotIn("example.invalid", encoded)
        self.assertNotIn("cursor-one", encoded)
        self.assertNotIn("private-media", encoded)

    def test_field_theory_sqlite_reads_only_allowlisted_bookmarks_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "bookmarks.sqlite"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE bookmarks (id TEXT, tweet_id TEXT, url TEXT, synced_at TEXT, media_count INTEGER)")
            connection.execute("CREATE TABLE secret_unrelated (value TEXT)")
            connection.execute("INSERT INTO bookmarks VALUES ('b1', 't1', 'https://example.invalid/one', '2026-08-21T00:00:00Z', 2)")
            connection.execute("INSERT INTO bookmarks VALUES ('b2', 't2', 'https://example.invalid/two', '2026-08-21T00:00:00Z', 0)")
            connection.execute("INSERT INTO secret_unrelated VALUES ('never-read-secret')")
            connection.commit()
            connection.close()
            source = {
                "source_id": "field-theory",
                "paths": [str(database)],
                "field_theory_contract": {
                    "table": "bookmarks",
                    "columns": ["id", "tweet_id", "url", "synced_at", "media_count"],
                    "media_roots": [],
                },
            }
            snapshot = RECONCILE.reconcile_sources(source, self.policy)
            encoded = json.dumps(snapshot, sort_keys=True)
            self.assertEqual(snapshot["observation_count"], 2)
            self.assertEqual(snapshot["observations"][0]["media"]["state"], "metadata_only")
            self.assertEqual(snapshot["observations"][0]["media"]["count"], 2)
            self.assertEqual(len(snapshot["observations"][0]["media_item_digests"]), 1)
            self.assertEqual(snapshot["observations"][0]["media"]["byte_count"], 0)
            self.assertEqual(snapshot["observations"][0]["media"]["missing_fields"], ["byte_count", "digest", "mime_type"])
            self.assertEqual(snapshot["observations"][1]["media"]["state"], "not_present")
            self.assertEqual(snapshot["observations"][1]["media"]["count"], 0)
            self.assertEqual(snapshot["media_coverage"]["state"], "partial")
            self.assertEqual(snapshot["page_receipts"][0]["media_resolution"]["state"], "partial")
            self.assertEqual(snapshot["dispositions"]["unavailable_media"], [snapshot["observations"][0]["canonical_source_identity"]])
            self.assertNotIn("never-read-secret", encoded)
            self.assertNotIn("secret_unrelated", encoded)

    def test_optional_x_is_networkless_and_rejects_unapproved_or_plaintext_credentials(self) -> None:
        self.assertEqual(RECONCILE.validate_optional_x_api({"enabled": False})["state"], "disabled")
        valid = {
            "enabled": True,
            "os_secret_ref": "os-secret:x-bookmarks-read",
            "scopes": ["bookmark.read"],
            "rotation": {"rotation_id": "rotation-1", "revocation_state": "not-revoked"},
        }
        self.assertEqual(RECONCILE.validate_optional_x_api(valid)["state"], "not_approved")
        approved = RECONCILE.validate_optional_x_api(valid, approved=True, spend_approved=True)
        self.assertEqual(approved["state"], "approved_contract")
        self.assertNotIn("secret_ref", approved)
        self.assertRegex(approved["scope_digest"], r"^[a-f0-9]{64}$")
        with self.assertRaisesRegex(RECONCILE.CorpusError, "scope"):
            RECONCILE.validate_optional_x_api({**valid, "scopes": ["bookmark.read", "bookmark.write"]}, approved=True, spend_approved=True)
        with self.assertRaisesRegex(RECONCILE.CorpusError, "rotation"):
            RECONCILE.validate_optional_x_api({key: value for key, value in valid.items() if key != "rotation"}, approved=True, spend_approved=True)
        for key in ("token", "access_token", "refresh_token", "client_secret", "api_key", "bearer_token", "authorization"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(RECONCILE.CorpusError, "plaintext"):
                    RECONCILE.validate_optional_x_api({"enabled": False, key: "secret"})
        with self.assertRaisesRegex(RECONCILE.CorpusError, "plaintext"):
            RECONCILE.validate_optional_x_api({"enabled": False, "rotation": {"access_token": "secret"}})

    def test_cursor_cycle_is_truthfully_partial_and_retains_safe_resume_digest(self) -> None:
        source = copy.deepcopy(self.source)
        source["pages"][1]["returned_cursor"] = "cursor-one"
        snapshot = RECONCILE.reconcile_sources(source, self.policy)

        self.assertEqual(snapshot["completeness_state"], "partial")
        self.assertFalse(snapshot["cursor_exhausted"])
        self.assertEqual(snapshot["failure"]["reason"], "cursor_cycle")
        self.assertRegex(snapshot["resume_cursor_digest"], r"^[a-f0-9]{64}$")

    def test_rate_limit_page_is_partial_with_resume_cursor_and_no_network(self) -> None:
        source = copy.deepcopy(self.source)
        source["pages"][1] = {
            "page_ordinal": 1,
            "requested_cursor": "cursor-one",
            "error": {"status": 429, "retry_after_seconds": 30},
        }
        snapshot = RECONCILE.reconcile_sources(source, self.policy)

        self.assertEqual(snapshot["completeness_state"], "partial")
        self.assertEqual(snapshot["failure"]["reason"], "rate_limited")
        self.assertEqual(snapshot["resume_cursor_digest"], RECONCILE.canonical_json_digest("cursor-one"))
        self.assertEqual(snapshot["page_receipts"][1]["retry"]["status"], "rate_limited")

    def test_set_diffs_ignore_order_and_report_missing_extra_and_revised(self) -> None:
        left = RECONCILE.reconcile_sources(self.source, self.policy)
        parity = json.loads(PARITY.read_text(encoding="utf-8"))
        diff = RECONCILE.compare_source_sets(left["observations"], parity["observations"])

        self.assertEqual(diff["missing"], [left["observations"][1]["canonical_source_identity"]])
        self.assertEqual(len(diff["extra"]), 1)
        self.assertEqual(diff["revised"], [])

        parity["observations"][0]["folder_ids"] = ["folder-other"]
        folder_diff = RECONCILE.compare_source_sets(left["observations"], parity["observations"])
        self.assertEqual(len(folder_diff["folder_membership_diffs"]), 1)

    def test_dry_run_does_not_create_missing_ledger_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing_ledger = root / "owner-only" / "bookmark-ledger.sqlite"
            output = root / "snapshot.json"
            result = RECONCILE.main([
                "--input", str(FIXTURE), "--policy-inline", json.dumps(self.policy),
                "--ledger", str(missing_ledger), "--out", str(output),
            ])
            self.assertEqual(result, 0)
            self.assertFalse(missing_ledger.exists())
            self.assertTrue(output.is_file())
            self.assertNotIn("example.invalid", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
