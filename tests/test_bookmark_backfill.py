"""Fixture-first tests for bounded, resumable private bookmark backfill."""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "bookmark-sources" / "field-theory-pages.json"
SPEC = importlib.util.spec_from_file_location("backfill_bookmark_history", ROOT / "scripts" / "backfill-bookmark-history.py")
assert SPEC and SPEC.loader
BACKFILL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BACKFILL)


class BookmarkBackfillTests(unittest.TestCase):
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
