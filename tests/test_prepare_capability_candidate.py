import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("prepare", ROOT / "scripts/prepare-capability-candidate.py")
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)

POLICY = json.loads((ROOT / "config/capability-activation-policy.json").read_text())
SAFE = {
    "intake_id": "intake_fixture",
    "disposition": "skill-update",
    "source_pin": "b" * 40,
    "review_state": "blocked-pending-human-review",
    "prior_provenance": "repo:existing",
    "dependencies": [],
}


class PrepareCapabilityCandidateTest(unittest.TestCase):
    def test_prepares_immutable_sandboxed_and_human_gated_packet(self):
        packet = prepare.prepare(SAFE, POLICY)
        self.assertEqual("deny", packet["evaluation"]["sandbox"]["network"])
        self.assertEqual("blocked-pending-provenance-and-evaluation-review", packet["evaluation"]["status"])
        self.assertEqual("prohibited-until-separate-publication-review", packet["activation"])
        self.assertEqual("repo:existing", packet["prior_provenance"])

    def test_malicious_candidate_fails_closed(self):
        malicious = dict(SAFE, requested_actions=["read parent workspace", "use network and ambient credentials"])
        with self.assertRaises(prepare.PreparationError):
            prepare.prepare(malicious, POLICY)

    def test_private_evidence_fails_closed(self):
        with self.assertRaises(prepare.PreparationError):
            prepare.prepare(dict(SAFE, local_path="/private/corpus"), POLICY)

    def test_missing_immutable_pin_fails_closed(self):
        with self.assertRaises(prepare.PreparationError):
            prepare.prepare(dict(SAFE, source_pin="main"), POLICY)


if __name__ == "__main__":
    unittest.main()
