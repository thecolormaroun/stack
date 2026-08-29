"""Executable U14 routing and protected-baseline contracts."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("resolve_command", ROOT / "scripts" / "resolve-command.py")
assert SPEC and SPEC.loader
RESOLVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESOLVER)


class IntentRoutingTests(unittest.TestCase):
    def resolver(self, root: Path = ROOT):
        return RESOLVER.CommandResolver.from_paths(
            root / "registry/commands.json",
            root / "registry/routing-rules.json",
        )

    def test_canonical_and_alias_requests_share_the_route_contract(self) -> None:
        resolver = self.resolver()
        canonical = resolver.resolve("stack.plan technical")
        alias = resolver.resolve("ce-plan")

        self.assertEqual(canonical["status"], "resolved")
        self.assertEqual(canonical["logical_command"], "stack.plan")
        self.assertEqual(canonical["subcommand"], "technical")
        self.assertEqual(canonical["match_reason"], "canonical-id")
        self.assertEqual(alias["logical_command"], canonical["logical_command"])
        self.assertEqual(alias["subcommand"], canonical["subcommand"])
        self.assertEqual(alias["trust_class"], canonical["trust_class"])
        self.assertEqual(alias["effect_vector"], canonical["effect_vector"])
        self.assertEqual(alias["match_reason"], "alias")
        self.assertTrue(alias["canonical_warning"])

    def test_intent_and_context_routes_are_executable(self) -> None:
        resolver = self.resolver()
        result = resolver.resolve("Please help me plan this feature")

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["logical_command"], "stack.plan")
        self.assertEqual(result["match_reason"], "intent")
        self.assertIn("requirements", result["evidence_context"]["required"])

        code_review = resolver.resolve("review this", {"artifacts": ["code"]})
        self.assertEqual(code_review["logical_command"], "stack.review")
        self.assertEqual(code_review["match_reason"], "context")

    def test_design_and_code_review_context_is_explicitly_ambiguous(self) -> None:
        result = self.resolver().resolve(
            "review this",
            {"artifacts": ["code", "screenshot"], "route": "/composer"},
        )

        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["match_reason"], "ambiguous")
        self.assertEqual(result["candidates"], ["stack.design", "stack.review"])
        self.assertIsNone(result["logical_command"])

    def test_task_context_retrieval_selects_extended_intelligence_route(self) -> None:
        result = self.resolver().resolve(
            "Show me relevant inspiration for this screen",
            {
                "project": "demo",
                "route": "/composer",
                "component": "media-composer",
                "viewport": "390x844",
                "brief": "dense mobile media composer",
                "screenshot": "sha256:fixture",
            },
        )

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["logical_command"], "stack.design.intelligence")
        self.assertEqual(result["subcommand"], "retrieve")
        self.assertEqual(result["match_reason"], "intent")
        self.assertEqual(result["approval_state"], "not_required")
        self.assertEqual(result["evidence_context"]["missing"], [])
        self.assertIn("screenshot", result["evidence_context"]["provided"])

    def test_unknown_and_metadata_incomplete_routes_fail_closed(self) -> None:
        unknown = self.resolver().resolve("please make up a completely unknown operation")
        self.assertEqual(unknown["status"], "unknown")
        self.assertEqual(unknown["match_reason"], "unknown")
        self.assertIsNone(unknown["logical_command"])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = json.loads((ROOT / "registry/commands.json").read_text())
            plan = next(item for item in commands["commands"] if item["id"] == "stack.plan")
            plan.pop("effect_vector")
            (root / "commands.json").write_text(json.dumps(commands), encoding="utf-8")
            (root / "routing.json").write_text(
                (ROOT / "registry/routing-rules.json").read_text(), encoding="utf-8"
            )
            incomplete = RESOLVER.CommandResolver.from_paths(root / "commands.json", root / "routing.json")
            result = incomplete.resolve("stack.plan technical")

        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["match_reason"], "metadata-incomplete")
        self.assertEqual(result["logical_command"], "stack.plan")
        self.assertEqual(result["approval_state"], "denied")

    def test_claude_and_codex_characterize_one_resolver_contract(self) -> None:
        resolver = self.resolver()
        claude = resolver.characterize("show me relevant inspiration for this screen", "claude", {
            "route": "/composer",
            "component": "media-composer",
            "viewport": "390x844",
            "brief": "mobile composer",
        })
        codex = resolver.characterize("show me relevant inspiration for this screen", "codex", {
            "route": "/composer",
            "component": "media-composer",
            "viewport": "390x844",
            "brief": "mobile composer",
        })

        self.assertEqual(claude["resolution"], codex["resolution"])
        self.assertEqual(claude["contract"], codex["contract"])
        self.assertEqual(claude["runtime"], "claude")
        self.assertEqual(codex["runtime"], "codex")

    def test_resolver_is_read_only(self) -> None:
        tracked = [
            ROOT / "registry/commands.json",
            ROOT / "registry/routing-rules.json",
        ]
        before = {path: path.read_bytes() for path in tracked}
        self.resolver().resolve("stack.design ui")
        after = {path: path.read_bytes() for path in tracked}
        self.assertEqual(before, after)

    def test_catalog_ignores_untracked_callable_collision(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "build_capability_registry_for_routing",
            ROOT / "scripts/build-capability-registry.py",
        )
        assert spec and spec.loader
        registry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(registry)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            tracked = root / "skills/tracked"
            tracked.mkdir(parents=True)
            (tracked / "SKILL.md").write_text("# tracked\n", encoding="utf-8")
            manifest = {
                "schema_version": 1,
                "canonical_name": "tracked",
                "purpose": "A tracked test capability.",
                "domain": "engineering",
                "family": "engineering",
                "role": "leaf",
                "visibility": "extended",
                "commands": ["stack.build"],
                "ownership": {"provider": "stack", "package": "stack", "source_path": "skills/tracked/SKILL.md"},
                "context": {"inputs": ["request"], "outputs": ["result"]},
                "trust_class": "read-only",
                "validation_class": "structural",
                "artifact_type": "skill",
                "lifecycle": "active",
                "audit_status": "reviewed",
                "source": {"skill_path": "skills/tracked/SKILL.md"},
                "provenance": {"posture": "repository-local", "source_identity": "stack:tracked", "license": "repository-owned"},
                "overlaps": [],
                "compatibility_aliases": [],
                "validation": {"status": "validated", "evidence": ["test"]},
                "runtimes": {"supported": ["codex"], "publish_targets": ["codex"]},
                "disposition": {"status": "keep", "evidence_gap": None, "next_review_trigger": None},
            }
            (tracked / "capability.json").write_text(json.dumps(manifest), encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "skills/tracked"], check=True)
            untracked = root / "skills/tracked-collision"
            untracked.mkdir(parents=True)
            (untracked / "SKILL.md").write_bytes(b"USER OWNED\n")

            catalog = registry.build_catalog(root)

            self.assertEqual(catalog["summary"]["callable_entrypoint_count"], 1)
            self.assertEqual([item["canonical_name"] for item in catalog["capabilities"]], ["tracked"])
            self.assertEqual((untracked / "SKILL.md").read_bytes(), b"USER OWNED\n")

    def test_doctor_dry_run_is_a_read_only_report_alias(self) -> None:
        before = subprocess.check_output(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=ROOT, text=True
        )
        result = subprocess.run(
            ["python3", "scripts/stack-doctor.py", "--dry-run"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        after = subprocess.check_output(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=ROOT, text=True
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, after)
        report = json.loads(result.stdout)
        self.assertEqual(report["mode"], "dry-run")
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["source"]["commit"], subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip())


if __name__ == "__main__":
    unittest.main()
