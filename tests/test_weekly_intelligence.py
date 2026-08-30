from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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
        self.state = Path(self.temporary.name).resolve()
        self.state.chmod(0o700)
        self.now = 1_777_000_000.0
        self.maintenance = {
            "schema_version": 1,
            "task_id": "stack-maintenance",
            "run_id": "fixture-maintenance",
            "mode": "audit",
            "manual_audit": False,
            "observed_at": WEEKLY._now_iso(self.now - 60),
            "input_fingerprint": "c" * 64,
            "provider_refs": [],
            "catalog_digest": "d" * 64,
            "policy_digest": "e" * 64,
            "changed_paths_digest": "f" * 64,
            "checks": {"fixture_only": True},
            **{key: {"status": "fixture_only"} for key in (
                "checkout_state", "pr_state", "approval_state", "cleanup_state", "thread_state"
            )},
            "terminal_classification": "no_action",
            "receipt_persisted": True,
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

    def automation_file(self, **changes) -> Path:
        config = WEEKLY.load_config()
        scheduler = config["scheduler"]
        prompt = (ROOT / scheduler["prompt_path"]).read_text(encoding="utf-8")
        values = {
            "id": scheduler["automation_id"],
            "kind": "cron",
            "status": "ACTIVE",
            "rrule": scheduler["rrule"],
            "model": scheduler["model"],
            "reasoning_effort": scheduler["reasoning_effort"],
            "execution_environment": scheduler["execution_environment"],
            "project_id": scheduler["project_id"],
            "prompt": prompt.removesuffix("\n"),
            "cwd": str(WEEKLY.DEFAULT_AUTOMATION_WORKDIR),
        }
        values.update(changes)
        path = self.state / "automation-root" / scheduler["automation_id"] / "automation.toml"
        path.parent.mkdir(parents=True, mode=0o700)
        path.write_text(
            "\n".join((
                f'id = {json.dumps(values["id"])}',
                f'kind = {json.dumps(values["kind"])}',
                f'prompt = {json.dumps(values["prompt"])}',
                f'status = {json.dumps(values["status"])}',
                f'rrule = {json.dumps(values["rrule"])}',
                f'model = {json.dumps(values["model"])}',
                f'reasoning_effort = {json.dumps(values["reasoning_effort"])}',
                f'execution_environment = {json.dumps(values["execution_environment"])}',
                f'target = {{ type = "project", project_id = {json.dumps(values["project_id"])} }}',
                f'cwds = [{json.dumps(values["cwd"])}]',
            )) + "\n",
            encoding="utf-8",
        )
        path.chmod(0o600)
        return path

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

    def test_unset_cli_options_do_not_erase_input_json(self) -> None:
        coordinator = self.coordinator()
        direct = coordinator._make_inputs(self.inputs)
        cli_style = coordinator._make_inputs(self.inputs, **{key: None for key in self.inputs})
        self.assertEqual(direct, cli_style)

    def test_local_adapter_configuration_disallows_semantic_overrides(self) -> None:
        with self.assertRaisesRegex(WEEKLY.WeeklyIntelligenceError, "local_adapter_input_override_forbidden"):
            WEEKLY.run_campaign(self.inputs, state_dir=self.state, local_adapter_config=self.state / "unused.json")

    def test_cli_local_adapters_persist_real_source_and_packet_then_block_live_retrieval(self) -> None:
        source = self.state / "source.json"
        source.write_text(json.dumps({
            "schema_version": 1, "source_id": "field-theory", "captured_at": "2026-08-23T12:00:00Z",
            "items": [{"id": "fixture-one", "tweet_id": "1", "url": "https://example.invalid/design", "text": "RAW-SENTINEL dashboard design hierarchy", "synced_at": "2026-08-23T12:00:00Z"}],
        }))
        config = self.state / "local-adapters.json"
        config.write_text(json.dumps({"schema_version": 1, "source_document": str(source)}))
        maintenance = self.state / "maintenance.json"
        maintenance.write_text(json.dumps(self.maintenance))
        for path in (source, config, maintenance):
            path.chmod(0o600)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = WEEKLY.main(["--local-adapter-config", str(config), "--state-dir", str(self.state / "campaign"), "--maintenance-receipt", str(maintenance), "--now", str(self.now)])
        self.assertEqual(1, code)
        receipt = json.loads(output.getvalue())
        self.assertEqual("partial", receipt["terminal_state"])
        self.assertEqual("retrieval", receipt["stages"][2]["id"])
        self.assertEqual("failed", receipt["stages"][2]["status"])
        artifacts = [json.loads((self.state / "campaign" / row["artifact_path"]).read_text()) for row in receipt["stages"][:2]]
        self.assertEqual(1, artifacts[0]["observation_count"])
        self.assertTrue(artifacts[1]["cards"])
        self.assertNotIn("RAW-SENTINEL", output.getvalue() + json.dumps(artifacts))
        self.assertFalse(receipt["publication"]["promotion_approved"])

    def test_changed_campaign_persists_safe_artifacts_and_prepares_automatic_tail(self) -> None:
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

        self.assertEqual("prepared", receipt["terminal_state"])
        self.assertEqual("automatic_promotion_pending", receipt["reason_code"])
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

        self.assertEqual("prepared", first["terminal_state"])
        self.assertEqual("no_action", second["terminal_state"])
        self.assertEqual("no_action", third["terminal_state"])
        self.assertEqual(first["input_fingerprint"], second["input_fingerprint"])
        self.assertEqual(first["input_fingerprint"], third["input_fingerprint"])
        self.assertEqual(call_count, len(calls))
        self.assertTrue(all(stage["status"] == "reused" for stage in second["stages"]))
        self.assertTrue(all(stage["status"] == "reused" for stage in third["stages"]))
        self.assertFalse(second["publication"]["promotion_approved"])

    def test_tampered_stage_artifact_is_not_a_reusable_checkpoint(self) -> None:
        coordinator = self.coordinator()
        first = coordinator.run(**self.inputs)
        path = self.state / first["stages"][0]["artifact_path"]
        path.write_text("{}\n")
        second = coordinator.run(**self.inputs, now=self.now + 30)
        self.assertNotIn(second["terminal_state"], {"no_action", "prepared", "awaiting_approval"})

    def test_incomplete_weekly_receipts_cannot_manufacture_no_action(self) -> None:
        coordinator = self.coordinator()
        first = coordinator.run(**self.inputs)
        for path in (self.state / "receipts").glob("*.json"):
            doc = json.loads(path.read_text())
            doc["stages"] = []
            path.write_text(json.dumps(doc))
        self.assertIsNone(WEEKLY._prior_reusable_receipt(self.state, first["input_fingerprint"]))

    def test_blocked_domain_artifact_remains_linked_without_claiming_success(self) -> None:
        path = self.state / "partial-snapshot.json"
        path.write_text('{"completeness_state":"partial"}\n')
        path.chmod(0o600)
        adapter = lambda stage, context: {"status": "blocked", "reason_code": "source_partial", "artifact_path": path.name, "output_digest": WEEKLY.file_digest(path)}
        receipt = WEEKLY.run_campaign(state_dir=self.state, adapters=adapter, now=self.now, **self.inputs)
        stage = receipt["stages"][0]
        self.assertEqual("failed", stage["status"])
        self.assertEqual("source_partial", receipt["reason_code"])
        self.assertEqual(path.name, stage["artifact_path"])
        self.assertEqual(WEEKLY.file_digest(path), stage["output_digest"])

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
        self.assertEqual("prepared", resumed["terminal_state"])
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

    def test_resume_after_newer_campaign_keeps_its_own_checkpoints(self) -> None:
        def fail(stage, context):
            return {"status": "failed", "reason_code": "fixture_failure"} if stage == "retrieval" else {"status": "prepared"}

        coordinator = WEEKLY.WeeklyIntelligenceCoordinator(state_dir=self.state, adapters=fail, now=self.now)
        first = coordinator.run(**self.inputs)
        coordinator.adapters = self.successful_adapter([])
        newer = coordinator.run(**{**self.inputs, "source_delta": {"delta_digest": "9" * 64}}, now=self.now + 30)
        self.assertEqual("prepared", newer["terminal_state"])
        resumed = coordinator.run(**self.inputs, run_id=first["run_id"], resume=True, now=self.now + 60)
        self.assertEqual("prepared", resumed["terminal_state"])
        for original, reused in zip(first["stages"][:2], resumed["stages"][:2]):
            self.assertEqual(original["artifact_path"], reused["artifact_path"])
            self.assertEqual(original["output_digest"], reused["output_digest"])

    def test_maintenance_rejects_incomplete_unpersisted_and_future_receipts(self) -> None:
        invalid = [
            {key: self.maintenance[key] for key in ("task_id", "observed_at", "terminal_classification")},
            {**self.maintenance, "receipt_persisted": False},
            {**self.maintenance, "catalog_digest": "invalid"},
            {**self.maintenance, "observed_at": WEEKLY._now_iso(self.now + 60)},
        ]
        for record in invalid:
            with self.subTest(record=record):
                self.assertEqual("alert_invalid", WEEKLY.read_latest_maintenance_receipt(record, now=self.now)["status"])
                path = self.state / "maintenance.json"
                path.write_text(json.dumps(record))
                path.chmod(0o600)
                self.assertEqual("alert_invalid", WEEKLY.read_latest_maintenance_receipt(path, now=self.now)["status"])

    def test_new_campaign_still_reuses_matching_model_heavy_stages(self) -> None:
        calls = []
        coordinator = self.coordinator(calls)
        first = coordinator.run(**self.inputs)
        calls.clear()
        second = coordinator.run(**{**self.inputs, "eval_config": {"profile": "changed-fixture"}}, now=self.now + 30)
        self.assertEqual("prepared", second["terminal_state"])
        for index in (1, 2):
            self.assertEqual("reused", second["stages"][index]["status"])
            self.assertEqual(first["stages"][index]["artifact_path"], second["stages"][index]["artifact_path"])
        self.assertIn("candidate_evaluation", calls)

    def test_report_checkpoint_fingerprint_includes_automation_contract(self) -> None:
        config = WEEKLY.load_config()
        input_digests = {
            name: character * 64
            for name, character in zip(
                (
                    "source_manifest",
                    "source_delta",
                    "model_config",
                    "prompt_config",
                    "eval_config",
                ),
                "abcde",
                strict=True,
            )
        }
        maintenance = {"receipt_digest": "f" * 64, "status": "linked"}
        current = WEEKLY.stage_input_fingerprints(
            config=config,
            input_digests=input_digests,
            maintenance=maintenance,
        )
        changed = json.loads(json.dumps(config))
        changed["automatic_promotion"]["maximum_total_bytes"] -= 1
        drifted = WEEKLY.stage_input_fingerprints(
            config=changed,
            input_digests=input_digests,
            maintenance=maintenance,
        )
        self.assertEqual(current["design_packet"], drifted["design_packet"])
        self.assertNotEqual(current["report_receipt"], drifted["report_receipt"])

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
        self.assertEqual("prepared", recovered["terminal_state"])
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
        automation = self.automation_file()
        with (
            mock.patch.object(WEEKLY, "ACCOUNT_HOME", self.state),
            mock.patch.object(WEEKLY, "DEFAULT_AUTOMATION_ROOT", automation.parents[1]),
        ):
            coordinator = WEEKLY.WeeklyIntelligenceCoordinator(
                state_dir=self.state,
                adapters=self.successful_adapter([]),
                now=self.now,
            )
            coordinator.run(**self.inputs)
            config = WEEKLY.load_config()
            active_receipt = coordinator.run(**self.inputs)
            self.assertEqual("approved_and_persisted", active_receipt["scheduler"]["status"])
            healthy = WEEKLY.eight_day_health_check(
                state_dir=self.state,
                config=config,
                now=self.now + 7 * 24 * 60 * 60,
            )
            stale = WEEKLY.eight_day_health_check(
                state_dir=self.state,
                config=config,
                now=self.now + 9 * 24 * 60 * 60,
            )
        self.assertEqual("pass", healthy["status"])
        self.assertEqual("alert", stale["status"])
        self.assertEqual("campaign", stale["blocking_stage"])

    def test_self_issued_or_mismatched_scheduler_proof_cannot_enable_health(self) -> None:
        with self.assertRaisesRegex(WEEKLY.WeeklyIntelligenceError, "self_issued"):
            self.coordinator([]).run(
                **self.inputs,
                scheduler_evidence={
                    "enabled": True,
                    "approval": True,
                    "persisted_contract": True,
                    "contract_digest": WEEKLY.scheduler_contract_digest(WEEKLY.load_config()),
                },
            )
        mismatched = self.automation_file(status="PAUSED")
        with (
            mock.patch.object(WEEKLY, "ACCOUNT_HOME", self.state),
            mock.patch.object(WEEKLY, "DEFAULT_AUTOMATION_ROOT", mismatched.parents[1]),
        ):
            self.assertEqual(
                "mismatch",
                WEEKLY.scheduler_contract_status(WEEKLY.load_config()),
            )

    def test_scheduler_contract_can_bind_saved_project_separately_from_execution_root(self) -> None:
        saved_project = self.state / "saved-stack-project"
        saved_project.mkdir(mode=0o700)
        automation = self.automation_file(cwd=str(saved_project))
        with (
            mock.patch.object(WEEKLY, "ACCOUNT_HOME", self.state),
            mock.patch.object(WEEKLY, "DEFAULT_AUTOMATION_ROOT", automation.parents[1]),
            mock.patch.object(WEEKLY, "DEFAULT_AUTOMATION_WORKDIR", saved_project),
        ):
            self.assertEqual(
                "approved_and_persisted",
                WEEKLY.scheduler_contract_status(WEEKLY.load_config()),
            )

    def test_owner_local_input_files_are_required(self) -> None:
        inputs = self.state / "inputs.json"
        inputs.write_text(json.dumps({"source_manifest": {}}), encoding="utf-8")
        inputs.chmod(0o644)
        with self.assertRaisesRegex(WEEKLY.WeeklyIntelligenceError, "mode"):
            WEEKLY._read_owner_json(inputs)
        inputs.chmod(0o600)
        self.assertEqual({"source_manifest": {}}, WEEKLY._read_owner_json(inputs))

    def test_receipt_schema_and_scheduler_config_are_strict_and_active(self) -> None:
        schema = json.loads(
            (ROOT / "registry" / "weekly-campaign-receipt.schema.json").read_text()
        )
        config = WEEKLY.load_config()
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            sorted(WEEKLY.TERMINAL_STATES),
            sorted(schema["properties"]["terminal_state"]["enum"]),
        )
        self.assertTrue(config["scheduler"]["enabled"])
        self.assertTrue(config["scheduler"]["approval_required"])
        prompt = (ROOT / config["scheduler"]["prompt_path"]).read_bytes()
        expected_digest = WEEKLY.hashlib.sha256(WEEKLY.canonical_prompt_bytes(prompt)).hexdigest()
        self.assertEqual(
            config["scheduler"]["prompt_digest"],
            expected_digest,
        )
        altered_prompts = (
            prompt.replace(b"\n", b"\r\n"),
            prompt + b"\n",
            prompt.removesuffix(b"\n") + b" \n",
        )
        for altered in altered_prompts:
            self.assertNotEqual(
                expected_digest,
                WEEKLY.hashlib.sha256(WEEKLY.canonical_prompt_bytes(altered)).hexdigest(),
            )
        self.assertEqual("deny", config["provider_egress"])
        self.assertTrue(config["analysis_budget"]["authorized"])


if __name__ == "__main__":
    unittest.main()
