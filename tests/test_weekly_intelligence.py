from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "stack_weekly_intelligence",
    ROOT / "scripts" / "run-stack-weekly-intelligence.py",
)
assert SPEC and SPEC.loader
WEEKLY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WEEKLY)


class WeeklyIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.state = Path(self.temporary.name)
        self.state.chmod(0o700)
        self.now = 1_777_000_000.0
        self.maintenance = {
            "task_id": "stack-maintenance",
            "observed_at": WEEKLY._now_iso(self.now - 60),
            "terminal_classification": "no_action",
        }
        self.inputs = {
            "source_manifest": {"state": "complete", "set_digest": "a" * 64},
            "source_delta": {"state": "changed", "delta_digest": "b" * 64},
            "model_config": {"model": "local-or-approved"},
            "prompt_config": {"revision": "fixture-v1"},
            "eval_config": {"profile": "design-learning-v1"},
            "maintenance_receipt": self.maintenance,
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def successful_adapter(calls: list[str]):
        def run(stage: str, context: dict) -> dict:
            calls.append(stage)
            if context["provider_egress"] != "deny":
                raise AssertionError("provider egress must stay denied")
            return {"status": "prepared"}

        return run

    def coordinator(self, calls: list[str] | None = None):
        calls = calls if calls is not None else []
        return WEEKLY.WeeklyIntelligenceCoordinator(
            state_dir=self.state,
            adapters=self.successful_adapter(calls),
            now=self.now,
        )

    def test_default_pipeline_fails_closed_without_real_stage_adapters(self) -> None:
        receipt = WEEKLY.run_campaign(
            state_dir=self.state,
            now=self.now,
            **self.inputs,
        )
        self.assertEqual("failed", receipt["terminal_state"])
        self.assertEqual("source_intake_adapter_not_configured", receipt["reason_code"])
        self.assertEqual(
            {"status": "not_published", "promotion_approved": False},
            receipt["publication"],
        )
        self.assertFalse((ROOT / "artifacts" / receipt["run_id"]).exists())

    def test_changed_campaign_persists_safe_artifacts_and_stops_at_review(self) -> None:
        before = subprocess.check_output(
            ["git", "-C", str(ROOT), "status", "--porcelain=v1", "--untracked-files=all"],
            text=True,
        )
        calls: list[str] = []
        receipt = self.coordinator(calls).run(**self.inputs)
        after = subprocess.check_output(
            ["git", "-C", str(ROOT), "status", "--porcelain=v1", "--untracked-files=all"],
            text=True,
        )

        self.assertEqual("awaiting_approval", receipt["terminal_state"])
        self.assertEqual(list(WEEKLY.STAGE_IDS), calls)
        self.assertEqual(before, after)
        self.assertFalse(receipt["publication"]["promotion_approved"])
        self.assertIsNotNone(receipt["report_path"])
        for stage in receipt["stages"]:
            artifact = self.state / stage["artifact_path"]
            self.assertTrue(artifact.is_file(), stage["id"])
            self.assertEqual(0o600, stat.S_IMODE(artifact.stat().st_mode))
        self.assertEqual(0o700, stat.S_IMODE(self.state.stat().st_mode))

    def test_identical_second_run_is_a_true_model_noop(self) -> None:
        calls: list[str] = []
        coordinator = self.coordinator(calls)
        first = coordinator.run(**self.inputs)
        call_count = len(calls)
        second = coordinator.run(**self.inputs, now=self.now + 30)
        third = coordinator.run(**self.inputs, now=self.now + 60)

        self.assertEqual("awaiting_approval", first["terminal_state"])
        self.assertEqual("no_action", second["terminal_state"])
        self.assertEqual("no_action", third["terminal_state"])
        self.assertEqual(first["input_fingerprint"], second["input_fingerprint"])
        self.assertEqual(first["input_fingerprint"], third["input_fingerprint"])
        self.assertEqual(call_count, len(calls))
        self.assertTrue(all(stage["status"] == "reused" for stage in second["stages"]))
        self.assertTrue(all(stage["status"] == "reused" for stage in third["stages"]))
        self.assertFalse(second["publication"]["promotion_approved"])

    def test_partial_failure_preserves_checkpoints_and_resume_only_retries_tail(self) -> None:
        first_calls: list[str] = []

        def fail_retrieval(stage: str, context: dict) -> dict:
            first_calls.append(stage)
            if stage == "retrieval":
                return {
                    "status": "failed",
                    "reason_code": "fixture_retrieval_failure",
                    "retry_class": "transient",
                }
            return {"status": "prepared"}

        coordinator = WEEKLY.WeeklyIntelligenceCoordinator(
            state_dir=self.state,
            adapters=fail_retrieval,
            now=self.now,
        )
        partial = coordinator.run(**self.inputs)
        self.assertEqual("partial", partial["terminal_state"])
        self.assertEqual(["source_intake", "design_packet", "retrieval"], first_calls)

        resumed_calls: list[str] = []
        coordinator.adapters = self.successful_adapter(resumed_calls)
        resumed = coordinator.run(
            **self.inputs,
            run_id=partial["run_id"],
            resume=True,
            now=self.now + 60,
        )
        self.assertEqual("awaiting_approval", resumed["terminal_state"])
        self.assertEqual(
            ["retrieval", "candidate_evaluation", "maintenance_link", "report_receipt"],
            resumed_calls,
        )
        self.assertEqual("reused", resumed["stages"][0]["status"])
        self.assertEqual("reused", resumed["stages"][1]["status"])

    def test_concurrent_lease_yields_duplicate_run_no_action(self) -> None:
        calls: list[str] = []
        coordinator = self.coordinator(calls)
        coordinator._prepare_state()
        _, _, fingerprint, _, _ = coordinator._make_inputs(**self.inputs)
        run_id = coordinator._new_run_id(None, fingerprint)
        store, _ = coordinator._store_and_run(run_id, resume=False)
        try:
            self.assertTrue(
                store.claim_child(run_id, "source_intake", "other-owner", now=self.now)
            )
            receipt = coordinator.run(**self.inputs)
        finally:
            store.close()

        self.assertEqual("no_action", receipt["terminal_state"])
        self.assertEqual("duplicate_run", receipt["reason_code"])
        self.assertEqual("alert", receipt["health"]["status"])
        self.assertEqual([], calls)

    def test_three_identical_blockers_open_circuit_until_manual_clear(self) -> None:
        calls: list[str] = []

        def blocked(stage: str, context: dict) -> dict:
            calls.append(stage)
            return {
                "status": "failed",
                "reason_code": "same_non_transient_blocker",
                "retry_class": "non_transient",
            }

        coordinator = WEEKLY.WeeklyIntelligenceCoordinator(
            state_dir=self.state,
            adapters=blocked,
            now=self.now,
        )
        receipts = [
            coordinator.run(**self.inputs, now=self.now + offset)
            for offset in range(4)
        ]
        self.assertEqual("open", receipts[2]["circuit"]["status"])
        self.assertEqual("circuit_open", receipts[3]["reason_code"])
        self.assertEqual(1, len(calls))

        coordinator.adapters = self.successful_adapter([])
        recovered = coordinator.run(
            **self.inputs,
            run_id=receipts[0]["run_id"],
            resume=True,
            manual_clear=True,
            now=self.now + 5,
        )
        self.assertEqual("awaiting_approval", recovered["terminal_state"])
        self.assertEqual("not_struck", recovered["circuit"]["status"])

    def test_stale_maintenance_alert_never_launches_maintenance(self) -> None:
        stale = {
            **self.maintenance,
            "observed_at": WEEKLY._now_iso(self.now - 8 * 24 * 60 * 60),
        }
        calls: list[str] = []
        receipt = self.coordinator(calls).run(
            **{**self.inputs, "maintenance_receipt": stale}
        )
        self.assertEqual("blocked", receipt["terminal_state"])
        self.assertEqual("alert_stale", receipt["maintenance"]["status"])
        self.assertEqual("alert_stale", receipt["reason_code"])
        self.assertEqual(list(WEEKLY.STAGE_IDS), calls)
        source = (ROOT / "scripts" / "run-stack-weekly-intelligence.py").read_text()
        self.assertNotIn("stack_maintenance.run", source)
        self.assertNotIn("stack-maintenance.py audit", source)

    def test_eight_day_health_requires_persisted_scheduler_contract_and_receipt(self) -> None:
        coordinator = self.coordinator([])
        coordinator.run(**self.inputs)
        config = WEEKLY.load_config()
        evidence = {
            "enabled": True,
            "approval": True,
            "persisted_contract": True,
            "contract_digest": WEEKLY.scheduler_contract_digest(config),
        }
        healthy = WEEKLY.eight_day_health_check(
            state_dir=self.state,
            config=config,
            now=self.now + 7 * 24 * 60 * 60,
            scheduler_evidence=evidence,
        )
        stale = WEEKLY.eight_day_health_check(
            state_dir=self.state,
            config=config,
            now=self.now + 9 * 24 * 60 * 60,
            scheduler_evidence=evidence,
        )
        self.assertEqual("pass", healthy["status"])
        self.assertEqual("alert", stale["status"])
        self.assertEqual("campaign", stale["blocking_stage"])

    def test_owner_local_input_files_are_required(self) -> None:
        inputs = self.state / "inputs.json"
        inputs.write_text(json.dumps({"source_manifest": {}}), encoding="utf-8")
        inputs.chmod(0o644)
        with self.assertRaisesRegex(WEEKLY.WeeklyIntelligenceError, "mode"):
            WEEKLY._read_owner_json(inputs)
        inputs.chmod(0o600)
        self.assertEqual({"source_manifest": {}}, WEEKLY._read_owner_json(inputs))

    def test_receipt_schema_and_scheduler_config_are_strict_and_disabled(self) -> None:
        schema = json.loads(
            (ROOT / "registry" / "weekly-campaign-receipt.schema.json").read_text()
        )
        config = WEEKLY.load_config()
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            sorted(WEEKLY.TERMINAL_STATES),
            sorted(schema["properties"]["terminal_state"]["enum"]),
        )
        self.assertFalse(config["scheduler"]["enabled"])
        self.assertTrue(config["scheduler"]["approval_required"])
        self.assertEqual("deny", config["provider_egress"])
        self.assertFalse(config["analysis_budget"]["authorized"])


if __name__ == "__main__":
    unittest.main()
