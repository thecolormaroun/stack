from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import stat
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run-stack-bookmark-curation.sh"
FRESHNESS_SPEC = importlib.util.spec_from_file_location(
    "field_theory_freshness", ROOT / "scripts" / "field_theory_freshness.py"
)
assert FRESHNESS_SPEC and FRESHNESS_SPEC.loader
FRESHNESS = importlib.util.module_from_spec(FRESHNESS_SPEC)
FRESHNESS_SPEC.loader.exec_module(FRESHNESS)

COLLECTOR_SPEC = importlib.util.spec_from_file_location(
    "collector_for_freshness", ROOT / "scripts" / "collect-bookmark-candidates.py"
)
assert COLLECTOR_SPEC and COLLECTOR_SPEC.loader
COLLECTOR = importlib.util.module_from_spec(COLLECTOR_SPEC)
COLLECTOR_SPEC.loader.exec_module(COLLECTOR)


class FieldTheoryFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root.chmod(0o700)
        self.db = self.root / "bookmarks.db"
        connection = sqlite3.connect(self.db)
        connection.execute("CREATE TABLE bookmarks (tweet_id TEXT, synced_at TEXT, text TEXT)")
        connection.executemany(
            "INSERT INTO bookmarks VALUES (?, ?, ?)",
            [("tweet-2", "2026-08-30T02:00:00Z", "private body"), ("tweet-1", "2026-08-29T02:00:00Z", "another body")],
        )
        connection.commit()
        connection.close()
        self.receipt = self.root / "refresh" / "field-theory-refresh-receipt.json"
        self.receipt.parent.mkdir(mode=0o700)
        self.receipt.parent.chmod(0o700)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def binding(self) -> dict:
        return FRESHNESS.read_database_binding(self.db)

    def write_receipt(self, *, generated_at: datetime | None = None, **changes: object) -> None:
        database_digest = FRESHNESS.file_sha256(self.db)
        empty_state = {
            "md": {"exists": False, "file_count": 0, "total_size": 0, "content_hash": "", "truncated": False},
            "library": {"exists": False, "file_count": 0, "total_size": 0, "content_hash": "", "truncated": False},
            "commands": {"exists": False, "file_count": 0, "total_size": 0, "content_hash": "", "truncated": False},
            "media_cache": {"exists": False, "file_count": 0, "total_size": 0, "metadata_hash": "", "truncated": False, "transactional": True, "snapshot": "apfs_copy_on_write_clone"},
            "root_files": {"bookmarks_db": {"exists": True, "size": self.db.stat().st_size, "sha256": database_digest}},
        }
        payload = {
            "schema": FRESHNESS.RECEIPT_SCHEMA,
            "run_id": "test-run",
            "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
            "outcome": "applied_verified",
            "authoritative": True,
            "deterministic_checks_passed": True,
            "source": {"id": "field-theory"},
            "database_binding": self.binding(),
            "state_binding_before": empty_state,
            "state_binding_after": empty_state,
            "media": {"state": "bounded"},
            "stages": {"wiki": "verified"},
            "stage_contract": {"expected": ["field-theory-sync"], "complete": True, "missing": [], "invalid_states": []},
            "safe_restart": {"snapshot_created": True, "media_cache_transactional": True},
        }
        payload.update(changes)
        self.receipt.write_text(json.dumps(payload), encoding="utf-8")
        self.receipt.chmod(0o600)

    def test_digest_is_shared_tuple_list_canonical_json(self) -> None:
        rows = [("tweet-1", "2026-08-29T02:00:00Z"), ("tweet-2", "2026-08-30T02:00:00Z")]
        expected = FRESHNESS.hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.assertEqual(expected, self.binding()["identity_revision_sha256"])

    def test_fresh_bound_receipt_passes_without_reading_bookmark_body(self) -> None:
        self.write_receipt()
        reads: list[tuple[object, object]] = []
        real_connect = FRESHNESS.sqlite3.connect

        def traced_connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            connection.set_authorizer(
                lambda action, arg1, arg2, _db, _trigger: reads.append((arg1, arg2))
                or FRESHNESS.sqlite3.SQLITE_OK
            )
            return connection

        with mock.patch.object(FRESHNESS.sqlite3, "connect", side_effect=traced_connect):
            result = FRESHNESS.verify_receipt(self.receipt, self.db)
        self.assertTrue(result["ok"])
        self.assertEqual("fresh_bound", result["reason"])
        self.assertNotIn(("text", "bookmarks"), reads)

    def test_stale_receipt_blocks(self) -> None:
        self.write_receipt(generated_at=datetime.now(timezone.utc) - timedelta(hours=36, seconds=1))
        self.assertEqual("receipt_stale", FRESHNESS.verify_receipt(self.receipt, self.db)["reason"])

    def test_partial_or_wrong_schema_receipt_blocks(self) -> None:
        self.write_receipt(deterministic_checks_passed=False)
        self.assertEqual("deterministic_checks_failed", FRESHNESS.verify_receipt(self.receipt, self.db)["reason"])
        self.write_receipt(schema="field-theory-refresh-receipt/v0")
        self.assertEqual("receipt_schema_mismatch", FRESHNESS.verify_receipt(self.receipt, self.db)["reason"])
        self.write_receipt(authoritative=False)
        self.assertEqual("receipt_not_authoritative", FRESHNESS.verify_receipt(self.receipt, self.db)["reason"])
        self.write_receipt(stage_contract={"expected": ["field-theory-sync"], "complete": False, "missing": ["field-theory-index"], "invalid_states": []})
        self.assertEqual("stage_contract_incomplete", FRESHNESS.verify_receipt(self.receipt, self.db)["reason"])

    def test_wrong_mode_and_path_substitution_block(self) -> None:
        self.write_receipt()
        self.receipt.chmod(0o644)
        self.assertEqual("receipt_permissions_invalid", FRESHNESS.verify_receipt(self.receipt, self.db)["reason"])
        self.receipt.chmod(0o600)
        replacement = self.root / "replacement"
        replacement.mkdir(mode=0o700)
        self.receipt.unlink()
        self.receipt.symlink_to(replacement / "receipt.json")
        self.assertEqual("receipt_path_substituted", FRESHNESS.verify_receipt(self.receipt, self.db)["reason"])

    def test_database_revision_drift_blocks(self) -> None:
        self.write_receipt()
        connection = sqlite3.connect(self.db)
        connection.execute("UPDATE bookmarks SET synced_at = ? WHERE tweet_id = ?", ("2026-08-30T03:00:00Z", "tweet-1"))
        connection.commit()
        connection.close()
        self.assertEqual("database_binding_mismatch", FRESHNESS.verify_receipt(self.receipt, self.db)["reason"])

    def test_database_body_drift_blocks_even_when_identity_revision_is_unchanged(self) -> None:
        self.write_receipt()
        connection = sqlite3.connect(self.db)
        connection.execute("UPDATE bookmarks SET text = ? WHERE tweet_id = ?", ("changed body", "tweet-1"))
        connection.commit()
        connection.close()
        self.assertEqual(
            "database_file_binding_mismatch",
            FRESHNESS.verify_receipt(self.receipt, self.db)["reason"],
        )

    def test_preflight_source_requires_the_allowlisted_owner_path(self) -> None:
        owner_root = self.root / "owner"
        owner_root.mkdir(mode=0o700)
        expected = owner_root / FRESHNESS.DEFAULT_RECEIPT_RELATIVE
        expected.parent.mkdir(parents=True, mode=0o700)
        expected.parent.chmod(0o700)
        self.write_receipt()
        expected.write_bytes(self.receipt.read_bytes())
        expected.chmod(0o600)
        source = {
            "id": "field-theory",
            "adapter": "field_theory",
            "enabled": True,
            "paths": [str(self.db)],
            "field_theory_contract": {"freshness_receipt": str(expected)},
        }
        with mock.patch.object(FRESHNESS, "owner_home", return_value=owner_root):
            self.assertTrue(FRESHNESS.preflight_source(source)["ok"])
            source["field_theory_contract"]["freshness_receipt"] = str(self.root / "elsewhere.json")
            self.assertEqual("receipt_path_not_allowlisted", FRESHNESS.preflight_source(source)["reason"])

    def test_collector_blocks_before_creating_or_mutating_ledger(self) -> None:
        owner_root = self.root / "owner"
        owner_root.mkdir(mode=0o700)
        expected = owner_root / FRESHNESS.DEFAULT_RECEIPT_RELATIVE
        expected.parent.mkdir(parents=True, mode=0o700)
        expected.parent.chmod(0o700)
        self.write_receipt(generated_at=datetime.now(timezone.utc) - timedelta(hours=37))
        expected.write_bytes(self.receipt.read_bytes())
        expected.chmod(0o600)
        source_path = self.root / "sources.json"
        source_path.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "id": "field-theory",
                            "adapter": "field_theory",
                            "paths": [str(self.db)],
                            "field_theory_contract": {"freshness_receipt": str(expected)},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        policy = self.root / "policy.json"
        policy.write_text("{}", encoding="utf-8")
        ledger = self.root / "state" / "ledger.sqlite"
        output = self.root / "collection.json"
        with mock.patch.object(COLLECTOR.field_theory_freshness, "owner_home", return_value=owner_root):
            result = COLLECTOR.main(
                [
                    "--sources",
                    str(source_path),
                    "--policy",
                    str(policy),
                    "--ledger",
                    str(ledger),
                    "--out",
                    str(output),
                    "--apply",
                ]
            )
        self.assertEqual(75, result)
        self.assertFalse(ledger.exists())
        receipt = json.loads(output.read_text(encoding="utf-8"))
        self.assertFalse(receipt["complete"])
        self.assertEqual("field_theory_freshness_failed", receipt["upstream_preflight"]["reason"])

    def test_runner_persists_failed_preflight_before_returning_non_success(self) -> None:
        state = self.root / "stack-state"
        source_path = self.root / "sources.json"
        source_path.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "id": "field-theory",
                            "adapter": "field_theory",
                            "paths": [str(self.db)],
                            "field_theory_contract": {"freshness_receipt": str(self.root / "substituted.json")},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        env = {
            **os.environ,
            "STACK_BOOKMARK_STATE_ROOT": str(state),
            "STACK_BOOKMARK_SOURCES": str(source_path),
        }
        result = subprocess.run(
            [str(RUNNER), "collection", "--apply"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        self.assertEqual(1, result.returncode)
        receipts = list((state / "receipts").glob("collection-*.json"))
        self.assertEqual(1, len(receipts))
        receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
        self.assertEqual("partial", receipt["receipt_type"])
        self.assertFalse(receipt["complete"])
        self.assertEqual("field_theory_freshness_failed", receipt["reason"])
        self.assertFalse((state / "bookmark-intake.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
