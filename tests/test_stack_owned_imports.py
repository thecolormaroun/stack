"""Contracts for the 2026-11-13 David/Matt import cleanup.

Eight David imports were retired. Ten David/Matt imports whose upstream copies
were removed or moved became Stack-owned and left the maintenance lane, and so
did the 12 remaining David imports once davidondrej/skills became pick-only.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

RETIRED = (
    "david-pi-web-search",
    "david-pi-custom-model",
    "david-push-skill-to-github",
    "david-distribute-skill-to-all-agents",
    "david-run-deep-swe",
    "david-level-up",
    "david-short",
    "david-teach",
)
CONVERTED = {
    "david-youtube-transcript": "skills/knowledge/david-youtube-transcript",
    "david-research-prompt": "skills/knowledge/david-research-prompt",
    "david-google-safe-browsing": "skills/review/david-google-safe-browsing",
    "david-cyber-audit": "skills/review/david-cyber-audit",
    "david-create-readonly-db-role": "skills/engineering/david-create-readonly-db-role",
    "david-prompt-me": "skills/engineering/david-prompt-me",
    "david-brain-to-docs": "skills/engineering/david-brain-to-docs",
    "david-agent-self-scheduling": "skills/orchestration/david-agent-self-scheduling",
    "david-folder-specific-claude-and-agents-md": "skills/platform/david-folder-specific-claude-and-agents-md",
    "matt-resolving-merge-conflicts": "skills/planning/matt-resolving-merge-conflicts",
    # davidondrej/skills became pick-only (docs/upstream-policy.md).
    "david-anti-sleep": "skills/engineering/david-anti-sleep",
    "david-deepapi": "skills/engineering/david-deepapi",
    "david-fable-safe-prompt": "skills/engineering/david-fable-safe-prompt",
    "david-read-all-adrs": "skills/engineering/david-read-all-adrs",
    "david-browser-harness": "skills/qa/david-browser-harness",
    "david-cmux": "skills/orchestration/david-cmux",
    "david-codex-subagent": "skills/orchestration/david-codex-subagent",
    "david-goal-loop": "skills/orchestration/david-goal-loop",
    "david-handoff": "skills/orchestration/david-handoff",
    "david-deep-research": "skills/knowledge/david-deep-research",
    "david-effective-agent-skills": "skills/platform/david-effective-agent-skills",
    "david-setup-help": "skills/platform/david-setup-help",
}


def read(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def catalog() -> dict[str, dict]:
    return {row["canonical_name"]: row for row in read("registry/capabilities.json")["capabilities"]}


class RetiredImportTests(unittest.TestCase):
    def test_retired_skills_are_gone_from_the_tree_catalog_and_records(self) -> None:
        names = catalog()
        moves = {move["canonical_name"] for move in read("registry/migrations/2026-07-23-skill-layout.json")["moves"]}
        retained = {
            Path(row["target"]).name
            for rule in read("registry/maintenance-imports.json")["providers"]
            for row in rule.get("retained_targets", [])
        }
        classifier = (ROOT / "scripts/classify-capabilities.py").read_text(encoding="utf-8")
        for name in RETIRED:
            with self.subTest(name=name):
                self.assertEqual(list((ROOT / "skills").glob(f"**/{name}")), [])
                self.assertNotIn(name, names)
                self.assertNotIn(name, moves)
                self.assertNotIn(name, retained)
                self.assertNotIn(f'"{name}"', classifier)


class StackOwnedImportTests(unittest.TestCase):
    def test_converted_skills_are_stack_owned_with_origin_and_license_kept(self) -> None:
        names = catalog()
        for name, path in CONVERTED.items():
            with self.subTest(name=name):
                row = names[name]
                self.assertEqual(row["source"]["skill_path"], f"{path}/SKILL.md")
                self.assertEqual(row["ownership"], {"package": "stack", "provider": "stack", "source_path": f"{path}/SKILL.md"})
                self.assertEqual(row["provenance"], {"license": "MIT", "posture": "repository-local", "source_identity": f"stack:skills/{name}"})
                self.assertEqual(row["lifecycle"], "active")
                self.assertTrue(row["purpose"].startswith("Stack-owned, adapted from "))
                skill = (ROOT / path / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn("## Stack-owned\n", skill)
                self.assertNotIn("Upstream name:", skill)
                self.assertNotIn("upstream workflow", skill)
                source = (ROOT / path / "references/source.md").read_text(encoding="utf-8")
                self.assertIn(f"- Stack-owned skill: `${name}`", source)
                self.assertRegex(source, r"- Last inspected commit: `[a-f0-9]{40}`")
                self.assertIn("MIT License", source)
                self.assertIn("Permission is hereby granted", source)

    def test_converted_skills_are_outside_the_maintenance_lane(self) -> None:
        imports = read("registry/maintenance-imports.json")["providers"]
        policy = read("config/stack-maintenance.json")
        sources = {row["id"]: row for row in read("registry/maintenance-sources.json")["sources"]}
        row = sources["stack-owned-imports"]
        self.assertEqual(row["disposition"], "repository-owned-capability")
        self.assertIsNone(row["provider_id"])
        self.assertEqual(row["target_paths"], sorted(CONVERTED.values()))
        self.assertIn("stack-owned-imports", policy["legacy_target_ids"])
        retained = {target["target"] for rule in imports for target in rule.get("retained_targets", [])}
        for name, path in CONVERTED.items():
            with self.subTest(name=name):
                self.assertFalse(path.startswith("skills/imported/"))
                self.assertFalse(any(path.startswith(rule["target_root"].rstrip("/") + "/") for rule in imports if rule["target_root"] != "."))
                self.assertFalse(any(path.startswith(entry) for entry in policy["diff_allowlist"] if entry.endswith("/")))
                self.assertNotIn(path, retained)
                self.assertFalse(any(target.get("target") == path for rule in imports for target in rule.get("targets", [])))


class ClassifierIdempotencyTests(unittest.TestCase):
    def test_classifier_rerun_leaves_every_manifest_and_the_reconciliation_unchanged(self) -> None:
        spec = importlib.util.spec_from_file_location("classify_rerun", ROOT / "scripts/classify-capabilities.py")
        assert spec and spec.loader
        classifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(classifier)
        inputs = ["config/runtime-targets.json", "registry/inventory-sources.json"]
        try:
            listed = subprocess.run(
                ["git", "-C", str(ROOT), "ls-files", "-z", "--", "skills", "packages"],
                check=True, capture_output=True,
            ).stdout.split(b"\0")
            files = [item.decode("utf-8") for item in listed if item] + inputs
        except (OSError, subprocess.CalledProcessError):
            files = [path.relative_to(ROOT).as_posix() for base in ("skills", "packages") for path in (ROOT / base).rglob("*") if path.is_file()] + inputs
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "stack"
            for relative in files:
                source = ROOT / relative
                if source.is_symlink() or not source.is_file():
                    continue
                destination = copy / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            before = {path.relative_to(copy).as_posix(): path.read_bytes() for path in (copy / "skills").rglob("capability.json")}
            reconciliation = classifier.classify(copy)
            after = {path.relative_to(copy).as_posix(): path.read_bytes() for path in (copy / "skills").rglob("capability.json")}
        self.assertEqual(sorted(after), sorted(before))
        changed = sorted(path for path in before if before[path] != after[path])
        self.assertEqual(changed, [])
        recorded = (ROOT / "artifacts/audits/phase1-architecture/capability-reconciliation.json").read_text(encoding="utf-8")
        self.assertEqual(json.loads(recorded)["callable_skills"], reconciliation["callable_skills"])


if __name__ == "__main__":
    unittest.main()
