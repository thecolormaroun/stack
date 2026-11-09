from __future__ import annotations

import hashlib
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
    def test_missing_mapped_directory_requires_explicit_deletion_approval(self) -> None:
        import tempfile

        materializer = _module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage, checkout = root / "stage", root / "checkout"
            target = stage / "skills/imported/david/david-agent-self-scheduling"
            (target / "references").mkdir(parents=True)
            checkout.mkdir()
            license_bytes = b"MIT License\nPermission is hereby granted, free of charge\n"
            (checkout / "LICENSE").write_bytes(license_bytes)
            old_pin, new_pin = "a" * 40, "b" * 40
            (target / "SKILL.md").write_text("preserve existing bytes\n", encoding="utf-8")
            (target / "references/source.md").write_text(
                f"- Upstream path: `skills/agent-orchestration/agent-self-scheduling`\n- Inspected commit: `{old_pin}`\n",
                encoding="utf-8",
            )
            provider = {
                "id": "david",
                "canonical_source": "https://github.com/davidondrej/skills.git",
                "pin": {"type": "git-commit", "value": old_pin},
                "license_sha256": hashlib.sha256(license_bytes).hexdigest(),
            }
            rule = {
                "id": "david", "display_name": "David Ondrej",
                "mapping": "existing-source-markdown", "license": "MIT",
                "target_root": "skills/imported/david", "target_prefix": "david-",
                "source_metadata": "references/source.md",
                "retained_targets": [{
                    "source": "skills/ops-and-setup/cyber-audit",
                    "target": "skills/imported/david/david-cyber-audit",
                    "pin": old_pin,
                }],
            }

            with self.assertRaisesRegex(materializer.ProposalError, "upstream_deletion_requires_approval"):
                materializer.materialize_provider(stage, checkout, provider, rule, new_pin)
            self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), "preserve existing bytes\n")

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

    def test_import_name_accepts_provider_prefix_or_exact_name_only(self) -> None:
        import tempfile

        materializer = _module()
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "SKILL.md"

            def imported(upstream: str, target: str) -> str:
                source.write_text(f"---\nname: {upstream}\ndescription: x\n---\nbody\n", encoding="utf-8")
                return materializer.materialized_skill(
                    source, target_name=target, display_name="Emil Kowalski", commit="c" * 40, metadata_path="references/source.json"
                ).decode("utf-8")

            self.assertIn("name: emil-animate\n", imported("animate", "emil-animate"))
            self.assertIn("name: emil-design-eng\n", imported("emil-design-eng", "emil-design-eng"))
            self.assertIn("name: review-animations\n", imported("review-animations", "review-animations"))
            self.assertIn("name: matt-tdd\n", imported("tdd", "matt-tdd"))
            for upstream, target in (("animate", "emil-choreograph"), ("animate", "animate-x"), ("animate", "other-animate")):
                with self.assertRaisesRegex(materializer.ProposalError, "import_name_mismatch"):
                    imported(upstream, target)

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

    def test_retained_files_keep_each_origin_across_consecutive_advances(self) -> None:
        import tempfile

        materializer = _module()
        for mapping in ("existing-source-markdown", "explicit-source-json"):
            with self.subTest(mapping=mapping), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                stage, checkout = root / "stage", root / "checkout"
                source_relative = Path("skills/engineering/domain-modeling")
                target_relative = Path("skills/imported/matt/matt-domain-modeling")
                source, target = checkout / source_relative, stage / target_relative
                source.mkdir(parents=True)
                (target / "references").mkdir(parents=True)
                license_bytes = b"MIT License\nPermission is hereby granted, free of charge\n"
                (checkout / "LICENSE").write_bytes(license_bytes)
                (source / "SKILL.md").write_text("---\nname: domain-modeling\ndescription: x\n---\nbody\n")
                (source / "later.md").write_bytes(b"second retained file\n")
                (target / "SKILL.md").write_text("existing imported skill\n")
                (target / "capability.json").write_text("{}\n")
                (target / "legacy.md").write_bytes(b"first retained file\n")
                (target / "later.md").write_bytes(b"second retained file\n")
                metadata_relative = Path("references/source.md" if mapping == "existing-source-markdown" else "references/source.json")
                metadata = target / metadata_relative
                if mapping == "existing-source-markdown":
                    metadata.write_text(f"- Upstream path: `{source_relative}`\n- Inspected commit: `{'a' * 40}`\n")
                else:
                    metadata.write_text("{}\n")
                provider = {
                    "pin": {"type": "git-commit", "value": "a" * 40},
                    "canonical_source": "https://github.com/mattpocock/skills.git",
                    "license_sha256": hashlib.sha256(license_bytes).hexdigest(),
                }
                rule = {
                    "mapping": mapping, "license": "MIT", "display_name": "Matt Pocock",
                    "target_root": "skills/imported/matt", "target_prefix": "matt-",
                    "source_metadata": metadata_relative.as_posix(),
                    "retained_files": ["legacy.md", "later.md"],
                    "targets": [{"source": source_relative.as_posix(), "target": target_relative.as_posix()}],
                }
                for pin in ("b" * 40, "c" * 40, "d" * 40):
                    if pin == "c" * 40:
                        (source / "later.md").unlink()
                    outputs = materializer.materialize_provider(stage, checkout, provider, rule, pin)
                    self.assertNotIn((target_relative / "legacy.md").as_posix(), outputs)
                    for relative, content in outputs.items():
                        path = stage / relative
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(content)
                    provider["pin"]["value"] = pin
                    expected = {"legacy.md": "a" * 40}
                    if pin != "b" * 40:
                        expected["later.md"] = "b" * 40
                        self.assertNotIn((target_relative / "later.md").as_posix(), outputs)
                    self.assertEqual(materializer.retained_file_origins(metadata, mapping), expected)
                    self.assertEqual((target / "legacy.md").read_bytes(), b"first retained file\n")
                    self.assertEqual((target / "later.md").read_bytes(), b"second retained file\n")

    def test_legacy_retained_file_metadata_and_malformed_origins(self) -> None:
        import json
        import tempfile

        materializer = _module()
        with tempfile.TemporaryDirectory() as temporary:
            metadata = Path(temporary) / "source.md"
            metadata.write_text(
                f"- Retained removed files: `old.md`\n- Retained files inspected commit: `{'a' * 40}`\n"
            )
            self.assertEqual(materializer.retained_file_origins(metadata, "existing-source-markdown"), {"old.md": "a" * 40})
            for text in (
                "- Retained removed files: `old.md`\n",
                "- Retained files inspected commit: `bad`\n",
                f"- Retained file: `old.md` at `{'a' * 40}`\n- Retained file: `old.md` at `{'b' * 40}`\n",
            ):
                metadata.write_text(text)
                with self.assertRaisesRegex(materializer.ProposalError, "retained_file_metadata_invalid"):
                    materializer.retained_file_origins(metadata, "existing-source-markdown")
            metadata = Path(temporary) / "source.json"
            for rows in (None, [{"path": "old.md", "inspected_commit": "bad"}], [{"path": "old.md", "inspected_commit": "a" * 40}] * 2):
                metadata.write_text(json.dumps({"retained_files": rows}))
                with self.assertRaisesRegex(materializer.ProposalError, "retained_file_metadata_invalid"):
                    materializer.retained_file_origins(metadata, "explicit-source-json")

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
