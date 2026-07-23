from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SkillArchitectureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.families = json.loads((ROOT / "registry/families.json").read_text())

    def test_family_ids_and_roles_are_stable(self) -> None:
        ids = [family["id"] for family in self.families["families"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, ["core", "product", "planning", "design", "engineering", "orchestration", "review", "qa", "delivery", "knowledge", "platform"])
        roles = set(self.families["artifact_roles"])
        for family in self.families["families"]:
            self.assertTrue(set(family["allowed_roles"]).issubset(roles))
            self.assertIn(family["default_trust_class"], {"read-only", "local-mutation", "external-mutation", "costly", "irreversible"})

    def test_documented_taxonomy_and_provider_provenance_rules_exist(self) -> None:
        text = (ROOT / "docs/skill-architecture.md").read_text().lower()
        self.assertIn("provider provenance is independent", text)
        self.assertIn("external and reference-only", text)
        self.assertIn("one primary family", text)


if __name__ == "__main__":
    unittest.main()
