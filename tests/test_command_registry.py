from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CommandRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.commands = json.loads((ROOT / "registry/commands.json").read_text())["commands"]
        self.rules = json.loads((ROOT / "registry/routing-rules.json").read_text())

    def test_exact_canonical_command_tree_and_runtime_parity(self) -> None:
        expected = ["stack", "stack.explore", "stack.plan", "stack.design", "stack.build", "stack.orchestrate", "stack.review", "stack.qa", "stack.ship", "stack.learn", "stack.maintain", "stack.run"]
        primary = [command for command in self.commands if command["visibility"] == "primary"]
        self.assertEqual([command["id"] for command in primary], expected)
        self.assertEqual(len(primary), 12)
        intelligence = next(command for command in self.commands if command["id"] == "stack.design.intelligence")
        self.assertEqual(intelligence["visibility"], "extended")
        self.assertEqual(intelligence["subcommands"], ["collect", "digest", "retrieve", "critique", "propose"])
        for command in self.commands:
            self.assertTrue(command["runtimes"]["claude"])
            self.assertTrue(command["runtimes"]["codex"])
            self.assertEqual(set(command["effect_vector"]), {"source_read", "owner_local_write", "project_write", "external_write", "costly_use", "irreversible_action"})

    def test_aliases_are_unique_and_package_native_aliases_warn(self) -> None:
        aliases = [alias for command in self.commands for alias in command["aliases"]]
        names = [alias["name"] for alias in aliases]
        self.assertEqual(len(names), len(set(names)))
        for alias in aliases:
            if alias["kind"] == "package-native":
                self.assertTrue(alias["canonical_warning"])

    def test_routing_is_deterministic_and_ambiguous_requests_ask(self) -> None:
        self.assertEqual(self.rules["precedence"], ["canonical-id", "alias", "intent", "context"])
        self.assertEqual(self.rules["ambiguity_policy"], "ask-with-candidates")
        self.assertEqual(self.rules["package_health_policy"], "last-known-good")
        self.assertIn("code-or-architecture-artifact", next(rule for rule in self.rules["rules"] if rule["command"] == "stack.review")["requires_context"])

    def test_every_command_owner_resolves(self) -> None:
        capabilities = {
            capability["canonical_name"]
            for capability in json.loads((ROOT / "registry/capabilities.json").read_text())["capabilities"]
        }
        providers = {
            json.loads(path.read_text())["provider"]
            for path in (ROOT / "packages").glob("*/package.json")
        }
        for command in self.commands:
            with self.subTest(command=command["id"]):
                owner = command["owner"]
                if owner["kind"] == "stack":
                    self.assertIn(owner["id"], capabilities)
                elif owner["kind"] == "package":
                    self.assertIn(owner["id"], providers)
                else:
                    self.fail(f"unsupported owner kind: {owner['kind']}")


if __name__ == "__main__":
    unittest.main()
