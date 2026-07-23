from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("evaluate_candidate", ROOT / "scripts/evaluate-capability-candidate.py")
assert SPEC and SPEC.loader
EVALUATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVALUATOR)


@unittest.skipUnless(os.uname().sysname == "Darwin" and Path("/usr/bin/sandbox-exec").is_file(), "requires macOS sandbox-exec")
class EvaluateCapabilityCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "candidate-repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Fixture"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "fixture@example.invalid"], check=True)
        (self.repo / "SKILL.md").write_text("---\nname: fixture\ndescription: Fixture.\n---\n# Fixture\n", encoding="utf-8")
        (self.repo / "capability.json").write_text(json.dumps({"schema_version": 1, "canonical_name": "fixture"}), encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "SKILL.md", "capability.json"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "fixture"], check=True)
        self.pin = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        self.packet = {
            "schema_version": 1,
            "packet_kind": "capability-evaluation-candidate",
            "intake_id": "fixture-intake",
            "disposition": "new-candidate-skill",
            "source_pin": self.pin,
            "prior_provenance": None,
            "evaluation": {
                "sandbox": {},
                "status": "blocked-pending-provenance-and-evaluation-review",
                "human_gates": ["provenance-review", "evaluation-review", "publication-review"],
            },
            "activation": "prohibited-until-separate-publication-review",
        }
        self.packet_path = self.root / "packet.json"
        self.packet_path.write_text(json.dumps(self.packet), encoding="utf-8")
        self.review_path = self.root / "review.json"
        self.review_path.write_text(json.dumps(self.review()), encoding="utf-8")
        self.receipt_path = self.root / "receipt.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def review(self, **overrides):
        value = {
            "schema_version": 1,
            "packet_digest": EVALUATOR.digest_json(self.packet),
            "source_pin": self.pin,
            "profile": "skill-structure-v1",
            "provenance_review": "approved",
            "evaluation_execution_review": "approved",
            "reviewed_by": "fixture-reviewer",
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }
        value.update(overrides)
        return value

    def evaluate(self):
        return EVALUATOR.run_evaluation(
            self.packet_path,
            self.review_path,
            self.repo,
            ROOT / "config/candidate-evaluation-profiles.json",
            "skill-structure-v1",
            self.receipt_path,
        )

    def test_exact_commit_runs_in_verified_sandbox_and_emits_only_receipt(self):
        receipt = self.evaluate()

        self.assertEqual("passed", receipt["status"])
        self.assertTrue(all(receipt["sandbox"].values()))
        self.assertTrue(all(receipt["checks"].values()))
        self.assertEqual("human-evaluation-result-review", receipt["next_gate"])
        self.assertEqual("prohibited-pending-result-review-and-publication-review", receipt["activation"])
        serialized = self.receipt_path.read_text(encoding="utf-8")
        self.assertNotIn(str(self.repo), serialized)
        self.assertNotIn("fixture-reviewer", serialized)

    def test_unreviewed_candidate_fails_before_sandbox(self):
        self.review_path.write_text(json.dumps(self.review(provenance_review="pending")), encoding="utf-8")
        with self.assertRaisesRegex(EVALUATOR.EvaluationError, "provenance review"):
            self.evaluate()
        self.assertFalse(self.receipt_path.exists())

    def test_review_cannot_authorize_a_different_packet_or_pin(self):
        self.review_path.write_text(json.dumps(self.review(packet_digest="0" * 64)), encoding="utf-8")
        with self.assertRaisesRegex(EVALUATOR.EvaluationError, "does not match"):
            self.evaluate()

    def test_executable_candidate_file_fails_without_being_run(self):
        attack = self.repo / "attack.sh"
        attack.write_text("touch escaped\n", encoding="utf-8")
        attack.chmod(0o755)
        subprocess.run(["git", "-C", str(self.repo), "add", "attack.sh"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "malicious fixture"], check=True)
        self.pin = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        self.packet["source_pin"] = self.pin
        self.packet_path.write_text(json.dumps(self.packet), encoding="utf-8")
        self.review_path.write_text(json.dumps(self.review()), encoding="utf-8")

        receipt = self.evaluate()

        self.assertEqual("failed", receipt["status"])
        self.assertFalse(receipt["checks"]["no_executable_candidate_files"])
        self.assertFalse((self.repo / "escaped").exists())

    def test_source_pin_must_exist_in_local_repository(self):
        self.packet["source_pin"] = "f" * 40
        self.packet_path.write_text(json.dumps(self.packet), encoding="utf-8")
        self.review_path.write_text(json.dumps(self.review(source_pin="f" * 40, packet_digest=EVALUATOR.digest_json(self.packet))), encoding="utf-8")
        with self.assertRaisesRegex(EVALUATOR.EvaluationError, "unavailable"):
            self.evaluate()


if __name__ == "__main__":
    unittest.main()
