from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("materialize_capability_change", ROOT / "scripts/materialize-capability-change.py")
assert SPEC and SPEC.loader
MATERIALIZER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MATERIALIZER)


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
        packet["source_lineage"].update({
            "campaign_run_id": "weekly-fixture",
            "campaign_receipt_digest": "5" * 64,
            "design_packet_artifact_digest": "6" * 64,
            "retrieval_artifact_digest": "7" * 64,
            "candidate_evaluation_artifact_digest": "8" * 64,
        })
        value = self.authorization(packet)
        value.update({
            "authorization_contract": "weekly-design-auto-promotion-approved-v1",
            "campaign_run_id": "weekly-fixture",
            "campaign_receipt_digest": "5" * 64,
        })
        value.update(overrides)
        return value

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
        )
        self.assertEqual("weekly-design-auto-promotion-approved-v1", receipt["authorization"]["authorization_contract"])
        self.assertEqual("weekly-fixture", receipt["authorization"]["campaign_run_id"])

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


if __name__ == "__main__":
    unittest.main()
