"""End-to-end discovery contract for registry-derived runtime adapters."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COMPILER = load("command_adapter_compiler", "compile-runtime.py")
INSTALLER = load("command_adapter_installer", "install-runtime.py")
DOCTOR = load("command_adapter_doctor", "stack-doctor.py")


class RuntimeCommandAdapterTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path, Path]:
        skill = root / "skills/local-leaf"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# Local leaf\n", encoding="utf-8")
        registry = root / "registry"
        registry.mkdir()
        catalog = registry / "capabilities.json"
        catalog.write_text(json.dumps({
            "schema_version": 1,
            "capabilities": [{
                "canonical_name": "local-leaf",
                "lifecycle": "active",
                "artifact_type": "skill",
                "source": {"skill_path": "skills/local-leaf/SKILL.md"},
                "runtimes": {
                    "supported": ["claude", "codex"],
                    "publish_targets": ["claude", "codex"],
                },
            }],
        }), encoding="utf-8")
        shutil.copy2(ROOT / "registry/commands.json", registry / "commands.json")
        upstreams = json.loads((ROOT / "registry/upstreams.json").read_text())
        stack_codex = next(item for item in upstreams["providers"] if item["id"] == "stack-codex")
        package_cache = root / "package-cache"
        package_cache.mkdir()
        external_providers = []
        provider_exports = {
            "compound-engineering": ["ce-plan", "ce-brainstorm", "ce-work", "lfg", "ce-worktree", "ce-code-review", "ce-commit"],
            "gstack": ["office-hours", "qa", "canary", "land-and-deploy", "retro"],
        }
        for provider_id, exports in provider_exports.items():
            origin = root / "origins" / provider_id
            origin.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(origin)], check=True)
            subprocess.run(["git", "-C", str(origin), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(origin), "config", "user.name", "Test"], check=True)
            export_paths = {}
            for export in exports:
                relative = f"skills/{export}/SKILL.md" if provider_id == "compound-engineering" else f"{export}/SKILL.md"
                skill_path = origin / relative
                skill_path.parent.mkdir(parents=True)
                skill_path.write_text(f"# {export}\n", encoding="utf-8")
                export_paths[export] = relative
            subprocess.run(["git", "-C", str(origin), "add", "."], check=True)
            subprocess.run(["git", "-C", str(origin), "commit", "-qm", "fixture exports"], check=True)
            pin = subprocess.check_output(["git", "-C", str(origin), "rev-parse", "HEAD"], text=True).strip()
            subprocess.run(["git", "clone", "-q", str(origin), str(package_cache / provider_id)], check=True)
            external_providers.append({
                "id": provider_id,
                "canonical_source": str(origin),
                "pin": {"value": pin},
                "exports": exports,
                "export_paths": export_paths,
                "install": "pinned-git-checkout",
            })
        (registry / "upstreams.json").write_text(json.dumps({"providers": [stack_codex, *external_providers]}), encoding="utf-8")
        shutil.copytree(ROOT / "packages/stack-codex/content", root / "packages/stack-codex/content")
        targets = root / "config/runtime-targets.json"
        targets.parent.mkdir()
        verifier = [
            "python3",
            "-c",
            "import json; from pathlib import Path; m=json.loads(Path('runtime-manifest.json').read_text()); assert len(m['command_adapters']) == 12; assert all(Path(x['path']).is_file() for x in m['command_adapters']); assert all((Path('skills') / x['alias'] / 'SKILL.md').is_file() for x in m['command_aliases'])",
        ]
        targets.write_text(json.dumps({
            "schema_version": 1,
            "catalog_digest": COMPILER.digest_file(catalog),
            "targets": [
                {"name": "claude", "runtime": "claude", "destination": ".claude/skills/stack", "post_switch_verifier": verifier},
                {"name": "codex", "runtime": "codex", "destination": ".codex/skills/stack", "post_switch_verifier": verifier},
            ],
        }), encoding="utf-8")
        return catalog, targets, package_cache

    def test_two_target_install_discovers_all_primary_routes_and_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "checkout"
            root.mkdir()
            catalog, targets, package_cache = self.fixture(root)
            stages = COMPILER.compile_runtimes(
                root,
                catalog,
                targets,
                root / "staging",
                source_commit="fixture",
                package_cache=package_cache,
            )
            deployment = Path(temporary) / "deployment"
            receipts = Path(temporary) / "receipts"
            receipt = INSTALLER.install_runtimes(deployment, targets, stages, receipts)

            self.assertEqual(receipt["status"], "published")
            commands = json.loads((root / "registry/commands.json").read_text())["commands"]
            for runtime in ("claude", "codex"):
                installed = deployment / f".{runtime}/skills/stack"
                self.assertTrue(installed.is_symlink())
                manifest = json.loads((installed / "runtime-manifest.json").read_text())
                self.assertEqual(len(manifest["command_adapters"]), 12)
                self.assertEqual(len(manifest["external_package_exports"]), 12)
                expected = {
                    command["runtimes"][runtime].removeprefix("/").replace(" ", "-")
                    for command in commands
                }
                self.assertTrue(all((installed / "skills" / name / "SKILL.md").is_file() for name in expected))
                aliases = {
                    alias["name"].removeprefix("/").replace(" ", "-")
                    for command in commands for alias in command["aliases"]
                }
                self.assertTrue(all((installed / "skills" / name / "SKILL.md").is_file() for name in aliases))
                self.assertEqual(manifest["shadowed_bundle_exports"], [
                    {"canonical_command": "stack.review", "shadowed_bundle_export": "stack-review"},
                    {"canonical_command": "stack.ship", "shadowed_bundle_export": "stack-ship"},
                ])
                review = (installed / "skills/stack-review/SKILL.md").read_text()
                ship = (installed / "skills/stack-ship/SKILL.md").read_text()
                self.assertIn("Canonical command: `stack.review`", review)
                self.assertIn("`compound-engineering:ce-code-review`", review)
                self.assertIn("Trust class: `read-only`", review)
                self.assertIn("Canonical command: `stack.ship`", ship)
                self.assertIn("`gstack:land-and-deploy`", ship)
                self.assertIn("Require explicit user approval", ship)
            health = DOCTOR.runtime_health(root, deployment)
            self.assertFalse(any("command adapter" in error or "command alias" in error for error in health), health)
            (deployment / ".codex/skills/stack/skills/stack-plan/SKILL.md").unlink()
            health = DOCTOR.runtime_health(root, deployment)
            self.assertTrue(any("unresolvable primary command adapter" in error for error in health), health)

    def test_undeclared_stack_codex_name_collision_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog, targets, package_cache = self.fixture(root)
            bundle_skill = root / "packages/stack-codex/content/skills/stack-plan"
            bundle_skill.mkdir()
            (bundle_skill / "SKILL.md").write_text("# Conflicting plan\n", encoding="utf-8")
            upstreams_path = root / "registry/upstreams.json"
            upstreams = json.loads(upstreams_path.read_text())
            provider = next(item for item in upstreams["providers"] if item["id"] == "stack-codex")
            provider["exports"].append("stack-plan")
            upstreams_path.write_text(json.dumps(upstreams), encoding="utf-8")

            with self.assertRaisesRegex(COMPILER.RuntimeError, "collides with staged skill: stack-plan"):
                COMPILER.compile_runtimes(root, catalog, targets, root / "staging", source_commit="fixture", package_cache=package_cache)


if __name__ == "__main__":
    unittest.main()
