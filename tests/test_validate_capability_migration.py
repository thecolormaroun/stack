"""Focused safety contracts for the non-mutating U3 migration gate."""
from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_capability_migration", ROOT / "scripts" / "validate-capability-migration.py"
)
assert SPEC and SPEC.loader
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class CapabilityMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audit = MIGRATION.load_json(ROOT / "artifacts/audits/2026-07-18-u2/capability-audit.json")
        self.catalog = MIGRATION.load_json(ROOT / "artifacts/migrations/2026-07-18-pre-migration-catalog.json")
        self.reviewed_migration = MIGRATION.load_json(ROOT / "registry/migrations/2026-07-18-estate-refactor.json")
        self.migration = MIGRATION.build_draft_map(
            self.audit,
            self.catalog,
            audit_path="artifacts/audits/2026-07-18-u2/capability-audit.json",
            catalog_path="artifacts/migrations/2026-07-18-pre-migration-catalog.json",
        )

    def test_recorded_reviewed_migration_is_valid(self) -> None:
        MIGRATION.validate_migration(self.reviewed_migration, self.audit, self.catalog)

    def decision(self, disposition: str) -> dict[str, object]:
        return next(item for item in self.migration["decisions"] if item["proposed_disposition"] == disposition)

    def test_invalid_source_fails(self) -> None:
        invalid = copy.deepcopy(self.migration)
        invalid["decisions"][0]["source"]["skill_path"] = "skills/not-registered/SKILL.md"

        with self.assertRaisesRegex(MIGRATION.MigrationError, "unregistered source"):
            MIGRATION.validate_migration(invalid, self.audit, self.catalog)

    def test_apply_approved_move_and_merge_require_targets_and_receipts(self) -> None:
        for disposition, expected in (("move", "missing destination_target"), ("merge", "missing merge_target")):
            with self.subTest(disposition=disposition):
                invalid = copy.deepcopy(self.migration)
                decision = next(item for item in invalid["decisions"] if item["proposed_disposition"] == disposition)
                decision["review_state"] = "approved"
                decision["review_decision"] = disposition

                with self.assertRaisesRegex(MIGRATION.MigrationError, expected):
                    MIGRATION.validate_migration(invalid, self.audit, self.catalog)

    def test_reviewed_targeted_decision_can_await_apply_prerequisites(self) -> None:
        reviewed = copy.deepcopy(self.migration)
        decision = next(item for item in reviewed["decisions"] if item["proposed_disposition"] == "move")
        decision["review_state"] = "reviewed"
        decision["review_decision"] = "move"

        MIGRATION.validate_migration(reviewed, self.audit, self.catalog)

    def test_review_can_override_a_proposal_with_rationale_and_matching_lifecycle(self) -> None:
        reviewed = copy.deepcopy(self.migration)
        decision = next(item for item in reviewed["decisions"] if item["proposed_disposition"] == "merge")
        decision["review_state"] = "reviewed"
        decision["review_decision"] = "keep"
        decision["review_rationale"] = "Keep this side as the canonical member of the overlap pair."
        decision["lifecycle"]["to"] = "candidate"

        MIGRATION.validate_migration(reviewed, self.audit, self.catalog)

        decision["review_rationale"] = None
        with self.assertRaisesRegex(MIGRATION.MigrationError, "override requires review_rationale"):
            MIGRATION.validate_migration(reviewed, self.audit, self.catalog)

    def test_keep_does_not_bypass_activation_validation(self) -> None:
        decision = next(item for item in self.migration["decisions"] if item["proposed_disposition"] == "keep")
        self.assertEqual(decision["lifecycle"], {"from": "candidate", "to": "candidate"})

    def test_source_collision_fails(self) -> None:
        invalid = copy.deepcopy(self.migration)
        invalid["decisions"][1]["source"] = copy.deepcopy(invalid["decisions"][0]["source"])

        with self.assertRaisesRegex(MIGRATION.MigrationError, "source collision"):
            MIGRATION.validate_migration(invalid, self.audit, self.catalog)

    def test_apply_denies_decisions_without_separate_apply_approval(self) -> None:
        with self.assertRaisesRegex(MIGRATION.MigrationError, "not apply-approved"):
            MIGRATION.validate_migration(self.migration, self.audit, self.catalog, apply=True)

    def test_dry_run_is_deterministic_and_complete(self) -> None:
        MIGRATION.validate_migration(self.migration, self.audit, self.catalog)
        first = MIGRATION.canonical_json({"dry_run": True, "actions": MIGRATION.dry_run_actions(self.migration)})
        second = MIGRATION.canonical_json({"dry_run": True, "actions": MIGRATION.dry_run_actions(self.migration)})

        self.assertEqual(first, second)
        self.assertEqual(len(MIGRATION.dry_run_actions(self.migration)), 145)
        self.assertIn("merge_target", next(item for item in MIGRATION.dry_run_actions(self.migration) if item["proposed_disposition"] == "merge")["required_before_apply"])

    def test_matching_post_migration_catalog_has_no_remaining_actions(self) -> None:
        post_catalog = copy.deepcopy(self.catalog)
        lifecycle_by_name = {item["source"]["canonical_name"]: item["lifecycle"]["to"] for item in self.migration["decisions"]}
        post_catalog["capabilities"] = [
            {**capability, "lifecycle": lifecycle_by_name[capability["canonical_name"]]}
            for capability in post_catalog["capabilities"]
            if lifecycle_by_name[capability["canonical_name"]] != "external"
        ]

        self.assertEqual(MIGRATION.post_migration_actions(self.migration, post_catalog), [])

    def test_review_packet_contains_every_source_shaping_decision_within_cap(self) -> None:
        packet = MIGRATION.build_review_packet(self.migration)
        second = MIGRATION.build_review_packet(self.migration, batch_index=2)
        self.assertEqual(packet["total_consequential_decision_count"], 23)
        self.assertEqual(packet["consequential_decision_count"], 20)
        self.assertEqual(second["consequential_decision_count"], 3)
        self.assertEqual(packet["batch_count"], 2)
        self.assertEqual(packet["held_pending_evidence_count"], 6)
        self.assertEqual(packet["unchanged_keep_count"], 122)
        self.assertLessEqual(len(packet["decisions"]), 20)
        self.assertEqual(
            {decision["proposed_disposition"] for decision in packet["decisions"] + second["decisions"]},
            {"move", "merge", "hold"},
        )


if __name__ == "__main__":
    unittest.main()
