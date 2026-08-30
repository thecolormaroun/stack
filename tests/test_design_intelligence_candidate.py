from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATERIALIZER_SPEC = importlib.util.spec_from_file_location("materialize_capability_change", ROOT / "scripts/materialize-capability-change.py")
EVALUATOR_SPEC = importlib.util.spec_from_file_location("evaluate_design_intelligence_candidate", ROOT / "scripts/evaluate-design-intelligence-candidate.py")
assert MATERIALIZER_SPEC and MATERIALIZER_SPEC.loader and EVALUATOR_SPEC and EVALUATOR_SPEC.loader
MATERIALIZER = importlib.util.module_from_spec(MATERIALIZER_SPEC)
MATERIALIZER_SPEC.loader.exec_module(MATERIALIZER)
EVALUATOR = importlib.util.module_from_spec(EVALUATOR_SPEC)
EVALUATOR_SPEC.loader.exec_module(EVALUATOR)

FIXTURES = ROOT / "tests" / "fixtures" / "design-evaluation"
GATES = {
    "structure": True, "behavior": True, "visual": True, "accessibility": True,
    "privacy": True, "citation": True, "mobile_width": True, "content_overflow": True,
    "primary_workflow": True, "critical_data": True, "html": True,
}
DIMS = {"task_usefulness": 0.5, "visual_quality": 0.5, "behavior": 0.5, "accessibility": 0.5, "privacy": 0.5, "citation": 0.5}


class DesignIntelligenceCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.chmod(self.root, 0o700)
        self.repo = self.root / "repo"
        self.repo.mkdir(mode=0o700)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Fixture"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "fixture@example.invalid"], check=True)
        target = self.repo / "skills" / "design" / "fixture"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("---\nname: fixture\n---\n# Fixture\n", encoding="utf-8")
        (self.repo / "registry").mkdir()
        (self.repo / "registry" / "capabilities.json").write_text(json.dumps({
            "capabilities": [{"canonical_name": "fixture", "ownership": {"provider": "stack", "package": "stack", "source_path": "skills/design/fixture/SKILL.md"}, "source": {"skill_path": "skills/design/fixture/SKILL.md"}}],
        }), encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "base"], check=True)
        self.base = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        self.harness = self.root / "harness"
        self.harness.mkdir(mode=0o700)
        self.manifests: dict[str, Path] = {}
        for split in ("development", "holdout", "rotating-canary"):
            source = FIXTURES / f"{split}-manifest.json"
            target = self.harness / source.name
            shutil.copyfile(source, target)
            os.chmod(target, 0o600)
            self.manifests[split.replace("-", "_")] = target
        self.packet = self.make_packet()
        self.materialization = self.make_materialization()
        self.profile = EVALUATOR._profile(json.loads((ROOT / "config" / "candidate-evaluation-profiles.json").read_text()), "design-learning-v1")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def make_packet(self) -> dict:
        old = (self.repo / "skills/design/fixture/SKILL.md").read_bytes()
        content = old + b"\nBounded rule.\n"
        packet = {
            "schema_version": 1,
            "change_id": "change:" + "a" * 16,
            "state": "candidate_quarantined",
            "approval_state": "candidate_unapproved",
            "base_commit": self.base,
            "source_lineage": {"packet_id": "packet:" + "b" * 16, "packet_digest": "c" * 64, "card_ids": ["card:" + "d" * 16], "revision_ids": ["revision:" + "e" * 16], "evidence_ids": ["evidence:" + "f" * 16], "parent_digests": ["1" * 64]},
            "target": {"canonical_name": "fixture", "capability_path": "skills/design/fixture/SKILL.md", "provider": "stack", "package": "stack", "upstream_pin": None},
            "rationale": {"change_kind": "skill-update", "expected_behavior": ["Apply a bounded rule."], "overlap_analysis": {"status": "no_collision", "compared_capabilities": [], "explanation": "No overlap."}, "license_posture": "stack-owned-reviewed-derivative", "privacy_class": "reviewed-software-derivative"},
            "rollback": {"base_commit": self.base, "path_digests": {"skills/design/fixture/SKILL.md": MATERIALIZER.digest_bytes(old)}},
            "edits": [{"path": "skills/design/fixture/SKILL.md", "role": "skill", "operation": "replace", "before_digest": MATERIALIZER.digest_bytes(old), "after_digest": MATERIALIZER.digest_bytes(content), "content": content.decode()}],
            "evaluation": {"profile": "design-learning-v1", "development_manifest_digest": EVALUATOR.digest_file(self.manifests["development"]), "holdout_manifest_digest": EVALUATOR.digest_file(self.manifests["holdout"]), "rotating_canary_manifest_digest": EVALUATOR.digest_file(self.manifests["rotating_canary"]), "harness_required": True},
        }
        return packet

    def make_materialization(self) -> dict:
        auth = {"schema_version": 1, "change_digest": MATERIALIZER.digest_json(self.packet), "base_commit": self.base, "scope": "isolated-owner-local-patch-only", "decision": "approved", "reviewed_by": "fixture-reviewer", "reviewed_at": "2026-08-23T00:00:00Z"}
        return MATERIALIZER.materialize_change(self.packet, auth, repository=self.repo, output_dir=self.root / "materialization")

    def results(self, *, improvement: float = 0.06, feedback: object | None = None, gate_overrides: dict[str, bool] | None = None, candidate_dimensions: dict[str, float] | None = None, candidate_by_rep: list[float] | None = None, disagreement: tuple[float, float] | None = None) -> dict[str, Path]:
        output: dict[str, Path] = {}
        feedback = {"kind": "real", "text": "Used on a real task."} if feedback is None else feedback
        for split, manifest_path in self.manifests.items():
            manifest = json.loads(manifest_path.read_text())
            rows = []
            for repetition in range(3):
                fixture_rows = []
                for fixture in manifest["fixtures"]:
                    baseline_dims = dict(DIMS)
                    candidate_dims = dict(candidate_dimensions or {name: value + improvement for name, value in DIMS.items()})
                    score = 0.5 + improvement
                    if candidate_dimensions is not None:
                        score = sum(float(self.profile["dimension_weights"][name]) * value for name, value in candidate_dims.items()) if hasattr(self, "profile") else sum(candidate_dims.values()) / len(candidate_dims)
                    if candidate_by_rep is not None:
                        score = candidate_by_rep[repetition]
                        candidate_dims = {name: score for name in DIMS}
                    gates = dict(GATES)
                    gates.update(gate_overrides or {})
                    candidate = {"overall": score, "dimensions": candidate_dims, "hard_gates": gates, "task_usefulness_feedback": feedback}
                    row = {"fixture_id": fixture["id"], "baseline": {"overall": 0.5, "dimensions": baseline_dims}, "candidate": candidate}
                    if disagreement is not None:
                        row["candidate"]["rubric_score"], row["candidate"]["task_usefulness_score"] = disagreement
                    fixture_rows.append(row)
                rows.append({"repetition": repetition + 1, "fixtures": fixture_rows})
            path = self.harness / f"{split}-results.json"
            path.write_text(json.dumps({
                "schema_version": 1, "split": split, "results": rows,
                "candidate_packet_digest": EVALUATOR.digest_json(self.packet),
                "materialization_receipt_digest": EVALUATOR.digest_json(self.materialization),
                "manifest_digest": EVALUATOR.digest_file(manifest_path),
            }, indent=2) + "\n")
            os.chmod(path, 0o600)
            output[split] = path
        return output

    def evaluate(self, result_paths: dict[str, Path] | None = None, **kwargs: object) -> dict:
        results = result_paths or self.results(**kwargs)
        return EVALUATOR.evaluate_design_candidate(self.packet, self.materialization, manifests=self.manifests, results=results, profile=self.profile, harness_root=self.harness)

    def test_missing_or_incomplete_harness_is_blocked(self) -> None:
        missing = EVALUATOR.evaluate_design_candidate(self.packet, self.materialization, manifests={}, results={}, profile=self.profile, harness_root=self.root / "missing")
        self.assertEqual("blocked-eval", missing["status"])
        incomplete = EVALUATOR.evaluate_design_candidate(self.packet, self.materialization, manifests=self.manifests, results={}, profile=self.profile, harness_root=self.harness)
        self.assertEqual("blocked-eval", incomplete["status"])

        self.harness.chmod(0o750)
        unsafe = EVALUATOR.evaluate_design_candidate(self.packet, self.materialization, manifests=self.manifests, results={}, profile=self.profile, harness_root=self.harness)
        self.assertEqual("blocked-eval", unsafe["status"])
        self.assertIn("unsafe_eval_root", unsafe["reason_codes"])

    def test_manual_packet_limits_remain_fail_closed(self) -> None:
        too_many = json.loads(json.dumps(self.packet))
        too_many["edits"] = [dict(too_many["edits"][0], path=f"skills/design/fixture/references/{index}.md") for index in range(6)]
        with self.assertRaisesRegex(EVALUATOR.DesignEvaluationError, "file limit"):
            EVALUATOR._validate_packet(too_many)

        oversized_edit = json.loads(json.dumps(self.packet))
        oversized_edit["edits"][0]["content"] = "x" * 65537
        with self.assertRaisesRegex(EVALUATOR.DesignEvaluationError, "content"):
            EVALUATOR._validate_packet(oversized_edit)

        oversized_total = json.loads(json.dumps(self.packet))
        oversized_total["edits"] = [
            dict(oversized_total["edits"][0], path=f"skills/design/fixture/references/{index}.md", content="x" * 50000)
            for index in range(3)
        ]
        with self.assertRaisesRegex(EVALUATOR.DesignEvaluationError, "byte limit"):
            EVALUATOR._validate_packet(oversized_total)

        external_manual = json.loads(json.dumps(self.packet))
        external_manual["edits"][0].pop("content")
        external_manual["edits"][0]["content_file"] = "candidate-content/" + "a" * 64 + ".utf8"
        with self.assertRaisesRegex(EVALUATOR.DesignEvaluationError, "shape"):
            EVALUATOR._validate_packet(external_manual)

    def test_automatic_packet_uses_external_content_without_file_limit(self) -> None:
        automatic = json.loads(json.dumps(self.packet))
        automatic["source_lineage"].update({
            "campaign_run_id": "weekly-fixture",
            "campaign_receipt_digest": "2" * 64,
            "design_packet_artifact_digest": "3" * 64,
            "retrieval_artifact_digest": "4" * 64,
            "candidate_evaluation_artifact_digest": "5" * 64,
        })
        prototype = automatic["edits"][0]
        prototype.pop("content")
        prototype["content_file"] = f"candidate-content/{prototype['after_digest']}.utf8"
        automatic["edits"] = [
            dict(prototype, path=f"skills/design/fixture/references/{index}.md")
            for index in range(6)
        ]

        digest, _evaluation = EVALUATOR._validate_packet(automatic)

        self.assertEqual(EVALUATOR.digest_json(automatic), digest)

    def test_automatic_materialization_campaign_evidence_reaches_evaluator(self) -> None:
        automatic = json.loads(json.dumps(self.packet))
        automatic["source_lineage"].update({
            "campaign_run_id": "weekly-fixture",
            "campaign_receipt_digest": "2" * 64,
            "design_packet_artifact_digest": "3" * 64,
            "retrieval_artifact_digest": "4" * 64,
            "candidate_evaluation_artifact_digest": "5" * 64,
        })
        edit = automatic["edits"][0]
        edit.pop("content")
        edit["content_file"] = f"candidate-content/{edit['after_digest']}.utf8"
        materialization = json.loads(json.dumps(self.materialization))
        materialization["change_digest"] = EVALUATOR.digest_json(automatic)
        materialization["authorization"]["change_digest"] = materialization["change_digest"]
        materialization["campaign_evidence"] = {
            "receipt_digest": automatic["source_lineage"]["campaign_receipt_digest"],
            "materiality_verified_before_materialization": True,
        }

        EVALUATOR._validate_materialization(
            materialization,
            automatic,
            EVALUATOR.digest_json(automatic),
        )

    def test_four_development_wins_do_not_override_holdout_regression_or_hard_gate(self) -> None:
        results = self.results()
        holdout = json.loads(results["holdout"].read_text())
        for repetition in holdout["results"]:
            for row in repetition["fixtures"]:
                row["candidate"]["overall"] = 0.4
                row["candidate"]["dimensions"] = {name: 0.4 for name in DIMS}
        results["holdout"].write_text(json.dumps(holdout, indent=2) + "\n")
        rejected = self.evaluate(result_paths=results)
        self.assertEqual("rejected", rejected["status"])
        self.assertIn("holdout_regression", rejected["reason_codes"])
        rejected = self.evaluate(result_paths=self.results(gate_overrides={"privacy": False}))
        self.assertEqual("rejected", rejected["status"])
        self.assertIn("hard_gate_failure", rejected["reason_codes"])
        failures = rejected["metrics"]["hard_gate_failures"]
        self.assertTrue(failures)
        self.assertTrue(all(re.fullmatch(r"evaluation-failure:[a-f0-9]{16}", failure["failure_id"]) for failure in failures))
        identities = {
            (failure["split"], failure["fixture_id"], failure["gate"]): failure["failure_id"]
            for failure in failures
        }
        self.assertEqual(len(identities), len({failure["failure_id"] for failure in failures}))

    def test_unstable_scores_or_rubric_usefulness_disagreement_requires_human(self) -> None:
        unstable = self.evaluate(result_paths=self.results(candidate_by_rep=[0.4, 0.6, 0.5]))
        self.assertEqual("human_review_required", unstable["status"])
        self.assertIn("unstable_scores", unstable["reason_codes"])
        disagreement = self.evaluate(result_paths=self.results(disagreement=(0.9, 0.5)))
        self.assertEqual("human_review_required", disagreement["status"])
        self.assertIn("rubric_usefulness_disagreement", disagreement["reason_codes"])

    def test_passing_candidate_stops_at_approval_and_remains_quarantined_and_idempotent(self) -> None:
        results = self.results()
        first = self.evaluate(result_paths=results)
        second = self.evaluate(result_paths=results)
        self.assertEqual("awaiting_approval", first["status"])
        self.assertEqual(first, second)
        self.assertFalse(first["activation"]["active_pointer"])
        self.assertFalse(first["activation"]["install"])
        self.assertFalse(first["activation"]["publish"])
        self.assertFalse(first["activation"]["draft_pr"])
        self.assertFalse(first["quarantine"]["retrieval_truth"])

    def test_aggregate_only_scores_cannot_bypass_dimension_regression_checks(self) -> None:
        results = self.results()
        for path in results.values():
            payload = json.loads(path.read_text())
            for repetition in payload["results"]:
                for row in repetition["fixtures"]:
                    row["baseline"].pop("dimensions")
                    row["candidate"].pop("dimensions")
            path.write_text(json.dumps(payload))
        receipt = self.evaluate(result_paths=results)
        self.assertEqual("blocked-eval", receipt["status"])

    def test_results_require_exact_candidate_and_manifest_binding(self) -> None:
        for key in ("candidate_packet_digest", "materialization_receipt_digest", "manifest_digest"):
            results = self.results()
            payload = json.loads(results["development"].read_text())
            payload[key] = "0" * 64
            results["development"].write_text(json.dumps(payload))
            with self.subTest(key=key):
                receipt = self.evaluate(result_paths=results)
                self.assertEqual("blocked-eval", receipt["status"])

    def test_duplicate_repetitions_do_not_satisfy_repeated_evidence(self) -> None:
        results = self.results()
        payload = json.loads(results["development"].read_text())
        payload["results"] = [payload["results"][0]] * 3
        results["development"].write_text(json.dumps(payload))
        self.assertEqual("blocked-eval", self.evaluate(result_paths=results)["status"])

    def test_synthetic_only_feedback_cannot_promote_and_missing_real_feedback_is_visible(self) -> None:
        synthetic = self.evaluate(result_paths=self.results(feedback={"kind": "synthetic", "text": "fixture simulation"}))
        self.assertEqual("human_review_required", synthetic["status"])
        self.assertIn("missing_real_task_usefulness_feedback", synthetic["reason_codes"])
        no_feedback = self.evaluate(result_paths=self.results(feedback=[]))
        self.assertEqual("blocked-eval", no_feedback["status"])

    def test_per_fixture_dimension_regression_cannot_be_averaged_away(self) -> None:
        dimensions = dict(DIMS)
        dimensions["privacy"] = 0.4
        rejected = self.evaluate(result_paths=self.results(candidate_dimensions=dimensions))
        self.assertEqual("rejected", rejected["status"])
        self.assertIn("fixture_dimension_regression", rejected["reason_codes"])

    def test_exact_manifest_digest_is_required(self) -> None:
        self.packet["evaluation"]["development_manifest_digest"] = "0" * 64
        self.materialization["change_digest"] = MATERIALIZER.digest_json(self.packet)
        result = self.evaluate(result_paths=self.results())
        self.assertEqual("blocked-eval", result["status"])


if __name__ == "__main__":
    unittest.main()
