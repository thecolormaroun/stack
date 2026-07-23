"""Focused Phase 1 architecture classification and reconciliation checks."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CapabilityClassificationTests(unittest.TestCase):
    def test_reviewed_estate_is_fully_classified_and_reconciled(self) -> None:
        catalog = json.loads((ROOT / "registry" / "capabilities.json").read_text(encoding="utf-8"))
        commands = {item["id"] for item in json.loads((ROOT / "registry" / "commands.json").read_text(encoding="utf-8"))["commands"]}
        reconciliation = json.loads((ROOT / "artifacts" / "audits" / "phase1-architecture" / "capability-reconciliation.json").read_text(encoding="utf-8"))
        capabilities = catalog["capabilities"]
        self.assertFalse(reconciliation["callable_skills"]["missing"])
        self.assertEqual(reconciliation["counts"]["callable_skills"], reconciliation["counts"]["manifests"])
        self.assertTrue(all(item["family"] != "unclassified" for item in capabilities))
        self.assertTrue(all(item["commands"] and set(item["commands"]).issubset(commands) for item in capabilities))
        aliases = {item["canonical_name"]: item for item in capabilities if item["lifecycle"] == "deprecated"}
        self.assertEqual(
            set(aliases),
            {
                "agent-operating-stack",
                "cdo-deslop",
                "cdo-rams",
                "cdo-react-doctor",
                "departments",
                "ideate",
                "mega-workflow",
                "taste-skill-suite-taste-skill",
            },
        )
        for name, item in aliases.items():
            self.assertEqual(item["role"], "alias")
            target = next(candidate for candidate in capabilities if candidate["canonical_name"] == item["alias_of"])
            self.assertIn(name, target["compatibility_aliases"])

    def test_classification_and_catalog_are_deterministic(self) -> None:
        commands = [
            [sys.executable, "scripts/classify-capabilities.py", "--check"],
            [sys.executable, "scripts/build-capability-registry.py", "--check"],
        ]
        for command in commands:
            completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)


if __name__ == "__main__":
    unittest.main()
