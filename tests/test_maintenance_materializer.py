from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "materialize-maintenance-proposal.py"


def _module():
    spec = importlib.util.spec_from_file_location("maintenance_materializer", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MaintenanceMaterializerTests(unittest.TestCase):
    def test_import_is_deterministic_and_bound_to_existing_mapping(self) -> None:
        import tempfile

        materializer = _module()
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            stage = temporary_root / "stage"
            checkout = temporary_root / "checkout"
            target = stage / "skills/imported/matt/matt-tdd"
            source = checkout / "skills/engineering/tdd"
            (target / "references").mkdir(parents=True)
            source.mkdir(parents=True)
            (checkout / "LICENSE").write_text(
                "MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a copy\n",
                encoding="utf-8",
            )
            (source / "SKILL.md").write_text(
                "---\nname: tdd\ndescription: Test first.\n---\n\n# TDD\n\nUse a red-green loop.\n",
                encoding="utf-8",
            )
            old_pin = "a" * 40
            (target / "SKILL.md").write_text("old\n", encoding="utf-8")
            (target / "capability.json").write_text("{}\n", encoding="utf-8")
            (target / "references/source.md").write_text(
                "\n".join([
                    "# Source Metadata",
                    "",
                    "- Upstream path: `skills/engineering/tdd`",
                    f"- Inspected commit: `{old_pin}`",
                    "",
                ]),
                encoding="utf-8",
            )
            provider = {
                "id": "matt",
                "canonical_source": "https://github.com/mattpocock/skills.git",
                "pin": {"type": "git-commit", "value": old_pin},
            }
            rule = {
                "id": "matt",
                "display_name": "Matt Pocock",
                "target_root": "skills/imported/matt",
                "target_prefix": "matt-",
                "mapping": "existing-source-markdown",
                "source_metadata": "references/source.md",
                "license": "MIT",
            }
            commit = "b" * 40
            first = materializer.materialize_provider(stage, checkout, provider, rule, commit)
            second = materializer.materialize_provider(stage, checkout, provider, rule, commit)
            self.assertEqual(first, second)
            skill = first["skills/imported/matt/matt-tdd/SKILL.md"].decode()
            self.assertIn("name: matt-tdd", skill)
            self.assertIn(commit, skill)
            self.assertIn("Use a red-green loop.", skill)

    def test_import_refuses_unmapped_deletion(self) -> None:
        import tempfile

        materializer = _module()
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            stage = temporary_root / "stage"
            checkout = temporary_root / "checkout"
            target = stage / "skills/imported/david/david-handoff"
            source = checkout / "skills/agent-orchestration/handoff"
            (target / "references").mkdir(parents=True)
            source.mkdir(parents=True)
            (checkout / "LICENSE").write_text(
                "MIT License\nPermission is hereby granted, free of charge\n",
                encoding="utf-8",
            )
            (source / "SKILL.md").write_text(
                "---\nname: handoff\ndescription: Handoff.\n---\n\n# Handoff\n",
                encoding="utf-8",
            )
            old_pin = "a" * 40
            (target / "SKILL.md").write_text("old\n", encoding="utf-8")
            (target / "capability.json").write_text("{}\n", encoding="utf-8")
            (target / "obsolete.md").write_text("old upstream file\n", encoding="utf-8")
            (target / "references/source.md").write_text(
                f"- Upstream path: `skills/agent-orchestration/handoff`\n- Inspected commit: `{old_pin}`\n",
                encoding="utf-8",
            )
            provider = {
                "id": "david",
                "canonical_source": "https://github.com/davidondrej/skills.git",
                "pin": {"type": "git-commit", "value": old_pin},
            }
            rule = {
                "id": "david",
                "display_name": "David Ondrej",
                "target_root": "skills/imported/david",
                "target_prefix": "david-",
                "mapping": "existing-source-markdown",
                "source_metadata": "references/source.md",
                "license": "MIT",
            }
            with self.assertRaisesRegex(materializer.ProposalError, "upstream_deletion_requires_approval"):
                materializer.materialize_provider(stage, checkout, provider, rule, "b" * 40)


if __name__ == "__main__":
    unittest.main()
