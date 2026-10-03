"""Fixture-first tests for bounded, resumable private bookmark backfill."""

from __future__ import annotations

import copy
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "bookmark-sources" / "field-theory-pages.json"
SPEC = importlib.util.spec_from_file_location("backfill_bookmark_history", ROOT / "scripts" / "backfill-bookmark-history.py")
assert SPEC and SPEC.loader
BACKFILL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACKFILL)


class BookmarkBackfillTests(unittest.TestCase):
    def test_main_accepts_canonical_sources_document(self) -> None:
        source = json.loads(FIXTURE.read_text(encoding="utf-8"))
        source["adapter"] = "field_theory"
        source["enabled"] = True
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "bookmark-sources.json"
            output_path = root / "receipt.json"
            input_path.write_text(
                json.dumps({"version": 1, "sources": [source]}),
                encoding="utf-8",
            )

            exit_code = BACKFILL.main([
                "--input", str(input_path),
                "--state", str(root / "checkpoint.json"),
                "--ledger", str(root / "ledger.sqlite"),
                "--out", str(output_path),
            ])

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                json.loads(output_path.read_text(encoding="utf-8"))["status"],
                "prepared",
            )
            self.assertFalse((root / "checkpoint.json").exists())
            self.assertFalse((root / "ledger.sqlite").exists())

    def test_approved_backfill_reaches_terminal_cursor_and_second_run_is_zero_delta(self) -> None:
        source = json.loads(FIXTURE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "checkpoint.json"
            ledger = root / "owner-ledger.sqlite"
            first = BACKFILL.backfill_source(
                source, state_path=state, ledger_path=ledger,
                apply=True, approval_contract="u15-backfill-approved-v1",
            )
            second = BACKFILL.backfill_source(
                source, state_path=state, ledger_path=ledger,
                apply=True, approval_contract="u15-backfill-approved-v1",
            )

            self.assertEqual(first["status"], "complete")
            self.assertTrue(first["terminal_cursor"])
            self.assertEqual(first["observation_count"], 2)
            self.assertEqual(second["status"], "no_action")
            self.assertTrue(second["zero_delta"])
            self.assertEqual(second["pages_read"], 0)
            self.assertEqual(second["observation_count"], 0)
            self.assertTrue(state.is_file())
            self.assertTrue(ledger.is_file())

    def test_partial_page_persists_resume_cursor_then_resumes_without_restarting(self) -> None:
        partial = json.loads(FIXTURE.read_text(encoding="utf-8"))
        partial["pages"][1] = {
            "page_ordinal": 1,
            "requested_cursor": "cursor-one",
            "error": {"status": 429, "retry_after_seconds": 10},
        }
        complete = json.loads(FIXTURE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "checkpoint.json"
            ledger = root / "owner-ledger.sqlite"
            first = BACKFILL.backfill_source(
                partial, state_path=state, ledger_path=ledger,
                apply=True, approval_contract="u15-backfill-approved-v1",
            )
            resumed = BACKFILL.backfill_source(
                complete, state_path=state, ledger_path=ledger,
                apply=True, approval_contract="u15-backfill-approved-v1",
            )

            self.assertEqual(first["status"], "partial")
            self.assertEqual(first["resume_cursor_digest"], BACKFILL.canonical_json_digest("cursor-one"))
            self.assertEqual(first["pages_read"], 1)
            self.assertEqual(resumed["status"], "complete")
            self.assertEqual(resumed["pages_read"], 1)
            self.assertEqual(resumed["observation_count"], 1)
            self.assertEqual(resumed["first_page_ordinal"], 1)
            self.assertEqual(first["stored_count"], 1)
            with sqlite3.connect(ledger) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM source_observations").fetchone()[0], 2)

    def test_trailing_pages_after_terminal_never_write_or_certify_coverage(self) -> None:
        source = json.loads(FIXTURE.read_text(encoding="utf-8"))
        source["pages"][0]["returned_cursor"] = None
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(BACKFILL.BackfillError, "pages after terminal cursor"):
                BACKFILL.backfill_source(source, state_path=root / "checkpoint.json", ledger_path=root / "ledger.sqlite",
                    apply=True, approval_contract="u15-backfill-approved-v1")
            self.assertFalse((root / "checkpoint.json").exists())
            self.assertFalse((root / "ledger.sqlite").exists())

    def test_changed_partial_prefix_restarts_with_reset_cursor(self) -> None:
        partial = json.loads(FIXTURE.read_text(encoding="utf-8"))
        partial["pages"][1] = {"page_ordinal": 1, "requested_cursor": "cursor-one", "error": {"status": 429}}
        changed = json.loads(FIXTURE.read_text(encoding="utf-8"))
        changed["pages"][0]["rows"][0].update(tweet_id="new-prefix", url="https://example.invalid/new-prefix")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kwargs = {"state_path": root / "checkpoint.json", "ledger_path": root / "ledger.sqlite",
                      "apply": True, "approval_contract": "u15-backfill-approved-v1"}
            BACKFILL.backfill_source(partial, **kwargs)
            resumed = BACKFILL.backfill_source(changed, **kwargs)
            self.assertEqual(resumed["status"], "complete")
            self.assertEqual(resumed["first_page_ordinal"], 0)
            self.assertEqual(resumed["observation_count"], 2)
            with sqlite3.connect(kwargs["ledger_path"]) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM source_observations").fetchone()[0], 3)

    def test_same_source_revision_changed_content_appends_without_overwrite(self) -> None:
        source = json.loads(FIXTURE.read_text(encoding="utf-8"))
        changed = copy.deepcopy(source)
        changed["pages"][1]["rows"][0]["text"] = "Synthetic content changed without new source revision"
        new_row = copy.deepcopy(changed["pages"][0]["rows"][0])
        new_row.update(tweet_id="new-before-conflict", url="https://example.invalid/new-before-conflict")
        changed["pages"][0]["rows"].append(new_row)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kwargs = {"state_path": root / "checkpoint.json", "ledger_path": root / "ledger.sqlite",
                      "apply": True, "approval_contract": "u15-backfill-approved-v1"}
            BACKFILL.backfill_source(source, **kwargs)
            with sqlite3.connect(kwargs["ledger_path"]) as connection:
                original = connection.execute("SELECT * FROM source_observations ORDER BY evidence_id").fetchall()
            result = BACKFILL.backfill_source(changed, **kwargs)
            self.assertEqual(result["stored_count"], 2)
            with sqlite3.connect(kwargs["ledger_path"]) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM source_observations").fetchone()[0], 4)
                for record in original:
                    self.assertEqual(connection.execute("SELECT * FROM source_observations WHERE evidence_id=?", (record[0],)).fetchone(), record)
            repeated = BACKFILL.backfill_source(changed, **kwargs)
            self.assertTrue(repeated["zero_delta"])

    def test_forged_identity_content_conflict_rolls_back_every_insert(self) -> None:
        source = json.loads(FIXTURE.read_text(encoding="utf-8"))
        first_row = source["pages"][0]["rows"][0]
        original_public, original = BACKFILL.normalize_observation(first_row, "field-theory", "original")
        changed_row = dict(first_row, text="Different synthetic evidence")
        public, changed = BACKFILL.normalize_observation(changed_row, "field-theory", "changed")
        public["evidence_id"] = original_public["evidence_id"]
        new_row = dict(first_row, tweet_id="new", url="https://example.invalid/new")
        _, new_record = BACKFILL.normalize_observation(new_row, "field-theory", "new")
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.sqlite"
            BACKFILL.store_owner_records(ledger, [original])
            with self.assertRaisesRegex(BACKFILL.CorpusError, "evidence content conflict"):
                BACKFILL.store_owner_records(ledger, [new_record, changed])
            with sqlite3.connect(ledger) as connection:
                self.assertEqual(connection.execute("SELECT count(*) FROM source_observations").fetchone()[0], 1)

    def test_partial_checkpoint_never_skips_prefix_under_different_source_config(self) -> None:
        partial = json.loads(FIXTURE.read_text(encoding="utf-8"))
        partial["pages"][1] = {"page_ordinal": 1, "requested_cursor": "cursor-one", "error": {"status": 429}}
        changed = json.loads(FIXTURE.read_text(encoding="utf-8"))
        changed["source_id"] = "second-source"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kwargs = {"state_path": root / "checkpoint.json", "ledger_path": root / "ledger.sqlite",
                      "apply": True, "approval_contract": "u15-backfill-approved-v1"}
            BACKFILL.backfill_source(partial, **kwargs)
            resumed = BACKFILL.backfill_source(changed, **kwargs)
            self.assertEqual(resumed["status"], "complete")
            self.assertEqual(resumed["first_page_ordinal"], 0)
            self.assertEqual(resumed["observation_count"], 2)
            with sqlite3.connect(kwargs["ledger_path"]) as connection:
                count = connection.execute("SELECT count(*) FROM source_observations WHERE source_id = 'second-source'").fetchone()[0]
                self.assertEqual(count, 2)

    def test_terminal_and_partial_checkpoints_require_bound_persisted_ledger_coverage(self) -> None:
        source = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for partial in (False, True):
            for replaced in (False, True):
                with self.subTest(partial=partial, replaced=replaced), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    kwargs = {"state_path": root / "checkpoint.json", "ledger_path": root / "ledger.sqlite",
                              "apply": True, "approval_contract": "u15-backfill-approved-v1"}
                    BACKFILL.backfill_source(source, max_pages=1 if partial else None, **kwargs)
                    if replaced:
                        kwargs["ledger_path"] = root / "different-ledger.sqlite"
                    else:
                        with sqlite3.connect(kwargs["ledger_path"]) as connection:
                            connection.execute("DELETE FROM source_observations")
                    repaired = BACKFILL.backfill_source(source, **kwargs)
                    self.assertEqual(repaired["status"], "complete")
                    self.assertEqual(repaired["first_page_ordinal"], 0)
                    self.assertEqual(repaired["stored_count"], 2)
                    self.assertFalse(repaired["zero_delta"])
                    self.assertTrue(BACKFILL.backfill_source(source, **kwargs)["zero_delta"])

    def test_changed_empty_source_is_not_a_zero_delta(self) -> None:
        source = json.loads(FIXTURE.read_text(encoding="utf-8"))
        empty = copy.deepcopy(source)
        empty["pages"] = [{"page_ordinal": 0, "requested_cursor": None, "returned_cursor": None, "rows": []}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kwargs = {"state_path": root / "checkpoint.json", "ledger_path": root / "ledger.sqlite",
                      "apply": True, "approval_contract": "u15-backfill-approved-v1"}
            original = BACKFILL.backfill_source(source, **kwargs)
            changed = BACKFILL.backfill_source(empty, **kwargs)
            self.assertNotEqual(original["source_digest"], changed["source_digest"])
            self.assertEqual(changed["status"], "complete")
            self.assertEqual(changed["observation_count"], 0)
            self.assertFalse(changed["zero_delta"])
            self.assertTrue(BACKFILL.backfill_source(empty, **kwargs)["zero_delta"])

    def test_terminal_checkpoint_binds_loaded_rows_not_only_unchanged_source_config(self) -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        source = {"source_id": "field-theory", "path": "/owner/bookmarks.db"}
        original_pages = fixture["pages"]
        changed_pages = copy.deepcopy(original_pages)
        added_row = copy.deepcopy(changed_pages[0]["rows"][0])
        added_row.update(tweet_id="999000111222333", url="https://x.com/i/status/999000111222333")
        changed_pages[0]["rows"].append(added_row)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kwargs = {"state_path": root / "checkpoint.json", "ledger_path": root / "ledger.sqlite",
                      "apply": True, "approval_contract": "u15-backfill-approved-v1"}
            with mock.patch.object(BACKFILL, "load_source_pages", return_value=(original_pages, {})):
                original = BACKFILL.backfill_source(source, **kwargs)
            with mock.patch.object(BACKFILL, "load_source_pages", return_value=(changed_pages, {})):
                changed = BACKFILL.backfill_source(source, **kwargs)
                repeated = BACKFILL.backfill_source(source, **kwargs)
            self.assertNotEqual(original["source_digest"], changed["source_digest"])
            self.assertEqual(changed["status"], "complete")
            self.assertEqual(changed["first_page_ordinal"], 0)
            self.assertEqual(changed["observation_count"], 3)
            self.assertEqual(changed["stored_count"], 1)
            self.assertEqual(repeated["status"], "no_action")
            self.assertTrue(repeated["zero_delta"])

    def test_backfill_requires_exact_approval_and_dry_run_does_not_create_state_or_ledger(self) -> None:
        source = json.loads(FIXTURE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "owner-only" / "checkpoint.json"
            ledger = root / "owner-only" / "ledger.sqlite"
            result = BACKFILL.backfill_source(
                source, state_path=state, ledger_path=ledger,
                apply=False, approval_contract="u15-backfill-approved-v1",
            )
            self.assertEqual(result["status"], "prepared")
            self.assertFalse(state.exists())
            self.assertFalse(ledger.exists())

    def test_apply_rejects_checkpoint_and_ledger_inside_repository_before_creation(self) -> None:
        source = json.loads(FIXTURE.read_text(encoding="utf-8"))
        state = ROOT / ".u15-test-backfill-checkpoint"
        ledger = ROOT / ".u15-test-backfill-ledger.sqlite"
        try:
            with self.assertRaisesRegex(BACKFILL.BackfillError, "outside the repository"):
                BACKFILL.backfill_source(
                    source, state_path=state, ledger_path=ledger,
                    apply=True, approval_contract="u15-backfill-approved-v1",
                )
            self.assertFalse(state.exists())
            self.assertFalse(ledger.exists())
        finally:
            for path in (state, ledger):
                if path.exists():
                    raise AssertionError(f"private test path was unexpectedly created: {path}")

            with self.assertRaisesRegex(BACKFILL.BackfillError, "approval"):
                BACKFILL.backfill_source(
                    source, state_path=state, ledger_path=ledger,
                    apply=True, approval_contract="wrong",
                )
            self.assertFalse(state.exists())
            self.assertFalse(ledger.exists())


if __name__ == "__main__":
    unittest.main()
