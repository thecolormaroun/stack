from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "stack_weekly_intelligence_auto_promotion",
    ROOT / "scripts" / "run-stack-weekly-intelligence.py",
)
assert SPEC and SPEC.loader
WEEKLY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WEEKLY)


class WeeklyAutomaticPromotionContractTests(unittest.TestCase):
    def test_activation_policy_grants_only_the_weekly_design_contract(self) -> None:
        policy = json.loads(
            (ROOT / "config" / "capability-activation-policy.json").read_text()
        )

        automatic = policy["automatic_weekly_design_promotion"]
        self.assertEqual("active", automatic["state"])
        self.assertEqual(
            "weekly-design-auto-promotion-approved-v1",
            automatic["authorization_contract"],
        )
        self.assertEqual(
            ["skills/**/SKILL.md", "skills/**/references/**/*.md"],
            automatic["allowed_path_patterns"],
        )
        self.assertTrue(automatic["pull_request"]["automatic_merge"])
        self.assertTrue(automatic["pull_request"]["head_digest_binding"])
        self.assertTrue(automatic["publication"]["merged_origin_main_only"])
        self.assertTrue(automatic["publication"]["atomic_installer_only"])
        self.assertTrue(automatic["publication"]["rollback_receipt_required"])
        self.assertEqual(
            [
                "direct-main-commit",
                "vendor-or-imported-edit",
                "route-or-command-edit",
                "source-corpus-mutation",
                "credential-access",
                "paid-provider-fallback",
                "destructive-cleanup",
                "upstream-pin-change",
            ],
            automatic["prohibited_effects"],
        )

        # The default candidate lane remains non-publishing. Only the exact
        # weekly authorization contract may cross the automatic tail.
        self.assertFalse(policy["materialization"]["draft_pr_authority"])
        self.assertFalse(policy["materialization"]["runtime_publication_authority"])
        self.assertFalse(policy["publication"]["candidate_may_publish"])

    def test_strong_model_and_uncapped_automatic_promotion_are_active(self) -> None:
        config = WEEKLY.load_config()

        self.assertEqual("gpt-5.6-sol", config["scheduler"]["model"])
        self.assertEqual("high", config["scheduler"]["reasoning_effort"])
        self.assertTrue(config["analysis_budget"]["authorized"])
        self.assertEqual("concurrent_model_contexts", config["analysis_budget"]["unit"])
        self.assertEqual(3, config["analysis_budget"]["maximum"])

        promotion = config["automatic_promotion"]
        self.assertEqual("active", promotion["state"])
        self.assertEqual(
            "weekly-design-auto-promotion-approved-v1",
            promotion["authorization_contract"],
        )
        self.assertNotIn("maximum_candidates_per_run", promotion)
        self.assertNotIn("maximum_changed_files", promotion)
        self.assertNotIn("maximum_total_bytes", promotion)
        self.assertEqual(
            ["skills/**/SKILL.md", "skills/**/references/**/*.md"],
            promotion["allowed_path_patterns"],
        )
        self.assertEqual(
            [
                "material-evidence",
                "isolated-materialization",
                "frozen-design-eval",
                "full-repository-tests",
                "fresh-independent-review",
                "pull-request-ci",
                "merge-verification",
                "runtime-publication",
                "rollback-receipt",
            ],
            promotion["required_gates"],
        )
        self.assertEqual("no_action", promotion["weak_candidate_outcome"])
        self.assertEqual("rejected_no_queue", promotion["rejected_candidate_outcome"])
        self.assertEqual("retry_with_alert", promotion["operational_failure_outcome"])

        self.assertEqual(
            {
                "evidence": "bounded_model_analysis_approved",
                "promotion": "automatic_evaluated",
                "publication": "automatic_after_merge",
                "upstream_maintenance": "separate_approved_workflow",
            },
            config["approval"],
        )

    def test_automation_prompt_owns_the_full_automatic_tail(self) -> None:
        config = WEEKLY.load_config()
        prompt = (ROOT / config["scheduler"]["prompt_path"]).read_text(encoding="utf-8")

        required_phrases = (
            "Do not stop at `awaiting_approval`",
            "every independently material candidate",
            "Process candidates sequentially",
            "material-evidence",
            "frozen-design-eval",
            "fresh independent review",
            "pull request",
            "merge verification",
            "bootstrap-stack.py --install",
            "stack-doctor.py",
            "rollback receipt",
            "rejected_no_queue",
            "no_action",
        )
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, prompt)
        self.assertLess(
            prompt.index("scripts/list-pending-weekly-design-promotions.py"),
            prompt.index("scripts/run-stack-weekly-live.py"),
        )
        self.assertIn(
            "persist its terminal receipt, then refresh and verify `origin/main`, before starting the next candidate",
            prompt,
        )
        self.assertIn("candidate-content/<after-digest>.utf8", prompt)
        self.assertIn("Candidate receipts are append-only", prompt)

    def test_candidate_schema_has_no_automatic_file_or_content_ceiling(self) -> None:
        schema = json.loads(
            (ROOT / "registry" / "capability-change.schema.json").read_text()
        )
        edits = schema["properties"]["edits"]
        edit = schema["$defs"]["edit"]

        self.assertNotIn("maxItems", edits)
        self.assertNotIn("maxLength", edit["properties"]["content"])
        self.assertIn("content_file", edit["properties"])
        self.assertIn("oneOf", edit)
        manual_contract = schema["allOf"][0]["else"]["properties"]["edits"]
        automatic_contract = schema["allOf"][0]["then"]["properties"]["edits"]
        self.assertEqual(5, manual_contract["maxItems"])
        self.assertEqual(65536, manual_contract["items"]["properties"]["content"]["maxLength"])
        self.assertIn("content_file", automatic_contract["items"]["required"])
        lineage = schema["$defs"]["source_lineage"]
        campaign_fields = {
            "campaign_run_id",
            "campaign_receipt_digest",
            "design_packet_artifact_digest",
            "retrieval_artifact_digest",
            "candidate_evaluation_artifact_digest",
        }
        self.assertTrue(campaign_fields <= set(lineage["properties"]))
        self.assertEqual(
            campaign_fields - {"campaign_run_id"},
            set(lineage["dependentRequired"]["campaign_run_id"]),
        )

    def test_coordinator_prepares_the_automatic_tail_without_manual_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            state.chmod(0o700)
            now = 1_777_000_000.0
            maintenance = {
                "schema_version": 1,
                "task_id": "stack-maintenance",
                "run_id": "fixture-maintenance",
                "mode": "audit",
                "manual_audit": False,
                "observed_at": WEEKLY._now_iso(now - 60),
                "input_fingerprint": "c" * 64,
                "provider_refs": [],
                "catalog_digest": "d" * 64,
                "policy_digest": "e" * 64,
                "changed_paths_digest": "f" * 64,
                "checks": {"fixture_only": True},
                **{
                    key: {"status": "fixture_only"}
                    for key in (
                        "checkout_state",
                        "pr_state",
                        "approval_state",
                        "cleanup_state",
                        "thread_state",
                    )
                },
                "terminal_classification": "no_action",
                "receipt_persisted": True,
            }

            coordinator = WEEKLY.WeeklyIntelligenceCoordinator(
                state_dir=state,
                adapters=lambda stage, context: {"status": "prepared"},
                now=now,
            )
            receipt = coordinator.run(
                source_manifest={"state": "complete", "set_digest": "a" * 64},
                source_delta={"state": "changed", "delta_digest": "b" * 64},
                model_config={"model": "approved-automation"},
                prompt_config={"revision": "fixture-v1"},
                eval_config={"profile": "design-learning-v1"},
                maintenance_receipt=maintenance,
            )

        self.assertEqual("prepared", receipt["terminal_state"])
        self.assertEqual("automatic_promotion_pending", receipt["reason_code"])
        self.assertEqual(
            "Continue the approved automatic evaluation and publication tail; weak or rejected candidates create no review queue.",
            receipt["safe_restart"],
        )
        self.assertFalse(receipt["publication"]["promotion_approved"])

    def test_automatic_promotion_policy_drift_fails_closed(self) -> None:
        config = json.loads((ROOT / "config" / "weekly-intelligence.json").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "weekly.json"
            config["automatic_promotion"]["maximum_changed_files"] = 3
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(
                WEEKLY.WeeklyIntelligenceError,
                "automatic_promotion_contract_invalid",
            ):
                WEEKLY.load_config(path)


if __name__ == "__main__":
    unittest.main()
