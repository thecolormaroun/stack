from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("materialize", ROOT / "scripts/materialize-bookmark-candidates.py")
assert SPEC and SPEC.loader
MATERIALIZE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MATERIALIZE)


class MaterializeBookmarkCandidatesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Path(self.tmp.name) / "ledger.sqlite"
        connection = sqlite3.connect(self.ledger)
        connection.execute("CREATE TABLE canonical_items (canonical TEXT PRIMARY KEY, intake_id TEXT NOT NULL, first_seen_at TEXT NOT NULL)")
        connection.execute("""CREATE TABLE observations (
          id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, canonical TEXT NOT NULL,
          source_revision TEXT NOT NULL, content_digest TEXT NOT NULL,
          policy_digest TEXT NOT NULL, observed_at TEXT NOT NULL,
          run_id TEXT NOT NULL, raw_json TEXT NOT NULL
        )""")
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def add(self, canonical: str, intake_id: str, source: str, revision: str, raw: dict) -> None:
        connection = sqlite3.connect(self.ledger)
        connection.execute("INSERT OR IGNORE INTO canonical_items VALUES (?, ?, 'now')", (canonical, intake_id))
        connection.execute(
            "INSERT INTO observations VALUES (NULL, ?, ?, ?, ?, 'policy', 'now', 'run', ?)",
            (source, canonical, revision, f"digest-{source}-{revision}", json.dumps(raw)),
        )
        connection.commit()
        connection.close()

    def test_groups_cross_source_observations_into_one_repository_candidate(self) -> None:
        identity = "intake_AbCdEf0123456789_Group"
        canonical = "https://github.com/example/project"
        self.add(canonical, identity, "github-stars", "one", {"description": "Frontend design tool", "license": {"spdx_id": "MIT"}})
        self.add(canonical, identity, "github-linked", "two", {"license": "MIT", "updated_at": "two"})

        candidates = MATERIALIZE.materialize(self.ledger)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["kind"], "repository")
        self.assertEqual(candidate["license"], "MIT")
        self.assertEqual(candidate["relevance"], "relevant")
        self.assertEqual(candidate["evidence_count"], 2)
        self.assertEqual(candidate["source_id"], "github-linked")
        self.assertNotIn("github.com", json.dumps(candidate))

    def test_group_pin_is_idempotent_but_changed_revision_reenters(self) -> None:
        identity = "intake_AbCdEf0123456789_Change"
        canonical = "https://example.com/design"
        self.add(canonical, identity, "arc-sidebar", "one", {"savedTitle": "Interface design"})
        first = MATERIALIZE.materialize(self.ledger)
        MATERIALIZE.materialize(self.ledger, apply=True, selected_pins={first[0]["source_pin"]})
        self.assertEqual(MATERIALIZE.materialize(self.ledger), [])

        self.add(canonical, identity, "arc-sidebar", "two", {"savedTitle": "Interface design updated"})
        changed = MATERIALIZE.materialize(self.ledger)
        self.assertEqual(len(changed), 1)
        self.assertNotEqual(first[0]["source_pin"], changed[0]["source_pin"])

    def test_curation_policy_change_reenters_same_canonical_revision(self) -> None:
        identity = "intake_AbCdEf0123456789_Policy"
        canonical = "https://example.com/design"
        self.add(canonical, identity, "arc-sidebar", "one", {"savedTitle": "Interface design"})
        first = MATERIALIZE.materialize(self.ledger, curation_policy_digest="policy-one")
        MATERIALIZE.materialize(
            self.ledger,
            apply=True,
            selected_pins={first[0]["source_pin"]},
            curation_policy_digest="policy-one",
        )

        self.assertEqual(MATERIALIZE.materialize(self.ledger, curation_policy_digest="policy-one"), [])
        changed = MATERIALIZE.materialize(self.ledger, curation_policy_digest="policy-two")
        self.assertEqual(len(changed), 1)
        self.assertNotEqual(first[0]["source_pin"], changed[0]["source_pin"])

    def test_private_text_affects_relevance_but_never_leaves_candidate(self) -> None:
        identity = "intake_AbCdEf0123456789_Private"
        secret = "private title about typography and interface design"
        self.add("https://example.com/private", identity, "field-theory", "one", {"text": secret})

        candidate = MATERIALIZE.materialize(self.ledger)[0]

        self.assertEqual(candidate["relevance"], "relevant")
        self.assertNotIn(secret, json.dumps(candidate))

    def test_explicit_hermes_identifier_survives_canonical_deduplication(self) -> None:
        canonical_id = "intake_AbCdEf0123456789_Canonical"
        hermes_id = "intake_AbCdEf0123456789_Hermes"
        canonical = "https://example.com/design"
        self.add(canonical, canonical_id, "field-theory", "one", {"text": "design system"})
        self.add(canonical, canonical_id, "hermes-links", "two", {"intake_id": hermes_id, "canonical_url": canonical})

        candidate = MATERIALIZE.materialize(self.ledger)[0]

        self.assertEqual(candidate["intake_id"], canonical_id)
        self.assertEqual(candidate["hermes_intake_id"], hermes_id)


if __name__ == "__main__":
    unittest.main()
