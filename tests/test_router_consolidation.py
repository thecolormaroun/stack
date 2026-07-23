"""Focused contracts for the Stack command router and legacy adapters."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = {
    "core/compatibility/agent-operating-stack": "stack",
    "core/compatibility/mega-workflow": "stack.run full",
    "core/compatibility/departments": "stack.run plan",
    "product/compatibility/ideate": "stack.explore ideate",
}


class RouterConsolidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.commands = json.loads((ROOT / "registry/commands.json").read_text())["commands"]

    def test_command_tree_is_an_exact_registry_mirror(self) -> None:
        rows = re.findall(r"^\| `([^`]+)` \| `([^`]+)` \| `([^`]+)` \|$", (ROOT / "docs/command-tree.md").read_text(), re.M)
        self.assertEqual(rows, [(command["id"], command["owner"]["id"], command["trust_class"]) for command in self.commands])

    def test_legacy_routers_are_thin_compatibility_surfaces(self) -> None:
        for name, target in ADAPTERS.items():
            with self.subTest(name=name):
                text = (ROOT / "skills" / name / "SKILL.md").read_text().lower()
                self.assertIn("compatibility adapter", text)
                self.assertIn("deprecated", text)
                self.assertIn(f"canonical target: `{target}`", text)
                self.assertLess(len(text), 900)

    def test_legacy_routers_resolve_to_existing_canonical_surfaces(self) -> None:
        self.assertTrue((ROOT / "skills/core/stack/SKILL.md").is_file())
        self.assertTrue((ROOT / "skills/core/run/SKILL.md").is_file())
        self.assertEqual(ADAPTERS["core/compatibility/agent-operating-stack"], "stack")
        for name in ("core/compatibility/mega-workflow", "core/compatibility/departments"):
            self.assertTrue(ADAPTERS[name].startswith("stack.run"))
        self.assertTrue(ADAPTERS["product/compatibility/ideate"].startswith("stack.explore"))

    def test_mega_has_no_stale_duplicated_command_inventory(self) -> None:
        text = (ROOT / "skills/core/compatibility/mega-workflow/SKILL.md").read_text().lower()
        for stale_inventory_marker in ("all available commands", "/office-hours", "/autoplan", "/lfg", "/cso"):
            with self.subTest(marker=stale_inventory_marker):
                self.assertNotIn(stale_inventory_marker, text)

    def test_root_router_names_approval_and_ambiguous_review_policy(self) -> None:
        text = (ROOT / "skills/core/stack/SKILL.md").read_text().lower()
        self.assertIn("explicit approval", text)
        self.assertIn("ask", text)
        self.assertIn("code, architecture, security, data, or simplicity", text)

    def test_canonical_owners_and_legacy_aliases_are_explicit(self) -> None:
        commands = {command["id"]: command for command in self.commands}
        self.assertEqual(commands["stack"]["owner"], {"kind": "stack", "id": "core-stack"})
        self.assertEqual(commands["stack.run"]["owner"], {"kind": "stack", "id": "core-run"})
        self.assertEqual(commands["stack.explore"]["owner"], {"kind": "stack", "id": "cpo"})
        aliases = {
            alias["name"]: (command["id"], alias["canonical_warning"])
            for command in self.commands
            for alias in command["aliases"]
        }
        for legacy, target in {
            "agent-operating-stack": "stack",
            "mega-workflow": "stack.run",
            "departments": "stack.run",
            "ideate": "stack.explore",
        }.items():
            self.assertEqual(aliases[legacy], (target, True))

    def test_router_manifest_roles_survive_classifier_regeneration(self) -> None:
        expected = {
            "core/stack": ("core-stack", "router", "primary", "active", None),
            "core/run": ("core-run", "workflow", "primary", "active", None),
            "core/compatibility/agent-operating-stack": ("agent-operating-stack", "alias", "compatibility", "deprecated", "core-stack"),
            "core/compatibility/mega-workflow": ("mega-workflow", "alias", "compatibility", "deprecated", "core-run"),
            "core/compatibility/departments": ("departments", "alias", "compatibility", "deprecated", "core-run"),
            "product/compatibility/ideate": ("ideate", "alias", "compatibility", "deprecated", "cpo"),
        }
        for path, values in expected.items():
            with self.subTest(path=path):
                manifest = json.loads((ROOT / "skills" / path / "capability.json").read_text())
                actual = (
                    manifest["canonical_name"],
                    manifest["role"],
                    manifest["visibility"],
                    manifest["lifecycle"],
                    manifest.get("alias_of"),
                )
                self.assertEqual(actual, values)


if __name__ == "__main__":
    unittest.main()
