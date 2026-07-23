import importlib.util
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("triage", ROOT / "scripts/triage-bookmark-candidates.py")
triage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(triage)


POLICY = {
    "decision_cap": 2,
    "accepted_licenses": ["MIT"],
    "review_gates": ["provenance-review", "evaluation-review", "publication-review"],
    "evaluation": {},
}
CATALOG = {"capabilities": [{"canonical_name": "existing", "provenance": {"source_identity": "repo:existing"}}]}


def candidate(identity, rank, **extra):
    value = {
        "intake_id": "intake_" + hashlib.sha256(identity.encode()).hexdigest()[:24],
        "source_id": "fixture",
        "source_identity": identity,
        "source_pin": "a" * 40,
        "scores": {"leverage": rank, "novelty": 0, "evidence": 0, "implementation_cost": 0, "evaluation_cost": 0},
    }
    value.update(extra)
    return value


class TriageBookmarkCandidatesTest(unittest.TestCase):
    def test_duplicate_becomes_evidence_update_and_keeps_prior_provenance(self):
        packet = triage.triage([candidate("repo:existing", 5, evidence_count=2, evidence_ids=["evidence_new"])], CATALOG, POLICY)
        record = packet["candidates"][0]
        self.assertEqual("evidence-attachment", record["disposition"])
        self.assertEqual("repo:existing", record["prior_provenance"])
        self.assertTrue(record["evidence_update"])
        self.assertEqual(["evidence_new"], record["evidence_ids"])

    def test_each_smallest_change_disposition_has_a_fixture(self):
        cases = [
            (candidate("repo:existing", 9), "no-action"),
            (candidate("repo:existing", 8, evidence_count=1), "evidence-attachment"),
            (candidate("reference", 7, requested_disposition="reference-update"), "reference-update"),
            (candidate("skill", 6, requested_disposition="skill-update"), "skill-update"),
            (candidate("new", 5, requested_disposition="new-candidate-skill"), "new-candidate-skill"),
            (candidate("upstream", 4, kind="repository", license="MIT"), "upstream-import-update"),
        ]
        packet = triage.triage([value for value, _ in cases], CATALOG, dict(POLICY, decision_cap=6))
        self.assertEqual([expected for _, expected in cases], [item["disposition"] for item in packet["candidates"]])

    def test_unlicensed_repository_is_blocked_without_import(self):
        packet = triage.triage([candidate("repo:unlicensed", 5, kind="repository", license="proprietary")], CATALOG, POLICY)
        record = packet["candidates"][0]
        self.assertEqual("blocked-import", record["disposition"])
        self.assertEqual("license-unacceptable", record["blocker"])

    def test_lower_ranked_overflow_is_retained(self):
        packet = triage.triage([candidate("one", 9), candidate("two", 8), candidate("three", 7)], CATALOG, POLICY)
        self.assertEqual([candidate("one", 0)["intake_id"], candidate("two", 0)["intake_id"]], [item["intake_id"] for item in packet["candidates"]])
        self.assertEqual([candidate("three", 0)["intake_id"]], [item["intake_id"] for item in packet["deferred"]])

    def test_public_packet_redacts_private_evidence(self):
        packet = triage.triage([candidate("one", 9, title="secret title", url="https://private.example/a", notes="do not expose")], CATALOG, POLICY)
        encoded = str(packet)
        self.assertNotIn("secret title", encoded)
        self.assertNotIn("private.example", encoded)
        self.assertFalse(triage.contains_private_field(packet))

    def test_empty_input_is_no_change_receipt(self):
        self.assertTrue(triage.triage([], CATALOG, POLICY)["no_change"])

    def test_rejects_nonopaque_intake_ids_and_nonhex_source_pins(self):
        with self.assertRaises(triage.TriageError):
            triage.triage([candidate("one", 1, intake_id="secret-token")], CATALOG, POLICY)
        with self.assertRaises(triage.TriageError):
            triage.triage([candidate("one", 1, source_pin="secret-token")], CATALOG, POLICY)

    def test_fake_hermes_callback_receives_unchanged_opaque_ids_for_all_outcomes(self):
        records = [
            {"hermes_intake_id": candidate("proposed", 0)["intake_id"], "disposition": "reference-update"},
            {"hermes_intake_id": candidate("none", 0)["intake_id"], "disposition": "no-action"},
            {"hermes_intake_id": candidate("blocked", 0)["intake_id"], "disposition": "blocked-import"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); log = root / "calls"; fake = root / "hermes.py"
            fake.write_text("import os, sys\nopen(os.environ['CALL_LOG'], 'a').write(' '.join(sys.argv[1:]) + '\\n')\n")
            for record in records:
                subprocess.run(["python3", *triage.hermes_callback_argv(str(fake), record)], check=True,
                               env={**os.environ, "CALL_LOG": str(log)})
            calls = log.read_text()
        for record, outcome in zip(records, ("proposed", "no-action", "blocked")):
            self.assertIn(f"--intake-id {record['hermes_intake_id']} --state {outcome}", calls)

    def test_hermes_callbacks_only_target_explicit_hermes_rows(self):
        explicit = {"intake_id": candidate("explicit", 0)["intake_id"], "hermes_intake_id": candidate("explicit-hermes", 0)["intake_id"], "source_id": "hermes-links", "disposition": "reference-update"}
        scheduled = {"intake_id": candidate("scheduled", 0)["intake_id"], "source_id": "field-theory", "disposition": "reference-update"}

        self.assertEqual(triage.hermes_callback_records({"candidates": [scheduled, explicit]}), [explicit])


if __name__ == "__main__":
    unittest.main()
