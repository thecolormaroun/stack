"""Focused U3 layout migration contracts."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("apply_skill_layout", ROOT / "scripts/apply-skill-layout.py")
assert SPEC and SPEC.loader
LAYOUT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAYOUT)


class SkillLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.migration = json.loads((ROOT / "registry/migrations/2026-07-23-skill-layout.json").read_text())

    def test_every_manifested_capability_has_one_explicit_move(self) -> None:
        manifests = list((ROOT / "skills").glob("**/capability.json"))
        moves = self.migration["moves"]
        self.assertEqual(len(moves), len(manifests))
        self.assertEqual(len({move["canonical_name"] for move in moves}), len(moves))
        self.assertEqual(len({move["source"] for move in moves}), len(moves))
        self.assertEqual(len({move["destination"] for move in moves}), len(moves))

    def test_layout_uses_only_family_or_provider_roots(self) -> None:
        approved = {"core", "product", "planning", "design", "engineering", "orchestration", "review", "qa", "delivery", "knowledge", "platform", "imported"}
        for move in self.migration["moves"]:
            with self.subTest(move=move["canonical_name"]):
                self.assertIn(Path(move["destination"]).parts[1], approved)

    def test_manifest_paths_and_alias_targets_are_preserved(self) -> None:
        expected_paths = {move["canonical_name"]: move["destination"] for move in self.migration["moves"]}
        manifests = {}
        for path in (ROOT / "skills").glob("**/capability.json"):
            manifest = json.loads(path.read_text())
            manifests[manifest["canonical_name"]] = manifest
            self.assertEqual(manifest["source"]["skill_path"], expected_paths[manifest["canonical_name"]])
            self.assertEqual(manifest["ownership"]["source_path"], expected_paths[manifest["canonical_name"]])
        self.assertEqual(
            {name: manifests[name]["alias_of"] for name in ("cdo-deslop", "cdo-rams", "cdo-react-doctor", "taste-skill-suite-taste-skill")},
            {"cdo-deslop": "deslop", "cdo-rams": "rams", "cdo-react-doctor": "react-doctor", "taste-skill-suite-taste-skill": "cdo-taste-skill"},
        )

    def test_second_dry_run_is_a_noop(self) -> None:
        command = ["python3", "scripts/apply-skill-layout.py", "--dry-run"]
        first = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        second = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        self.assertIn('"pending_root_moves": 0', first.stdout)

    def test_preflight_rejects_destination_collision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "skills/old").mkdir(parents=True)
            (root / "skills/old/SKILL.md").write_text("# old\n")
            (root / "skills/old/capability.json").write_text(json.dumps({"canonical_name": "old", "source": {"skill_path": "skills/old/SKILL.md"}, "ownership": {"source_path": "skills/old/SKILL.md"}}))
            (root / "skills/new").mkdir(parents=True)
            (root / "skills/new/SKILL.md").write_text("# collision\n")
            migration = {"moves": [{"canonical_name": "old", "source": "skills/old/SKILL.md", "destination": "skills/new/SKILL.md"}]}
            with self.assertRaisesRegex(LAYOUT.LayoutError, "destination collision"):
                LAYOUT.preflight(root, migration)


if __name__ == "__main__":
    unittest.main()
