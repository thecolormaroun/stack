"""Focused contract tests for the capability registry builder."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_capability_registry", ROOT / "scripts" / "build-capability-registry.py"
)
assert SPEC and SPEC.loader
REGISTRY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REGISTRY)


def manifest(name: str, *, lifecycle: str = "active") -> dict[str, object]:
    return {
        "schema_version": 1,
        "canonical_name": name,
        "purpose": "Makes a focused design or build workflow repeatable.",
        "domain": "engineering",
        "family": "engineering",
        "role": "leaf",
        "visibility": "extended",
        "commands": ["stack.build"],
        "ownership": {"provider": "stack", "package": "stack", "source_path": "skills/design-review/SKILL.md"},
        "context": {"inputs": ["request"], "outputs": ["result"]},
        "trust_class": "local-mutation",
        "validation_class": "structural",
        "artifact_type": "skill",
        "lifecycle": lifecycle,
        "audit_status": "reviewed" if lifecycle == "active" else "pending",
        "source": {"skill_path": "skills/design-review/SKILL.md"},
        "provenance": {
            "posture": "repository-local",
            "source_identity": f"stack:skills/{name}",
            "license": "repository-owned",
        },
        "overlaps": [],
        "validation": {"status": "validated", "evidence": ["unit-test"]},
        "runtimes": {"supported": ["codex"], "publish_targets": ["codex"]},
        "disposition": {"status": "keep", "evidence_gap": None, "next_review_trigger": None},
    }


class CapabilityRegistryTests(unittest.TestCase):
    def write_manifest(self, root: Path, relative: str, value: dict[str, object]) -> None:
        path = root / relative / "capability.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        (path.parent / "SKILL.md").write_text("# Test capability\n", encoding="utf-8")
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_valid_active_design_skill_builds_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_manifest(root, "skills/design-review", manifest("design-review"))

            catalog = REGISTRY.build_catalog(root)

        self.assertEqual(catalog["summary"], {"capability_count": 1, "callable_entrypoint_count": 1})
        self.assertEqual(catalog["capabilities"][0]["canonical_name"], "design-review")

    def test_active_entry_missing_required_field_reports_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = manifest("design-review")
            del value["purpose"]
            self.write_manifest(root, "skills/design-review", value)

            with self.assertRaisesRegex(REGISTRY.RegistryError, r"purpose"):
                REGISTRY.build_catalog(root)

    def test_duplicate_canonical_name_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            one = manifest("same-name")
            one["source"] = {"skill_path": "skills/one/SKILL.md"}
            one["provenance"]["source_identity"] = "stack:skills/one"
            two = manifest("same-name")
            two["source"] = {"skill_path": "skills/two/SKILL.md"}
            two["provenance"]["source_identity"] = "stack:skills/two"
            self.write_manifest(root, "skills/one", one)
            self.write_manifest(root, "skills/two", two)

            with self.assertRaisesRegex(REGISTRY.RegistryError, r"duplicate canonical_name"):
                REGISTRY.build_catalog(root)

    def test_duplicate_source_identity_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            one = manifest("one")
            one["source"] = {"skill_path": "skills/one/SKILL.md"}
            two = manifest("two")
            two["source"] = {"skill_path": "skills/two/SKILL.md"}
            two["provenance"]["source_identity"] = one["provenance"]["source_identity"]
            self.write_manifest(root, "skills/one", one)
            self.write_manifest(root, "skills/two", two)

            with self.assertRaisesRegex(REGISTRY.RegistryError, r"duplicate source_identity"):
                REGISTRY.build_catalog(root)

    def test_compatibility_alias_cannot_collide_with_canonical_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            one = manifest("one")
            one["source"] = {"skill_path": "skills/one/SKILL.md"}
            one["compatibility_aliases"] = ["two"]
            two = manifest("two")
            two["source"] = {"skill_path": "skills/two/SKILL.md"}
            self.write_manifest(root, "skills/one", one)
            self.write_manifest(root, "skills/two", two)

            with self.assertRaisesRegex(REGISTRY.RegistryError, r"collides with canonical"):
                REGISTRY.build_catalog(root)

    def test_deprecated_entries_cannot_declare_compatibility_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = manifest("legacy", lifecycle="deprecated")
            value["audit_status"] = "reviewed"
            value["validation"] = {"status": "validated", "evidence": ["review"]}
            value["disposition"] = {
                "status": "hold-pending-evidence",
                "evidence_gap": "Pending review.",
                "next_review_trigger": "Review.",
            }
            value["compatibility_aliases"] = ["old-name"]
            self.write_manifest(root, "skills/design-review", value)

            with self.assertRaisesRegex(REGISTRY.RegistryError, r"only active or blocked candidate"):
                REGISTRY.build_catalog(root)

    def test_check_mode_detects_aggregate_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_manifest(root, "skills/design-review", manifest("design-review"))
            output = root / "registry" / "capabilities.json"
            output.parent.mkdir()
            REGISTRY.write_catalog(root, output)
            self.assertTrue(REGISTRY.catalog_matches(root, output))

            output.write_text("{}\n", encoding="utf-8")
            self.assertFalse(REGISTRY.catalog_matches(root, output))

    def test_seed_namespaces_nested_entrypoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "skills" / "cdo" / "deslop" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: deslop\n---\n# Deslop\n", encoding="utf-8")

            seeded = REGISTRY.seed_manifest(root, skill)

        self.assertEqual(seeded["canonical_name"], "cdo-deslop")

    def test_private_overlay_uses_an_opaque_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = manifest("private-reference", lifecycle="candidate")
            private["artifact_type"] = "private-overlay"
            private["audit_status"] = "pending"
            private["source"] = {"overlay_id": "private-overlay:reference-pack"}
            private["provenance"] = {
                "posture": "private-overlay",
                "source_identity": "private:reference-pack",
                "license": "owner-controlled",
            }
            private["validation"] = {"status": "pending", "evidence": []}
            private["runtimes"] = {"supported": [], "publish_targets": []}
            private["disposition"] = {
                "status": "hold-pending-evidence",
                "evidence_gap": "Awaiting overlay review.",
                "next_review_trigger": "Review overlay authorization.",
            }
            self.write_manifest(root, "skills/private-reference", private)

            catalog = REGISTRY.build_catalog(root)

        self.assertEqual(catalog["capabilities"][0]["source"], {"overlay_id": "private-overlay:reference-pack"})

    def test_unknown_nested_private_field_is_rejected_before_aggregation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = manifest("design-review")
            value["provenance"]["private_payload"] = "PRIVATE_PAYLOAD_SENTINEL"
            self.write_manifest(root, "skills/design-review", value)

            with self.assertRaisesRegex(REGISTRY.RegistryError, r"provenance has unsupported field"):
                REGISTRY.build_catalog(root)

    def test_symlinked_capability_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_manifest(root, "skills/design-review", manifest("design-review"))
            external = root / "external.json"
            external.write_text(json.dumps(manifest("design-review")), encoding="utf-8")
            (root / "skills/design-review/capability.json").unlink()
            (root / "skills/design-review/capability.json").symlink_to(external)
            with self.assertRaisesRegex(REGISTRY.RegistryError, "symlinks are not allowed"):
                REGISTRY.build_catalog(root)


if __name__ == "__main__":
    unittest.main()
