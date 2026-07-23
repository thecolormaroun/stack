from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("record_review", ROOT / "scripts/record-capability-review.py")
assert SPEC and SPEC.loader
REVIEWER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REVIEWER)


def fixture():
    audit = {
        "human_approval": "not granted",
        "capabilities": [
            {"canonical_name": "plain", "proposed_disposition": "keep", "review_state": "unreviewed"},
            {"canonical_name": "held", "proposed_disposition": "hold", "review_state": "unreviewed"},
            {"canonical_name": "duplicate", "proposed_disposition": "merge", "review_state": "unreviewed"},
            {"canonical_name": "outside", "proposed_disposition": "move", "review_state": "unreviewed"},
        ],
    }
    decisions = []
    for name, proposed in (("plain", "keep"), ("held", "hold"), ("duplicate", "merge"), ("outside", "move")):
        decisions.append({
            "source": {"canonical_name": name},
            "proposed_disposition": proposed,
            "review_state": "unreviewed",
            "review_decision": None,
            "review_rationale": None,
            "lifecycle": {"from": "candidate", "to": "candidate"},
            "merge_target": None,
            "compatibility_alias": None,
        })
    migration = {
        "migration_id": "fixture",
        "status": "draft",
        "human_approval": "not granted",
        "source": {"audit_digest": "old"},
        "decisions": decisions,
    }
    review = {
        "schema_version": "capability-migration-review-decision/v1",
        "migration_id": "fixture",
        "reviewed_by": "Reviewer",
        "reviewed_at": "2026-07-19",
        "approval_statement": "Approve all",
        "scope": "disposition-review-only",
        "batch_confirm_unchanged_keeps": True,
        "decisions": [
            {"canonical_name": "held", "decision": "keep", "rationale": "Supports build work."},
            {"canonical_name": "duplicate", "decision": "merge", "merge_target": "plain", "rationale": "Duplicate."},
            {"canonical_name": "outside", "decision": "move", "rationale": "Outside scope."},
        ],
    }
    return audit, migration, review


class RecordCapabilityReviewTests(unittest.TestCase):
    def test_records_batch_keeps_overrides_and_scoped_receipt(self):
        audit, migration, review = fixture()
        updated_audit, updated_migration, receipt = REVIEWER.record_review(audit, migration, review)

        by_name = {row["source"]["canonical_name"]: row for row in updated_migration["decisions"]}
        self.assertEqual("active", by_name["plain"]["lifecycle"]["to"])
        self.assertEqual("active", by_name["held"]["lifecycle"]["to"])
        self.assertEqual("deprecated", by_name["duplicate"]["lifecycle"]["to"])
        self.assertEqual({"alias": "duplicate", "canonical_target": "plain"}, by_name["duplicate"]["compatibility_alias"])
        self.assertEqual("external", by_name["outside"]["lifecycle"]["to"])
        self.assertEqual("reviewed", by_name["outside"]["review_state"])
        self.assertEqual("approved", updated_audit["human_approval"])
        self.assertFalse(receipt["source_mutation_authorized"])
        self.assertEqual("destination-and-consumer-proof", receipt["next_gate"])

    def test_missing_consequential_decision_fails_closed(self):
        audit, migration, review = fixture()
        review["decisions"].pop()
        with self.assertRaisesRegex(REVIEWER.ReviewError, "exactly once"):
            REVIEWER.record_review(audit, migration, review)

    def test_review_scope_cannot_authorize_source_mutation(self):
        audit, migration, review = fixture()
        review["scope"] = "source-mutation"
        with self.assertRaisesRegex(REVIEWER.ReviewError, "disposition-review-only"):
            REVIEWER.record_review(audit, migration, review)

    def test_rerun_does_not_silently_reapprove(self):
        audit, migration, review = fixture()
        updated_audit, updated_migration, _receipt = REVIEWER.record_review(audit, migration, review)
        with self.assertRaisesRegex(REVIEWER.ReviewError, "unapproved draft"):
            REVIEWER.record_review(updated_audit, updated_migration, review)


if __name__ == "__main__":
    unittest.main()
