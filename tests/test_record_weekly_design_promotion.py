from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RECORDER = load("record_weekly_design_promotion", ROOT / "scripts" / "record-weekly-design-promotion.py")
WEEKLY = load("weekly_design_promotion_test_contract", ROOT / "scripts" / "run-stack-weekly-intelligence.py")


class RecordWeeklyDesignPromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root.chmod(0o700)
        self.evidence_root = self.root / "evidence"
        self.evidence_root.mkdir(mode=0o700)
        RECORDER.TRUSTED_RUNTIME_RECEIPTS_ROOT = self.evidence_root.resolve()
        self.output = self.root / "promotion-receipts"
        self.campaign = self._real_campaign()
        self.campaign_digest = hashlib.sha256(self.campaign.read_bytes()).hexdigest()
        self.live_receipt = self._live_binding()
        self.live_receipt_digest = hashlib.sha256(self.live_receipt.read_bytes()).hexdigest()
        self.packet = self._candidate_packet()
        self.packet_digest = RECORDER._digest_json(self.packet)
        self.head_sha = "c" * 40
        self.merge_commit = "d" * 40

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _real_campaign(self) -> Path:
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
                for key in ("checkout_state", "pr_state", "approval_state", "cleanup_state", "thread_state")
            },
            "terminal_classification": "no_action",
            "receipt_persisted": True,
        }
        state = self.root / "live" / "coordinator"
        state.parent.mkdir(mode=0o700)
        state.mkdir(mode=0o700)
        artifacts = state / "fixture-artifacts"
        artifacts.mkdir(mode=0o700)
        documents = {
            "design_packet": {
                "packet_id": "packet:" + "2" * 16,
                "packet_digest": "3" * 64,
                "cards": [
                    {
                        "card_id": "card:" + "4" * 16,
                        "revision_id": "revision:" + "5" * 16,
                        "anti_pattern_failure_mode": ["Repeated critique fixture."],
                        "evidence_citations": [{"evidence_id": "evidence:" + "6" * 16, "source_identity": "source:" + "a" * 16}],
                    },
                    {
                        "card_id": "card:" + "7" * 16,
                        "revision_id": "revision:" + "7" * 16,
                        "anti_pattern_failure_mode": ["Repeated critique fixture."],
                        "evidence_citations": [{"evidence_id": "evidence:" + "8" * 16, "source_identity": "source:" + "b" * 16}],
                    },
                    {
                        "card_id": "card:" + "8" * 16,
                        "revision_id": "revision:" + "9" * 16,
                        "anti_pattern_failure_mode": ["Independent-source fixture."],
                        "evidence_citations": [
                            {"evidence_id": "evidence:" + "6" * 16, "source_identity": "source:" + "a" * 16},
                            {"evidence_id": "evidence:" + "7" * 16, "source_identity": "source:" + "a" * 16},
                        ],
                    },
                ],
                "clusters": [{
                    "cluster_id": "failure:" + "b" * 16,
                    "card_ids": ["card:" + "4" * 16, "card:" + "7" * 16],
                    "count": 2,
                }],
                "candidate_changes": [
                    {
                        "change_id": "change:" + "1" * 16,
                        "card_id": "card:" + "4" * 16,
                        "revision_id": "revision:" + "5" * 16,
                        "evidence_ids": ["evidence:" + "6" * 16],
                    },
                    {
                        "change_id": "change:" + "9" * 16,
                        "card_id": "card:" + "8" * 16,
                        "revision_id": "revision:" + "9" * 16,
                        "evidence_ids": ["evidence:" + "6" * 16, "evidence:" + "7" * 16],
                    },
                ],
            },
            "retrieval": {"results": [{"evidence_id": "evidence:" + "6" * 16}, {"evidence_id": "evidence:" + "7" * 16}]},
            "candidate_evaluation": {"status": "prepared", "promotion": "automatic-promotion-pending", "metrics": {"hard_gate_failures": []}},
        }
        prepared: dict[str, tuple[str, str]] = {}
        for stage_id, document in documents.items():
            artifact = artifacts / f"{stage_id}.json"
            artifact.write_bytes(RECORDER._canonical(document))
            artifact.chmod(0o600)
            prepared[stage_id] = (
                f"fixture-artifacts/{artifact.name}",
                hashlib.sha256(artifact.read_bytes()).hexdigest(),
            )

        def adapter(stage_id: str, _context: dict) -> dict:
            if stage_id in prepared:
                relative, digest = prepared[stage_id]
                return {"status": "prepared", "artifact_path": relative, "output_digest": digest}
            return {"status": "prepared"}

        receipt = WEEKLY.WeeklyIntelligenceCoordinator(
            state_dir=state,
            adapters=adapter,
            now=now,
        ).run(
            source_manifest={"state": "complete", "set_digest": "a" * 64},
            source_delta={"state": "changed", "delta_digest": "b" * 64},
            model_config={"model": "approved-automation"},
            prompt_config={"revision": "fixture-v1"},
            eval_config={"profile": "design-learning-v1"},
            maintenance_receipt=maintenance,
        )
        path = state / "receipts" / f"{receipt['run_id']}.json"
        self.assertTrue(path.is_file())
        return path

    def _live_binding(self) -> Path:
        campaign = json.loads(self.campaign.read_text())
        directory = self.root / "live" / "live-receipts"
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / f"{campaign['run_id']}.json"
        path.write_bytes(RECORDER._canonical({
            "schema_version": 1,
            "task_id": "stack-weekly-live-binding",
            "campaign_run_id": campaign["run_id"],
            "campaign_receipt_relative_path": f"live/coordinator/receipts/{self.campaign.name}",
            "campaign_receipt_digest": self.campaign_digest,
            "campaign_terminal_state": campaign["terminal_state"],
            "campaign_reason_code": campaign["reason_code"],
            "receipt_persisted": True,
        }))
        path.chmod(0o600)
        return path

    def record(self, decision: dict, out: Path) -> dict:
        return RECORDER.record(
            self.live_receipt,
            self.live_receipt_digest,
            self.campaign,
            decision,
            out,
        )

    def packet_total_bytes(self) -> int:
        total = 0
        for edit in self.packet["edits"]:
            if "content" in edit:
                total += len(edit["content"].encode())
            else:
                total += (self.evidence_root / edit["content_file"]).stat().st_size
        return total

    def _candidate_packet(self) -> dict:
        base = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
        path = "skills/design/design-intelligence/SKILL.md"
        before = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{base}:{path}"])
        content = before.decode("utf-8") + "\n<!-- weekly fixture -->\n"
        after_digest = hashlib.sha256(content.encode()).hexdigest()
        content_dir = self.evidence_root / "candidate-content"
        content_dir.mkdir(mode=0o700, exist_ok=True)
        blob = content_dir / f"{after_digest}.utf8"
        blob.write_bytes(content.encode())
        blob.chmod(0o600)
        campaign = json.loads(self.campaign.read_text())
        stage_digests = {stage["id"]: stage["output_digest"] for stage in campaign["stages"]}
        return {
            "schema_version": 1,
            "change_id": "change:" + "1" * 16,
            "state": "candidate_quarantined",
            "approval_state": "candidate_unapproved",
            "base_commit": base,
            "source_lineage": {
                "packet_id": "packet:" + "2" * 16,
                "packet_digest": "3" * 64,
                "card_ids": ["card:" + "4" * 16],
                "revision_ids": ["revision:" + "5" * 16],
                "evidence_ids": ["evidence:" + "6" * 16],
                "parent_digests": [stage_digests["design_packet"], stage_digests["retrieval"], stage_digests["candidate_evaluation"]],
                "campaign_run_id": campaign["run_id"],
                "campaign_receipt_digest": self.campaign_digest,
                "design_packet_artifact_digest": stage_digests["design_packet"],
                "retrieval_artifact_digest": stage_digests["retrieval"],
                "candidate_evaluation_artifact_digest": stage_digests["candidate_evaluation"],
            },
            "target": {
                "canonical_name": "design-intelligence",
                "capability_path": path,
                "provider": "stack",
                "package": "stack",
                "upstream_pin": None,
            },
            "rationale": {
                "change_kind": "skill-update",
                "expected_behavior": ["Improve one bounded design-learning behavior."],
                "overlap_analysis": {"status": "no_collision", "compared_capabilities": [], "explanation": "No overlap."},
                "license_posture": "stack-owned-reviewed-derivative",
                "privacy_class": "reviewed-software-derivative",
                "materiality": {
                    "basis": "source-plus-repeated-critique-failure",
                    "source_count": 1,
                    "critique_failure_ids": ["failure:" + "b" * 16],
                    "evaluation_failure_ids": [],
                },
            },
            "rollback": {"base_commit": base, "path_digests": {path: hashlib.sha256(before).hexdigest()}},
            "edits": [{
                "path": path,
                "role": "skill",
                "operation": "replace",
                "before_digest": hashlib.sha256(before).hexdigest(),
                "after_digest": after_digest,
                "content_file": f"candidate-content/{blob.name}",
            }],
            "evaluation": {
                "profile": "design-learning-v1",
                "development_manifest_digest": "8" * 64,
                "holdout_manifest_digest": "9" * 64,
                "rotating_canary_manifest_digest": "a" * 64,
                "harness_required": True,
            },
        }

    def rebind_design_artifact(self, packet: dict, mutate) -> tuple[dict, str]:
        campaign = json.loads(self.campaign.read_text())
        stage = next(stage for stage in campaign["stages"] if stage["id"] == "design_packet")
        artifact = self.campaign.parents[1] / stage["artifact_path"]
        design = json.loads(artifact.read_text())
        mutate(design)
        artifact.write_bytes(RECORDER._canonical(design))
        artifact.chmod(0o600)
        new_artifact_digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        stage["output_digest"] = new_artifact_digest
        self.campaign.write_bytes(RECORDER._canonical(campaign))
        self.campaign.chmod(0o600)
        campaign_digest = hashlib.sha256(self.campaign.read_bytes()).hexdigest()
        lineage = packet["source_lineage"]
        lineage["campaign_receipt_digest"] = campaign_digest
        lineage["design_packet_artifact_digest"] = new_artifact_digest
        stage_digests = {stage["id"]: stage["output_digest"] for stage in campaign["stages"]}
        lineage["parent_digests"] = [
            stage_digests["design_packet"],
            stage_digests["retrieval"],
            stage_digests["candidate_evaluation"],
        ]
        return campaign, campaign_digest

    def write(self, name: str, value: dict) -> tuple[Path, str]:
        path = self.evidence_root / f"{name}.json"
        return self.write_path(path, value)

    def write_path(self, path: Path, value: dict) -> tuple[Path, str]:
        raw = RECORDER._canonical(value)
        path.write_bytes(raw)
        path.chmod(0o600)
        return path, hashlib.sha256(raw).hexdigest()

    def write_decision_path(self, decision: dict, *, valid_name: bool = True) -> Path:
        directory = self.root / "promotion-decisions"
        directory.mkdir(mode=0o700, exist_ok=True)
        raw = RECORDER._canonical(decision)
        digest = hashlib.sha256(raw).hexdigest()
        campaign_run_id = json.loads(self.campaign.read_text())["run_id"]
        candidate_digest = decision["candidate"]["digest"] or "no-candidate"
        name = (
            f"{campaign_run_id}--{candidate_digest}--{digest}.json"
            if valid_name
            else "wrong-decision-name.json"
        )
        path = directory / name
        path.write_bytes(raw)
        path.chmod(0o600)
        return path

    @staticmethod
    def gates(status: str = "passed") -> dict[str, str]:
        return {gate: status for gate in RECORDER.REQUIRED_GATES}

    def published_decision(self) -> dict:
        candidate_path, candidate_file_digest = self.write("candidate", self.packet)
        materialization = {
            "schema_version": 1,
            "receipt_kind": "capability-change-materialization",
            "status": "prepared",
            "change_digest": self.packet_digest,
            "change_id": self.packet["change_id"],
            "base_commit": self.packet["base_commit"],
            "target": self.packet["target"],
            "edits": [{key: edit[key] for key in ("path", "role", "operation", "before_digest", "after_digest")} for edit in self.packet["edits"]],
            "patch_digest": "b" * 64,
            "authorization": {
                "change_digest": self.packet_digest,
                "base_commit": self.packet["base_commit"],
                "scope": "isolated-owner-local-patch-only",
                "decision": "approved",
                "authorization_contract": RECORDER.AUTHORIZATION_CONTRACT,
                "campaign_run_id": json.loads(self.campaign.read_text())["run_id"],
                "campaign_receipt_digest": self.campaign_digest,
            },
            "campaign_evidence": {
                "receipt_digest": self.campaign_digest,
                "materiality_verified_before_materialization": True,
            },
            "active_checkout": {"head_before": self.packet["base_commit"], "head_after": self.packet["base_commit"], "status_digest_before": "c" * 64, "status_digest_after": "c" * 64, "unchanged": True},
            "isolation": {"disposable_checkout": True, "network": "not_used", "temporary_checkout_cleaned": True},
        }
        materialization_path, materialization_digest = self.write("materialization", materialization)
        evaluation = {
            "schema_version": 1,
            "receipt_kind": "design-learning-evaluation",
            "status": "awaiting_approval",
            "candidate_packet_digest": self.packet_digest,
            "materialization_receipt_digest": materialization_digest,
            "gates": {"minimum_repetitions": True, "development_wins": True, "holdout_regression": True},
            "metrics": {"synthetic_only": False, "real_task_usefulness_feedback_count": 4},
        }
        test_receipt = {
            "schema_version": 1,
            "receipt_kind": "stack-full-repository-tests",
            "status": "passed",
            "candidate_digest": self.packet_digest,
            "head_sha": self.head_sha,
            "command": ["python3", "-m", "unittest", "discover", "-s", "tests"],
            "test_count": 418,
            "exit_code": 0,
            "observed_at": "2026-08-30T00:00:00Z",
        }
        review = {
            "schema_version": 1,
            "receipt_kind": "stack-independent-review",
            "status": "passed",
            "candidate_digest": self.packet_digest,
            "head_sha": self.head_sha,
            "verdict": "ship",
            "reviewer_family": "gpt-5.6-sol",
            "reviewer_id": "independent-review-fixture",
            "independence_verified": True,
            "reviewed_at": "2026-08-30T00:01:00Z",
        }
        ci = {"schema_version": 1, "receipt_kind": "github-pull-request-ci", "status": "passed", "candidate_digest": self.packet_digest, "number": 42, "head_sha": self.head_sha, "draft": False, "all_required_checks_passed": True, "auto_merge_enabled": True}
        merge = {"schema_version": 1, "receipt_kind": "github-merge-verification", "status": "passed", "candidate_digest": self.packet_digest, "number": 42, "head_sha": self.head_sha, "merge_commit": self.merge_commit, "origin_main_commit": self.merge_commit}
        transaction_id = "install-fixture"
        install = {
            "schema_version": 1,
            "transaction_id": transaction_id,
            "status": "published",
            "registry_digest": "d" * 64,
            "source_commits": [self.merge_commit],
            "prior_targets": {"claude": True, "codex": True},
            "targets": ["claude", "codex"],
            "verifier_results": [{"target": "claude", "status": "passed", "exit_code": 0}, {"target": "codex", "status": "passed", "exit_code": 0}],
            "verified_at": "2026-08-30T00:02:00Z",
        }
        rollback = {"schema_version": 1, "transaction_id": transaction_id, "prior_targets": {"claude": "/prior/claude", "codex": "/prior/codex"}}
        transaction = self.evidence_root / "transactions" / transaction_id
        transaction.mkdir(parents=True, mode=0o700, exist_ok=True)
        transaction.parent.chmod(0o700)
        artifacts = {
            "candidate_packet": (candidate_path, candidate_file_digest),
            "materialization": (materialization_path, materialization_digest),
            "evaluation": self.write("evaluation", evaluation),
            "repository_tests": self.write("tests", test_receipt),
            "independent_review": self.write("review", review),
            "pull_request_ci": self.write("ci", ci),
            "merge_verification": self.write("merge", merge),
            "runtime_publication": self.write_path(transaction / "install.json", install),
            "rollback_receipt": self.write_path(transaction / "rollback.json", rollback),
        }
        return {
            "schema_version": 1,
            "authorization_contract": RECORDER.AUTHORIZATION_CONTRACT,
            "disposition": "published",
            "reason_code": "published",
            "candidate": {
                "state": "selected",
                "digest": self.packet_digest,
                "changed_files": len(self.packet["edits"]),
                "total_bytes": self.packet_total_bytes(),
            },
            "gates": self.gates(),
            "pull_request": {"state": "merged", "number": 42, "head_sha": self.head_sha, "merge_commit": self.merge_commit},
            "runtime": {"state": "published", "targets": ["claude", "codex"], "install_receipt_digest": artifacts["runtime_publication"][1], "rollback_receipt_digest": artifacts["rollback_receipt"][1]},
            "evidence": {name: {"path": str(path), "digest": digest} for name, (path, digest) in artifacts.items()},
        }

    def inactive_decision(self, disposition: str, candidate: bool) -> dict:
        evidence = {name: None for name in RECORDER.EVIDENCE_KEYS}
        if candidate:
            packet_path, packet_file_digest = self.write("candidate", self.packet)
            evidence["candidate_packet"] = {"path": str(packet_path), "digest": packet_file_digest}
            candidate_summary = {
                "state": "selected",
                "digest": self.packet_digest,
                "changed_files": len(self.packet["edits"]),
                "total_bytes": self.packet_total_bytes(),
            }
        else:
            candidate_summary = {"state": "absent", "digest": None, "changed_files": 0, "total_bytes": 0}
        return {
            "schema_version": 1,
            "authorization_contract": RECORDER.AUTHORIZATION_CONTRACT,
            "disposition": disposition,
            "reason_code": disposition,
            "candidate": candidate_summary,
            "gates": self.gates("not_applicable"),
            "pull_request": {"state": "not_created", "number": None, "head_sha": None, "merge_commit": None},
            "runtime": {"state": "not_run", "targets": [], "install_receipt_digest": None, "rollback_receipt_digest": None},
            "evidence": evidence,
        }

    def test_real_coordinator_receipt_and_every_evidence_file_are_required_for_publication(self) -> None:
        receipt = self.record(self.published_decision(), self.output)
        self.assertEqual("published", receipt["disposition"])
        self.assertEqual(set(RECORDER.EVIDENCE_KEYS), set(receipt["evidence"]))
        path = self.output / (
            f"{receipt['campaign']['run_id']}--{receipt['candidate']['digest']}--"
            f"{RECORDER._digest_json(receipt)}.json"
        )
        self.assertNotIn(str(self.root), path.read_text())
        self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))

        missing = self.published_decision()
        missing["evidence"]["independent_review"] = None
        with self.assertRaisesRegex(RECORDER.PromotionReceiptError, "lacks independent_review"):
            self.record(missing, self.root / "missing-review")

    def test_runtime_receipt_root_cannot_redirect_through_a_symlink(self) -> None:
        decision = self.published_decision()
        redirected = self.root / "trusted-receipt-link"
        redirected.symlink_to(self.evidence_root, target_is_directory=True)
        original_root = RECORDER.TRUSTED_RUNTIME_RECEIPTS_ROOT
        RECORDER.TRUSTED_RUNTIME_RECEIPTS_ROOT = redirected
        try:
            with self.assertRaisesRegex(
                RECORDER.PromotionReceiptError,
                "owner-local path must not use a symlink",
            ):
                self.record(decision, self.root / "redirected-runtime-root")
        finally:
            RECORDER.TRUSTED_RUNTIME_RECEIPTS_ROOT = original_root

    def test_fabricated_or_mismatched_evidence_fails_closed(self) -> None:
        with self.assertRaisesRegex(RECORDER.PromotionReceiptError, "returned digest"):
            RECORDER.record(
                self.live_receipt,
                "0" * 64,
                self.campaign,
                self.published_decision(),
                self.root / "bad-live-binding",
            )

        decision = self.published_decision()
        decision["evidence"]["evaluation"]["digest"] = "0" * 64
        with self.assertRaisesRegex(RECORDER.PromotionReceiptError, "does not match"):
            self.record(decision, self.root / "bad-digest")

        missing_materiality = self.published_decision()
        materialization_path = Path(missing_materiality["evidence"]["materialization"]["path"])
        materialization = json.loads(materialization_path.read_text())
        materialization.pop("campaign_evidence")
        materialization_path.write_bytes(RECORDER._canonical(materialization))
        missing_materiality["evidence"]["materialization"]["digest"] = hashlib.sha256(
            materialization_path.read_bytes()
        ).hexdigest()
        with self.assertRaisesRegex(RECORDER.PromotionReceiptError, "verified campaign materiality"):
            self.record(missing_materiality, self.root / "missing-campaign-materiality")

        mismatched_materiality = self.published_decision()
        materialization_path = Path(mismatched_materiality["evidence"]["materialization"]["path"])
        materialization = json.loads(materialization_path.read_text())
        materialization["campaign_evidence"]["receipt_digest"] = "0" * 64
        materialization_path.write_bytes(RECORDER._canonical(materialization))
        mismatched_materiality["evidence"]["materialization"]["digest"] = hashlib.sha256(
            materialization_path.read_bytes()
        ).hexdigest()
        with self.assertRaisesRegex(RECORDER.PromotionReceiptError, "verified campaign materiality"):
            self.record(mismatched_materiality, self.root / "mismatched-campaign-materiality")

        decision = self.published_decision()
        review_path = Path(decision["evidence"]["independent_review"]["path"])
        review = json.loads(review_path.read_text())
        review["independence_verified"] = False
        review_path.write_bytes(RECORDER._canonical(review))
        decision["evidence"]["independent_review"]["digest"] = hashlib.sha256(review_path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(RECORDER.PromotionReceiptError, "independent review"):
            self.record(decision, self.root / "bad-review")

        stale_rollback = self.published_decision()
        rollback_path = Path(stale_rollback["evidence"]["rollback_receipt"]["path"])
        rollback = json.loads(rollback_path.read_text())
        rollback["prior_targets"]["codex"] = None
        rollback_path.write_bytes(RECORDER._canonical(rollback))
        rollback_digest = hashlib.sha256(rollback_path.read_bytes()).hexdigest()
        stale_rollback["evidence"]["rollback_receipt"]["digest"] = rollback_digest
        stale_rollback["runtime"]["rollback_receipt_digest"] = rollback_digest
        with self.assertRaisesRegex(RECORDER.PromotionReceiptError, "does not match the runtime"):
            self.record(stale_rollback, self.root / "stale-rollback")

        stale_pair = self.published_decision()
        stale_transaction = self.evidence_root / "transactions" / "install-stale"
        stale_transaction.mkdir(mode=0o700, exist_ok=True)
        stale_document = {
            "schema_version": 1,
            "transaction_id": "install-stale",
            "prior_targets": {"claude": "/older/claude", "codex": "/older/codex"},
        }
        stale_path, stale_digest = self.write_path(stale_transaction / "rollback.json", stale_document)
        stale_pair["evidence"]["rollback_receipt"] = {"path": str(stale_path), "digest": stale_digest}
        stale_pair["runtime"]["rollback_receipt_digest"] = stale_digest
        with self.assertRaisesRegex(RECORDER.PromotionReceiptError, "transaction IDs"):
            self.record(stale_pair, self.root / "same-state-stale-rollback")

        forged_pair = self.published_decision()
        legitimate_install = Path(forged_pair["evidence"]["runtime_publication"]["path"])
        legitimate_rollback = Path(forged_pair["evidence"]["rollback_receipt"]["path"])
        transaction_id = json.loads(legitimate_install.read_text())["transaction_id"]
        forged_transaction = self.root / "forged-runtime-receipts" / "transactions" / transaction_id
        forged_transaction.mkdir(parents=True, mode=0o700)
        forged_transaction.parent.chmod(0o700)
        forged_transaction.parent.parent.chmod(0o700)
        forged_install, forged_install_digest = self.write_path(
            forged_transaction / "install.json",
            json.loads(legitimate_install.read_text()),
        )
        forged_rollback, forged_rollback_digest = self.write_path(
            forged_transaction / "rollback.json",
            json.loads(legitimate_rollback.read_text()),
        )
        forged_pair["evidence"]["runtime_publication"] = {
            "path": str(forged_install), "digest": forged_install_digest,
        }
        forged_pair["evidence"]["rollback_receipt"] = {
            "path": str(forged_rollback), "digest": forged_rollback_digest,
        }
        forged_pair["runtime"]["install_receipt_digest"] = forged_install_digest
        forged_pair["runtime"]["rollback_receipt_digest"] = forged_rollback_digest
        with self.assertRaisesRegex(RECORDER.PromotionReceiptError, "configured installer receipt root"):
            self.record(forged_pair, self.root / "forged-runtime-pair")

        weak = json.loads(json.dumps(self.packet))
        weak["rationale"]["materiality"] = {
            "basis": "two-independent-sources",
            "source_count": 1,
            "critique_failure_ids": [],
            "evaluation_failure_ids": [],
        }
        with self.assertRaisesRegex(RECORDER.PromotionReceiptError, "materiality basis"):
            RECORDER._candidate_packet(
                weak,
                json.loads(self.campaign.read_text()),
                self.campaign_digest,
                self.campaign,
            )

        unrelated = json.loads(json.dumps(self.packet))
        unrelated["source_lineage"]["evidence_ids"] = ["evidence:" + "f" * 16]
        unrelated["rationale"]["materiality"]["source_count"] = 1
        with self.assertRaisesRegex(RECORDER.PromotionReceiptError, "lineage IDs"):
            RECORDER._candidate_packet(
                unrelated,
                json.loads(self.campaign.read_text()),
                self.campaign_digest,
                self.campaign,
            )

        invented_failure = json.loads(json.dumps(self.packet))
        invented_failure["rationale"]["materiality"]["critique_failure_ids"] = ["failure:" + "f" * 16]
        with self.assertRaisesRegex(RECORDER.PromotionReceiptError, "failure IDs"):
            RECORDER._candidate_packet(
                invented_failure,
                json.loads(self.campaign.read_text()),
                self.campaign_digest,
                self.campaign,
            )

        same_source = json.loads(json.dumps(self.packet))
        same_source["change_id"] = "change:" + "9" * 16
        same_source["source_lineage"]["card_ids"] = ["card:" + "8" * 16]
        same_source["source_lineage"]["revision_ids"] = ["revision:" + "9" * 16]
        same_source["source_lineage"]["evidence_ids"] = ["evidence:" + "6" * 16, "evidence:" + "7" * 16]
        same_source["rationale"]["materiality"] = {
            "basis": "two-independent-sources",
            "source_count": 2,
            "critique_failure_ids": [],
            "evaluation_failure_ids": [],
        }
        with self.assertRaisesRegex(RECORDER.PromotionReceiptError, "source count"):
            RECORDER._candidate_packet(
                same_source,
                json.loads(self.campaign.read_text()),
                self.campaign_digest,
                self.campaign,
            )

        original_campaign = self.campaign.read_bytes()
        original_campaign_document = json.loads(original_campaign)
        original_design_stage = next(
            stage for stage in original_campaign_document["stages"] if stage["id"] == "design_packet"
        )
        original_design_path = self.campaign.parents[1] / original_design_stage["artifact_path"]
        original_design = original_design_path.read_bytes()
        unrelated_source = json.loads(json.dumps(same_source))

        def move_second_source_to_unrelated_card(design: dict) -> None:
            selected = next(card for card in design["cards"] if card["card_id"] == "card:" + "8" * 16)
            selected["evidence_citations"] = [selected["evidence_citations"][0]]
            unrelated_card = next(card for card in design["cards"] if card["card_id"] == "card:" + "7" * 16)
            unrelated_card["evidence_citations"] = [{
                "evidence_id": "evidence:" + "7" * 16,
                "source_identity": "source:" + "b" * 16,
            }]

        unrelated_campaign, unrelated_campaign_digest = self.rebind_design_artifact(
            unrelated_source,
            move_second_source_to_unrelated_card,
        )
        with self.assertRaisesRegex(RECORDER.PromotionReceiptError, "exact campaign source identity"):
            RECORDER._candidate_packet(
                unrelated_source,
                unrelated_campaign,
                unrelated_campaign_digest,
                self.campaign,
            )

        unrelated_cluster = json.loads(json.dumps(self.packet))
        unrelated_cluster["rationale"]["materiality"]["critique_failure_ids"] = ["failure:" + "c" * 16]

        def add_unrelated_cluster(design: dict) -> None:
            design["clusters"].append({
                "cluster_id": "failure:" + "c" * 16,
                "card_ids": ["card:" + "7" * 16, "card:" + "8" * 16],
                "count": 2,
            })

        cluster_campaign, cluster_campaign_digest = self.rebind_design_artifact(
            unrelated_cluster,
            add_unrelated_cluster,
        )
        with self.assertRaisesRegex(RECORDER.PromotionReceiptError, "failure IDs"):
            RECORDER._candidate_packet(
                unrelated_cluster,
                cluster_campaign,
                cluster_campaign_digest,
                self.campaign,
            )
        original_design_path.write_bytes(original_design)
        original_design_path.chmod(0o600)
        self.campaign.write_bytes(original_campaign)
        self.campaign.chmod(0o600)

        mixed_runtime = self.published_decision()
        install_path = Path(mixed_runtime["evidence"]["runtime_publication"]["path"])
        install = json.loads(install_path.read_text())
        install["source_commits"] = [self.merge_commit, "e" * 40]
        install_path.write_bytes(RECORDER._canonical(install))
        install_digest = hashlib.sha256(install_path.read_bytes()).hexdigest()
        mixed_runtime["evidence"]["runtime_publication"]["digest"] = install_digest
        mixed_runtime["runtime"]["install_receipt_digest"] = install_digest
        with self.assertRaisesRegex(RECORDER.PromotionReceiptError, "runtime publication"):
            self.record(mixed_runtime, self.root / "mixed-runtime-commits")

    def test_no_action_campaign_cannot_be_published(self) -> None:
        campaign = json.loads(self.campaign.read_text())
        campaign["terminal_state"] = "no_action"
        campaign["reason_code"] = "no_new_input"
        self.campaign.write_bytes(WEEKLY.canonical_json(campaign).encode())
        self.campaign.chmod(0o600)
        self.campaign_digest = hashlib.sha256(self.campaign.read_bytes()).hexdigest()
        self.live_receipt = self._live_binding()
        self.live_receipt_digest = hashlib.sha256(self.live_receipt.read_bytes()).hexdigest()
        with self.assertRaisesRegex(RECORDER.PromotionReceiptError, "no_action campaign"):
            self.record(self.published_decision(), self.output)

    def test_no_action_has_no_candidate_queue_or_evidence(self) -> None:
        receipt = self.record(self.inactive_decision("no_action", candidate=False), self.output)
        self.assertEqual("no_action", receipt["disposition"])
        self.assertTrue(all(value is None for value in receipt["evidence"].values()))
        self.assertTrue((self.output / f"{receipt['campaign']['run_id']}.json").is_file())

    def test_selected_candidate_has_no_file_or_byte_cap(self) -> None:
        paths = [
            "skills/design/design-intelligence/references/output-contract.md",
            "skills/design/design-intelligence/references/promotion-rules.md",
            "skills/design/design-intelligence/references/card-contract.md",
            "skills/design/design-intelligence/references/source-adapters.md",
        ]
        edits = []
        base = self.packet["base_commit"]
        for index, path in enumerate(paths):
            before = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{base}:{path}"])
            repetitions = 40000 if index == 0 else 350
            content = before.decode("utf-8") + "\n" + (f"Expanded candidate guidance {index}. " * repetitions) + "\n"
            edits.append({
                "path": path,
                "role": "reference",
                "operation": "replace",
                "before_digest": hashlib.sha256(before).hexdigest(),
                "after_digest": hashlib.sha256(content.encode()).hexdigest(),
                "content": content,
            })
        self.assertGreater(len(edits), 3)
        self.assertGreater(sum(len(edit["content"].encode()) for edit in edits), 32768)
        content_dir = self.evidence_root / "candidate-content"
        content_dir.mkdir(mode=0o700, exist_ok=True)
        for edit in edits:
            content = edit.pop("content").encode()
            blob = content_dir / f"{edit['after_digest']}.utf8"
            blob.write_bytes(content)
            blob.chmod(0o600)
            edit["content_file"] = f"candidate-content/{blob.name}"
        self.packet["edits"] = edits
        self.packet["rationale"]["change_kind"] = "reference-update"
        self.packet["rollback"]["path_digests"] = {edit["path"]: edit["before_digest"] for edit in edits}
        self.packet_digest = RECORDER._digest_json(self.packet)

        decision = self.published_decision()
        candidate_path = Path(decision["evidence"]["candidate_packet"]["path"])
        self.assertLess(candidate_path.stat().st_size, RECORDER.MAX_PRIVATE_JSON_BYTES)
        receipt = self.record(decision, self.output)

        self.assertEqual(len(edits), receipt["candidate"]["changed_files"])
        self.assertGreater(receipt["candidate"]["total_bytes"], 32768)

    def test_multiple_selected_candidate_receipts_do_not_collide(self) -> None:
        first = self.record(self.published_decision(), self.output)
        first_path = self.output / (
            f"{first['campaign']['run_id']}--{first['candidate']['digest']}--"
            f"{RECORDER._digest_json(first)}.json"
        )

        edit = self.packet["edits"][0]
        current = (self.evidence_root / edit["content_file"]).read_bytes()
        revised = current + b"\nA second independently evaluated refinement.\n"
        edit["after_digest"] = hashlib.sha256(revised).hexdigest()
        revised_blob = self.evidence_root / "candidate-content" / f"{edit['after_digest']}.utf8"
        revised_blob.write_bytes(revised)
        revised_blob.chmod(0o600)
        edit["content_file"] = f"candidate-content/{revised_blob.name}"
        self.packet_digest = RECORDER._digest_json(self.packet)
        second = self.record(self.published_decision(), self.output)
        second_path = self.output / (
            f"{second['campaign']['run_id']}--{second['candidate']['digest']}--"
            f"{RECORDER._digest_json(second)}.json"
        )

        self.assertNotEqual(first_path, second_path)
        self.assertTrue(first_path.is_file())
        self.assertTrue(second_path.is_file())

    def test_retry_then_publication_for_same_candidate_is_append_only(self) -> None:
        retry = self.inactive_decision("retry_with_alert", candidate=True)
        retry["gates"]["material-evidence"] = "passed"
        retry["gates"]["isolated-materialization"] = "unavailable"
        retry_receipt = self.record(retry, self.output)

        published_receipt = self.record(self.published_decision(), self.output)
        retry_path = self.output / (
            f"{retry_receipt['campaign']['run_id']}--{retry_receipt['candidate']['digest']}--"
            f"{RECORDER._digest_json(retry_receipt)}.json"
        )
        published_path = self.output / (
            f"{published_receipt['campaign']['run_id']}--{published_receipt['candidate']['digest']}--"
            f"{RECORDER._digest_json(published_receipt)}.json"
        )

        self.assertNotEqual(retry_path, published_path)
        self.assertEqual("retry_with_alert", json.loads(retry_path.read_text())["disposition"])
        self.assertEqual("published", json.loads(published_path.read_text())["disposition"])

    def test_decision_file_requires_campaign_candidate_and_exact_digest_name(self) -> None:
        decision = self.inactive_decision("retry_with_alert", candidate=True)
        decision["gates"]["material-evidence"] = "passed"
        decision["gates"]["isolated-materialization"] = "unavailable"
        valid = self.write_decision_path(decision)

        receipt = RECORDER.record(
            self.live_receipt,
            self.live_receipt_digest,
            self.campaign,
            valid,
            self.output,
        )

        self.assertEqual("retry_with_alert", receipt["disposition"])
        invalid = self.write_decision_path(decision, valid_name=False)
        with self.assertRaisesRegex(RECORDER.PromotionReceiptError, "filename digest"):
            RECORDER.record(
                self.live_receipt,
                self.live_receipt_digest,
                self.campaign,
                invalid,
                self.root / "invalid-decision-name",
            )

    def test_rejected_and_retry_outcomes_cannot_leave_open_pull_requests(self) -> None:
        rejected = self.inactive_decision("rejected_no_queue", candidate=True)
        rejected["gates"]["material-evidence"] = "passed"
        rejected["gates"]["isolated-materialization"] = "failed"
        self.assertEqual("rejected_no_queue", self.record(rejected, self.output)["disposition"])

        retry = self.inactive_decision("retry_with_alert", candidate=True)
        retry["gates"]["material-evidence"] = "passed"
        retry["gates"]["isolated-materialization"] = "unavailable"
        retry["pull_request"] = {"state": "open", "number": 44, "head_sha": self.head_sha, "merge_commit": None}
        with self.assertRaisesRegex(RECORDER.PromotionReceiptError, "cannot merge or publish"):
            self.record(retry, self.root / "open-retry")


if __name__ == "__main__":
    unittest.main()
