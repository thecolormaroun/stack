from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("materialize_capability_change", ROOT / "scripts/materialize-capability-change.py")
assert SPEC and SPEC.loader
MATERIALIZER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MATERIALIZER)
RECORDER_SPEC = importlib.util.spec_from_file_location("record_weekly_design_promotion_for_materializer", ROOT / "scripts" / "record-weekly-design-promotion.py")
assert RECORDER_SPEC and RECORDER_SPEC.loader
RECORDER = importlib.util.module_from_spec(RECORDER_SPEC)
RECORDER_SPEC.loader.exec_module(RECORDER)
WEEKLY_SPEC = importlib.util.spec_from_file_location("weekly_design_promotion_for_materializer", ROOT / "scripts" / "run-stack-weekly-intelligence.py")
assert WEEKLY_SPEC and WEEKLY_SPEC.loader
WEEKLY = importlib.util.module_from_spec(WEEKLY_SPEC)
WEEKLY_SPEC.loader.exec_module(WEEKLY)


class MaterializeCapabilityChangeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.chmod(self.root, 0o700)
        self.repo = self.root / "repo"
        self.repo.mkdir(mode=0o700)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Fixture"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "fixture@example.invalid"], check=True)
        target_root = self.repo / "skills" / "design" / "fixture"
        target_root.mkdir(parents=True)
        (target_root / "SKILL.md").write_text("---\nname: fixture\n---\n# Fixture\n", encoding="utf-8")
        (target_root / "capability.json").write_text(json.dumps({"canonical_name": "fixture", "ownership": {"provider": "stack", "package": "stack"}}), encoding="utf-8")
        (self.repo / "registry").mkdir()
        (self.repo / "registry" / "capabilities.json").write_text(json.dumps({
            "capabilities": [{
                "canonical_name": "fixture",
                "ownership": {"provider": "stack", "package": "stack", "source_path": "skills/design/fixture/SKILL.md"},
                "source": {"skill_path": "skills/design/fixture/SKILL.md"},
            }],
        }), encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "fixture base"], check=True)
        self.base = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        self.old = (target_root / "SKILL.md").read_bytes()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def packet(self, *, change_kind: str = "skill-update", edits: list[dict] | None = None, target: dict | None = None) -> dict:
        content = "---\nname: fixture\n---\n# Fixture\n\nA bounded rule.\n"
        edit = {
            "path": "skills/design/fixture/SKILL.md",
            "role": "skill",
            "operation": "replace",
            "before_digest": MATERIALIZER.digest_bytes(self.old),
            "after_digest": MATERIALIZER.digest_bytes(content.encode()),
            "content": content,
        }
        rows = edits if edits is not None else [edit]
        packet = {
            "schema_version": 1,
            "change_id": "change:" + "a" * 16,
            "state": "candidate_quarantined",
            "approval_state": "candidate_unapproved",
            "base_commit": self.base,
            "source_lineage": {
                "packet_id": "packet:" + "b" * 16,
                "packet_digest": "c" * 64,
                "card_ids": ["card:" + "d" * 16],
                "revision_ids": ["revision:" + "e" * 16],
                "evidence_ids": ["evidence:" + "f" * 16],
                "parent_digests": ["1" * 64],
            },
            "target": target or {
                "canonical_name": "fixture",
                "capability_path": "skills/design/fixture/SKILL.md",
                "provider": "stack",
                "package": "stack",
                "upstream_pin": None,
            },
            "rationale": {
                "change_kind": change_kind,
                "expected_behavior": ["The fixture follows the bounded rule."],
                "overlap_analysis": {"status": "no_collision", "compared_capabilities": [], "explanation": "No overlap."},
                "license_posture": "stack-owned-reviewed-derivative",
                "privacy_class": "reviewed-software-derivative",
                "materiality": {
                    "basis": "source-plus-repeated-critique-failure",
                    "source_count": 1,
                    "critique_failure_ids": ["failure:" + "6" * 16],
                    "evaluation_failure_ids": [],
                },
            },
            "rollback": {"base_commit": self.base, "path_digests": {row["path"]: row["before_digest"] for row in rows}},
            "edits": rows,
            "evaluation": {
                "profile": "design-learning-v1",
                "development_manifest_digest": "2" * 64,
                "holdout_manifest_digest": "3" * 64,
                "rotating_canary_manifest_digest": "4" * 64,
                "harness_required": True,
            },
        }
        return packet

    def authorization(self, packet: dict, **overrides: object) -> dict:
        value = {
            "schema_version": 1,
            "change_digest": MATERIALIZER.digest_json(packet),
            "base_commit": self.base,
            "scope": "isolated-owner-local-patch-only",
            "decision": "approved",
            "reviewed_by": "fixture-reviewer",
            "reviewed_at": "2026-08-23T00:00:00Z",
        }
        value.update(overrides)
        return value

    def automatic_authorization(self, packet: dict, **overrides: object) -> dict:
        defaults = {
            "campaign_run_id": "weekly-fixture",
            "campaign_receipt_digest": "5" * 64,
            "design_packet_artifact_digest": "6" * 64,
            "retrieval_artifact_digest": "7" * 64,
            "candidate_evaluation_artifact_digest": "8" * 64,
        }
        for key, value in defaults.items():
            packet["source_lineage"].setdefault(key, value)
        value = self.authorization(packet)
        value.update({
            "authorization_contract": "weekly-design-auto-promotion-approved-v1",
            "campaign_run_id": packet["source_lineage"]["campaign_run_id"],
            "campaign_receipt_digest": packet["source_lineage"]["campaign_receipt_digest"],
        })
        value.update(overrides)
        return value

    def automatic_campaign(self, packet: dict) -> tuple[Path, str]:
        state = self.root / "campaign-state"
        state.mkdir(mode=0o700)
        artifacts = state / "fixture-artifacts"
        artifacts.mkdir(mode=0o700)
        lineage = packet["source_lineage"]
        selected_card = lineage["card_ids"][0]
        selected_revision = lineage["revision_ids"][0]
        selected_evidence = lineage["evidence_ids"][0]
        critique_failure = packet["rationale"]["materiality"]["critique_failure_ids"][0]
        documents = {
            "design_packet": {
                "packet_id": lineage["packet_id"],
                "packet_digest": lineage["packet_digest"],
                "cards": [
                    {
                        "card_id": selected_card,
                        "revision_id": selected_revision,
                        "anti_pattern_failure_mode": ["Repeated fixture failure."],
                        "evidence_citations": [{"evidence_id": selected_evidence, "source_identity": "source:" + "1" * 16}],
                    },
                    {
                        "card_id": "card:" + "9" * 16,
                        "revision_id": "revision:" + "9" * 16,
                        "anti_pattern_failure_mode": ["Repeated fixture failure."],
                        "evidence_citations": [{"evidence_id": "evidence:" + "9" * 16, "source_identity": "source:" + "9" * 16}],
                    },
                ],
                "clusters": [{
                    "cluster_id": critique_failure,
                    "card_ids": [selected_card, "card:" + "9" * 16],
                    "count": 2,
                }],
                "candidate_changes": [{
                    "change_id": packet["change_id"],
                    "card_id": selected_card,
                    "revision_id": selected_revision,
                    "evidence_ids": [selected_evidence],
                }],
            },
            "retrieval": {"results": [{"evidence_id": selected_evidence}]},
            "candidate_evaluation": {"status": "prepared", "metrics": {"hard_gate_failures": []}},
        }
        prepared: dict[str, tuple[str, str]] = {}
        for stage_id, document in documents.items():
            path = artifacts / f"{stage_id}.json"
            path.write_bytes(RECORDER._canonical(document))
            path.chmod(0o600)
            prepared[stage_id] = (
                f"fixture-artifacts/{path.name}",
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        maintenance = {
            "schema_version": 1,
            "task_id": "stack-maintenance",
            "run_id": "fixture-maintenance",
            "mode": "audit",
            "manual_audit": False,
            "observed_at": WEEKLY._now_iso(1_777_000_000.0 - 60),
            "input_fingerprint": "c" * 64,
            "provider_refs": [],
            "catalog_digest": "d" * 64,
            "policy_digest": "e" * 64,
            "changed_paths_digest": "f" * 64,
            "checks": {"fixture_only": True},
            **{key: {"status": "fixture_only"} for key in ("checkout_state", "pr_state", "approval_state", "cleanup_state", "thread_state")},
            "terminal_classification": "no_action",
            "receipt_persisted": True,
        }

        def adapter(stage_id: str, _context: dict) -> dict:
            if stage_id in prepared:
                relative, digest = prepared[stage_id]
                return {"status": "prepared", "artifact_path": relative, "output_digest": digest}
            return {"status": "prepared"}

        receipt = WEEKLY.WeeklyIntelligenceCoordinator(state_dir=state, adapters=adapter, now=1_777_000_000.0).run(
            source_manifest={"state": "complete", "set_digest": "a" * 64},
            source_delta={"state": "changed", "delta_digest": "b" * 64},
            model_config={"model": "approved-automation"},
            prompt_config={"revision": "fixture-v1"},
            eval_config={"profile": "design-learning-v1"},
            maintenance_receipt=maintenance,
        )
        campaign = state / "receipts" / f"{receipt['run_id']}.json"
        campaign_digest = hashlib.sha256(campaign.read_bytes()).hexdigest()
        stage_digests = {stage["id"]: stage["output_digest"] for stage in receipt["stages"]}
        lineage.update({
            "campaign_run_id": receipt["run_id"],
            "campaign_receipt_digest": campaign_digest,
            "design_packet_artifact_digest": stage_digests["design_packet"],
            "retrieval_artifact_digest": stage_digests["retrieval"],
            "candidate_evaluation_artifact_digest": stage_digests["candidate_evaluation"],
        })
        return campaign, campaign_digest

    def test_reference_only_insight_cannot_become_command_or_router_change(self) -> None:
        content = "# Reference\n\nUse hierarchy.\n"
        edit = {
            "path": "registry/commands.json",
            "role": "registry",
            "operation": "create",
            "before_digest": None,
            "after_digest": MATERIALIZER.digest_bytes(content.encode()),
            "content": content,
        }
        packet = self.packet(change_kind="reference-update", edits=[edit])
        with self.assertRaises(MATERIALIZER.MaterializationError):
            MATERIALIZER.materialize_change(packet, self.authorization(packet), repository=self.repo, output_dir=self.root / "out")

    def test_mixed_primary_and_allowlisted_support_edits_materialize(self) -> None:
        target_content = "---\nname: fixture\n---\n# Fixture\n\nA bounded rule.\n"
        target_edit = self.packet()["edits"][0]
        target_edit["content"] = target_content
        target_edit["after_digest"] = MATERIALIZER.digest_bytes(target_content.encode())
        registry_old = (self.repo / "registry" / "capabilities.json").read_bytes()
        registry_content = registry_old + b"\n"
        support = [
            {"path": "registry/capabilities.json", "role": "registry", "operation": "replace", "before_digest": MATERIALIZER.digest_bytes(registry_old), "after_digest": MATERIALIZER.digest_bytes(registry_content), "content": registry_content.decode()},
            {"path": "tests/fixture-support.md", "role": "test", "operation": "create", "before_digest": None, "after_digest": MATERIALIZER.digest_bytes(b"fixture test\n"), "content": "fixture test\n"},
            {"path": "docs/fixture-learning.md", "role": "documentation", "operation": "create", "before_digest": None, "after_digest": MATERIALIZER.digest_bytes(b"fixture docs\n"), "content": "fixture docs\n"},
        ]
        packet = self.packet(edits=[target_edit, *support])
        receipt = MATERIALIZER.materialize_change(packet, self.authorization(packet), repository=self.repo, output_dir=self.root / "out")
        self.assertEqual("prepared", receipt["status"])
        self.assertTrue(receipt["active_checkout"]["unchanged"])
        self.assertEqual(4, len(receipt["edits"]))

    def test_provider_target_and_bad_digest_reject_without_output(self) -> None:
        packet = self.packet(target={
            "canonical_name": "fixture",
            "capability_path": "skills/imported/provider/fixture/SKILL.md",
            "provider": "provider",
            "package": "provider",
            "upstream_pin": "a" * 40,
        })
        with self.assertRaises(MATERIALIZER.MaterializationError):
            MATERIALIZER.materialize_change(packet, self.authorization(packet), repository=self.repo, output_dir=self.root / "out")
        packet = self.packet()
        packet["edits"][0]["after_digest"] = "0" * 64
        with self.assertRaises(MATERIALIZER.MaterializationError):
            MATERIALIZER.materialize_change(packet, self.authorization(packet), repository=self.repo, output_dir=self.root / "out2")

    def test_active_checkout_and_outputs_are_unchanged_and_rerun_is_idempotent(self) -> None:
        packet = self.packet()
        before_status = subprocess.check_output(["git", "-C", str(self.repo), "status", "--porcelain=v1", "--untracked-files=all"], text=True)
        output = self.root / "out"
        first = MATERIALIZER.materialize_change(packet, self.authorization(packet), repository=self.repo, output_dir=output)
        second = MATERIALIZER.materialize_change(packet, self.authorization(packet), repository=self.repo, output_dir=output)
        self.assertEqual(first, second)
        self.assertEqual(self.base, subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip())
        self.assertEqual(before_status, subprocess.check_output(["git", "-C", str(self.repo), "status", "--porcelain=v1", "--untracked-files=all"], text=True))
        self.assertEqual(0o700, output.stat().st_mode & 0o777)
        self.assertTrue(all(path.stat().st_mode & 0o077 == 0 for path in output.iterdir()))

    def test_authorization_is_exactly_bound_and_symlink_parent_is_rejected(self) -> None:
        packet = self.packet()
        bad = self.authorization(packet, change_digest="0" * 64)
        with self.assertRaisesRegex(MATERIALIZER.MaterializationError, "exact packet digest"):
            MATERIALIZER.materialize_change(packet, bad, repository=self.repo, output_dir=self.root / "bad")
        link = self.root / "link"
        link.symlink_to(self.root / "missing", target_is_directory=True)
        with self.assertRaises(MATERIALIZER.MaterializationError):
            MATERIALIZER.materialize_change(packet, self.authorization(packet), repository=self.repo, output_dir=link / "out")

        loose = self.root / "loose"
        loose.mkdir(mode=0o750)
        with self.assertRaisesRegex(MATERIALIZER.MaterializationError, "0700"):
            MATERIALIZER.materialize_change(packet, self.authorization(packet), repository=self.repo, output_dir=loose)

    def test_automatic_weekly_mode_accepts_only_existing_skill_or_reference_replacements(self) -> None:
        packet = self.packet()
        campaign, campaign_digest = self.automatic_campaign(packet)
        receipt = MATERIALIZER.materialize_change(
            packet,
            self.automatic_authorization(packet),
            repository=self.repo,
            output_dir=self.root / "automatic",
            policy={
                "materialization": {"allowed_roles": ["skill", "reference", "registry", "test", "documentation"]},
                "automatic_weekly_design_promotion": {
                    "state": "active",
                    "authorization_contract": "weekly-design-auto-promotion-approved-v1",
                    "maximum_changed_files": 3,
                    "maximum_total_bytes": 32768,
                },
            },
            automatic_weekly=True,
            campaign_receipt=campaign,
            campaign_receipt_digest=campaign_digest,
        )
        self.assertEqual("weekly-design-auto-promotion-approved-v1", receipt["authorization"]["authorization_contract"])
        self.assertEqual(packet["source_lineage"]["campaign_run_id"], receipt["authorization"]["campaign_run_id"])

        support = self.packet()["edits"][0]
        support.update({"path": "tests/fixture.md", "role": "test", "operation": "create", "before_digest": None})
        support["after_digest"] = MATERIALIZER.digest_bytes(support["content"].encode())
        rejected = self.packet(edits=[support])
        with self.assertRaisesRegex(MATERIALIZER.MaterializationError, "automatic weekly"):
            MATERIALIZER.materialize_change(
                rejected,
                self.automatic_authorization(rejected),
                repository=self.repo,
                output_dir=self.root / "rejected",
                policy={
                    "materialization": {"allowed_roles": ["skill", "reference", "registry", "test", "documentation"]},
                    "automatic_weekly_design_promotion": {
                        "state": "active",
                        "authorization_contract": "weekly-design-auto-promotion-approved-v1",
                        "maximum_changed_files": 3,
                        "maximum_total_bytes": 32768,
                    },
                },
                automatic_weekly=True,
            )

    def test_automatic_weekly_forged_failure_id_is_rejected_before_materialization(self) -> None:
        packet = self.packet()
        campaign, campaign_digest = self.automatic_campaign(packet)
        packet["rationale"]["materiality"]["critique_failure_ids"] = ["failure:" + "f" * 16]
        output = self.root / "forged"
        with self.assertRaisesRegex(MATERIALIZER.MaterializationError, "material failure IDs"):
            MATERIALIZER.materialize_change(
                packet,
                self.automatic_authorization(packet),
                repository=self.repo,
                output_dir=output,
                policy={
                    "materialization": {"allowed_roles": ["skill", "reference", "registry", "test", "documentation"]},
                    "automatic_weekly_design_promotion": {
                        "state": "active",
                        "authorization_contract": "weekly-design-auto-promotion-approved-v1",
                        "maximum_changed_files": 3,
                        "maximum_total_bytes": 32768,
                    },
                },
                automatic_weekly=True,
                campaign_receipt=campaign,
                campaign_receipt_digest=campaign_digest,
            )
        self.assertFalse(output.exists())

    def test_automatic_campaign_cannot_bypass_preflight_by_omitting_mode_flag(self) -> None:
        packet = self.packet()
        self.automatic_campaign(packet)
        output = self.root / "implicit-automatic"
        with self.assertRaisesRegex(MATERIALIZER.MaterializationError, "campaign receipt and digest"):
            MATERIALIZER.materialize_change(
                packet,
                self.automatic_authorization(packet),
                repository=self.repo,
                output_dir=output,
                policy={
                    "materialization": {"allowed_roles": ["skill", "reference"]},
                    "automatic_weekly_design_promotion": {
                        "state": "active",
                        "authorization_contract": "weekly-design-auto-promotion-approved-v1",
                        "maximum_changed_files": 3,
                        "maximum_total_bytes": 32768,
                    },
                },
            )
        self.assertFalse(output.exists())

    def test_cli_cannot_bypass_automatic_preflight_by_omitting_mode_flag(self) -> None:
        packet = self.packet()
        self.automatic_campaign(packet)
        authorization = self.automatic_authorization(packet)
        policy = {
            "materialization": {"allowed_roles": ["skill", "reference"]},
            "automatic_weekly_design_promotion": {
                "state": "active",
                "authorization_contract": "weekly-design-auto-promotion-approved-v1",
                "maximum_changed_files": 3,
                "maximum_total_bytes": 32768,
            },
        }
        packet_path = self.root / "automatic-packet.json"
        authorization_path = self.root / "automatic-authorization.json"
        policy_path = self.root / "automatic-policy.json"
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        authorization_path.write_text(json.dumps(authorization), encoding="utf-8")
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        output = self.root / "cli-implicit-automatic"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/materialize-capability-change.py"),
                "--packet", str(packet_path),
                "--authorization", str(authorization_path),
                "--repository", str(self.repo),
                "--policy", str(policy_path),
                "--out", str(output),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("campaign receipt and digest", result.stderr)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
