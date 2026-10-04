from __future__ import annotations

import hashlib
import importlib.util
import json
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
    def test_catalog_required_imports_resolve_through_curated_provenance(self) -> None:
        materializer = _module()
        registry = json.loads((ROOT / "registry/upstreams.json").read_text())
        rules = json.loads((ROOT / "registry/maintenance-imports.json").read_text())
        inventory = json.loads((ROOT / "registry/maintenance-sources.json").read_text())
        providers = {row["id"]: row for row in registry["providers"]}
        required_by_provider: dict[str, set[str]] = {}
        for source in inventory["sources"]:
            if source["disposition"] == "catalog-managed-provider":
                required_by_provider.setdefault(source["provider_id"], set()).update(
                    source["required_exports"]
                )

        for rule in rules["providers"]:
            with self.subTest(provider=rule["id"]):
                provider = providers[rule["id"]]
                self.assertEqual(provider["install"], "pinned-import")
                retained = {
                    (Path(row["source"]), Path(row["target"])): row["pin"]
                    for row in rule["retained_targets"]
                }
                targets = materializer.discover_targets(
                    ROOT, rule, provider["pin"]["value"], retained
                )
                target_names = [target.name for _source, target, _pin in targets]
                self.assertEqual(len(target_names), len(set(target_names)))
                self.assertTrue(set(provider["exports"]).issubset(target_names))
                self.assertTrue(
                    required_by_provider[rule["id"]].issubset(target_names)
                )
                for source, target, inspected_pin in targets:
                    self.assertTrue((ROOT / target / "SKILL.md").is_file())
                    self.assertTrue((ROOT / target / "capability.json").is_file())
                    self.assertEqual(
                        inspected_pin,
                        retained.get((source, target), provider["pin"]["value"]),
                    )

    def test_ordinary_mapping_does_not_require_a_retained_target_entry(self) -> None:
        import tempfile

        materializer = _module()
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            target = stage / "skills/imported/david/david-handoff"
            (target / "references").mkdir(parents=True)
            pin = "a" * 40
            (target / "references/source.md").write_text(
                "- Upstream path: `skills/agent-orchestration/handoff`\n"
                f"- Inspected commit: `{pin}`\n",
                encoding="utf-8",
            )
            rule = {
                "mapping": "existing-source-markdown",
                "target_root": "skills/imported/david",
                "target_prefix": "david-",
                "source_metadata": "references/source.md",
            }

            self.assertEqual(
                materializer.discover_targets(stage, rule, pin, {}),
                [
                    (
                        Path("skills/agent-orchestration/handoff"),
                        Path("skills/imported/david/david-handoff"),
                        pin,
                    )
                ],
            )

    def test_mapping_rejects_missing_or_wrong_pin_and_unsafe_provenance(self) -> None:
        import tempfile

        materializer = _module()
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            target = stage / "skills/imported/david/david-handoff"
            (target / "references").mkdir(parents=True)
            pin = "a" * 40
            rule = {
                "mapping": "existing-source-markdown",
                "target_root": "skills/imported/david",
                "target_prefix": "david-",
                "source_metadata": "references/source.md",
            }
            cases = {
                "missing_source": (f"- Inspected commit: `{pin}`\n", "import_metadata_invalid"),
                "missing_pin": (
                    "- Upstream path: `skills/agent-orchestration/handoff`\n",
                    "import_metadata_invalid",
                ),
                "wrong_pin": (
                    "- Upstream path: `skills/agent-orchestration/handoff`\n"
                    f"- Inspected commit: `{'b' * 40}`\n",
                    "import_metadata_invalid",
                ),
                "unsafe_source": (
                    f"- Upstream path: `../outside`\n- Inspected commit: `{pin}`\n",
                    "import_path_invalid",
                ),
            }
            for name, (metadata, reason) in cases.items():
                with self.subTest(case=name):
                    (target / "references/source.md").write_text(metadata, encoding="utf-8")
                    with self.assertRaisesRegex(materializer.ProposalError, reason):
                        materializer.discover_targets(stage, rule, pin, {})

    def test_import_normalizes_whitespace_only_lines_without_changing_markdown_breaks(self) -> None:
        import tempfile

        materializer = _module()
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "SKILL.md"
            source.write_text(
                "---\n"
                "name: tdd\n"
                "description: Test first.\n"
                "---\n"
                "   \n"
                "# TDD\n"
                "   \n"
                "\u00a0\n"
                "Keep this Markdown hard break.  \n"
                "Next line.\n",
                encoding="utf-8",
            )

            imported = materializer.materialized_skill(
                source,
                target_name="matt-tdd",
                display_name="Matt Pocock",
                commit="b" * 40,
                metadata_path="references/source.md",
            ).decode("utf-8")

            self.assertNotIn("\n   \n", imported)
            self.assertIn("\n\u00a0\n", imported)
            self.assertIn("Keep this Markdown hard break.  \nNext line.", imported)

    def test_explicit_mapping_preserves_existing_path_and_pin_identity(self) -> None:
        import copy
        import tempfile

        materializer = _module()
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary) / "stage"
            checkout = Path(temporary) / "checkout"
            target = stage / "skills/imported/emil/emil-design-eng"
            source = checkout / "skills/emil-design-eng"
            (target / "references").mkdir(parents=True)
            source.mkdir(parents=True)
            (target / "SKILL.md").write_text("old\n", encoding="utf-8")
            (target / "capability.json").write_text("{}\n", encoding="utf-8")
            license_bytes = b"MIT License\nPermission is hereby granted, free of charge\n"
            (checkout / "LICENSE").write_bytes(license_bytes)
            (source / "SKILL.md").write_text(
                "---\nname: emil-design-eng\ndescription: Design engineering.\n---\n\n# Design\n",
                encoding="utf-8",
            )
            old_pin, new_pin = "a" * 40, "b" * 40
            provider = {
                "id": "emil",
                "canonical_source": "https://github.com/example/design-skill.git",
                "pin": {"type": "git-commit", "value": old_pin},
                "license_sha256": hashlib.sha256(license_bytes).hexdigest(),
            }
            rule = {
                "id": "emil",
                "display_name": "Example Designer",
                "mapping": "explicit-source-json",
                "source_metadata": "references/source.json",
                "license": "MIT",
                "targets": [{
                    "source": "skills/emil-design-eng",
                    "target": "skills/imported/emil/emil-design-eng",
                }],
            }
            metadata_path = target / "references/source.json"
            valid_metadata = {
                "upstream_skill_path": "skills/emil-design-eng",
                "latest_commit": {"sha": old_pin},
            }
            metadata_path.write_text(json.dumps(valid_metadata), encoding="utf-8")
            before = {path: path.read_bytes() for path in target.rglob("*") if path.is_file()}
            outputs = materializer.materialize_provider(stage, checkout, provider, rule, new_pin)
            generated = json.loads(outputs["skills/imported/emil/emil-design-eng/references/source.json"])
            self.assertEqual(generated["upstream_skill_path"], "skills/emil-design-eng")
            self.assertEqual(generated["latest_commit"]["sha"], new_pin)
            self.assertEqual(before, {path: path.read_bytes() for path in before})

            wrong_path = copy.deepcopy(valid_metadata)
            wrong_path["upstream_skill_path"] = "skills/other"
            wrong_pin = copy.deepcopy(valid_metadata)
            wrong_pin["latest_commit"]["sha"] = "c" * 40
            for case, metadata in (
                ("missing", None),
                ("wrong_path", wrong_path),
                ("wrong_pin", wrong_pin),
                ("missing_commit", {"upstream_skill_path": "skills/emil-design-eng"}),
                ("malformed_commit", {"upstream_skill_path": "skills/emil-design-eng", "latest_commit": []}),
            ):
                with self.subTest(case=case):
                    if metadata is None:
                        metadata_path.unlink()
                    else:
                        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
                    existing = {path: path.read_bytes() for path in target.rglob("*") if path.is_file()}
                    with self.assertRaisesRegex(materializer.ProposalError, "import_metadata_invalid"):
                        materializer.materialize_provider(stage, checkout, provider, rule, new_pin)
                    self.assertEqual(existing, {path: path.read_bytes() for path in existing})

            outside = Path(temporary) / "outside"
            outside.mkdir()
            (outside / "source.json").write_text(json.dumps(valid_metadata), encoding="utf-8")
            metadata_path.unlink()
            metadata_path.symlink_to(outside / "source.json")
            with self.assertRaisesRegex(materializer.ProposalError, "mapped_skill_invalid"):
                materializer.materialize_provider(stage, checkout, provider, rule, new_pin)
            metadata_path.unlink()
            (target / "references").rename(target / "saved-references")
            (target / "references").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(materializer.ProposalError, "mapped_skill_invalid"):
                materializer.materialize_provider(stage, checkout, provider, rule, new_pin)
            self.assertEqual(
                (outside / "source.json").read_text(encoding="utf-8"),
                json.dumps(valid_metadata),
            )

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
                "license_sha256": hashlib.sha256((checkout / "LICENSE").read_bytes()).hexdigest(),
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
                "license_sha256": hashlib.sha256((checkout / "LICENSE").read_bytes()).hexdigest(),
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

    def test_retained_target_uses_its_own_pin_after_provider_advances(self) -> None:
        import tempfile

        materializer = _module()
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            stage = temporary_root / "stage"
            checkout = temporary_root / "checkout"
            target = stage / "skills/imported/matt/matt-writing-great-skills"
            (target / "references").mkdir(parents=True)
            checkout.mkdir()
            (checkout / "LICENSE").write_text(
                "MIT License\nPermission is hereby granted, free of charge\n",
                encoding="utf-8",
            )
            retained_pin = "a" * 40
            (target / "SKILL.md").write_text("retained\n", encoding="utf-8")
            (target / "references/source.md").write_text(
                "\n".join([
                    "- Upstream path: `skills/productivity/writing-great-skills`",
                    f"- Inspected commit: `{retained_pin}`",
                ]),
                encoding="utf-8",
            )
            provider = {
                "id": "matt",
                "canonical_source": "https://github.com/mattpocock/skills.git",
                "pin": {"type": "git-commit", "value": "b" * 40},
                "license_sha256": hashlib.sha256((checkout / "LICENSE").read_bytes()).hexdigest(),
            }
            rule = {
                "id": "matt",
                "display_name": "Matt Pocock",
                "target_root": "skills/imported/matt",
                "target_prefix": "matt-",
                "mapping": "existing-source-markdown",
                "source_metadata": "references/source.md",
                "license": "MIT",
                "retained_targets": [{
                    "source": "skills/productivity/writing-great-skills",
                    "target": "skills/imported/matt/matt-writing-great-skills",
                    "pin": retained_pin,
                }],
            }

            self.assertEqual(
                materializer.materialize_provider(stage, checkout, provider, rule, "c" * 40),
                {},
            )

    def test_license_text_with_extra_restrictions_does_not_match_approved_digest(self) -> None:
        import tempfile

        materializer = _module()
        approved = b"MIT License\nPermission is hereby granted, free of charge\n"
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary)
            (checkout / "LICENSE").write_bytes(approved + b"Commercial use is prohibited.\n")
            provider = {"license_sha256": hashlib.sha256(approved).hexdigest()}

            with self.assertRaisesRegex(materializer.ProposalError, "upstream_license_changed"):
                materializer.validate_upstream_license(checkout, provider)

    def test_import_refuses_directory_and_dangling_symlinks(self) -> None:
        import os
        import tempfile

        materializer = _module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            external = root / "external"
            source.mkdir()
            external.mkdir()
            (source / "SKILL.md").write_text("skill\n", encoding="utf-8")

            os.symlink(external, source / "linked-directory")
            with self.assertRaisesRegex(materializer.ProposalError, "mapped_skill_invalid"):
                materializer.validated_source_files(source)

            (source / "linked-directory").unlink()
            os.symlink(root / "missing", source / "dangling")
            with self.assertRaisesRegex(materializer.ProposalError, "mapped_skill_invalid"):
                materializer.validated_source_files(source)

            checkout = root / "checkout"
            checkout.mkdir()
            mapped_root = checkout / "mapped-root"
            os.symlink(external, mapped_root)
            with self.assertRaisesRegex(materializer.ProposalError, "mapped_skill_invalid"):
                materializer.validated_source_files(mapped_root, checkout)

            (mapped_root).unlink()
            linked_parent = checkout / "linked-parent"
            os.symlink(external, linked_parent)
            with self.assertRaisesRegex(materializer.ProposalError, "mapped_skill_invalid"):
                materializer.assert_no_symlink_components(linked_parent / "SKILL.md", checkout)


if __name__ == "__main__":
    unittest.main()
