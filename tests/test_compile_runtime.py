"""Focused contract tests for catalog-driven runtime compilation."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("compile_runtime", ROOT / "scripts" / "compile-runtime.py")
COMPILER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(COMPILER)


def capability(name: str, *, lifecycle: str = "active", supported: list[str] | None = None, artifact_type: str = "skill", dependencies: list[str] | None = None) -> dict[str, object]:
    value: dict[str, object] = {
        "canonical_name": name,
        "lifecycle": lifecycle,
        "artifact_type": artifact_type,
        "source": {"skill_path": f"skills/{name}/SKILL.md"},
        "runtimes": {"supported": supported if supported is not None else ["codex"], "publish_targets": ["codex"]},
    }
    if dependencies is not None:
        value["dependencies"] = dependencies
    return value


class RuntimeCompileTests(unittest.TestCase):
    def write_catalog(self, root: Path, capabilities: list[dict[str, object]]) -> Path:
        path = root / "registry" / "capabilities.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": 1, "capabilities": capabilities}, indent=2) + "\n", encoding="utf-8")
        return path

    def write_skill(self, root: Path, name: str, body: str = "# Test\n") -> None:
        path = root / "skills" / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "SKILL.md").write_text(body, encoding="utf-8")

    def target(self, root: Path) -> Path:
        path = root / "targets.json"
        catalog = root / "registry" / "capabilities.json"
        digest = COMPILER.digest_file(catalog) if catalog.is_file() else None
        value = {"schema_version": 1, "targets": [{"name": "codex", "runtime": "codex", "destination": "installed/codex"}]}
        if digest is not None:
            value["catalog_digest"] = digest
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_active_entries_compile_deterministically_and_record_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_skill(root, "active")
            self.write_catalog(root, [
                capability("active"), capability("candidate", lifecycle="candidate"),
                capability("archived", lifecycle="archived"),
                capability("private", artifact_type="private-overlay"),
                capability("other", supported=["hermes"]),
            ])
            targets = self.target(root)
            first = COMPILER.compile_runtimes(root, root / "registry/capabilities.json", targets, root / "runtime", source_commit="abc123")
            second = COMPILER.compile_runtimes(root, root / "registry/capabilities.json", targets, root / "runtime-copy", source_commit="abc123")

            manifest = json.loads((first["codex"] / "runtime-manifest.json").read_text())
            self.assertEqual([entry["canonical_name"] for entry in manifest["included"]], ["active"])
            self.assertEqual({entry["canonical_name"]: entry["reason"] for entry in manifest["excluded"]}, {
                "archived": "lifecycle-archived", "candidate": "lifecycle-candidate",
                "other": "unsupported-runtime", "private": "private-incompatible",
            })
            self.assertEqual(manifest["source_commit"], "abc123")
            self.assertTrue((first["codex"] / "skills/active/SKILL.md").is_file())
            self.assertEqual((first["codex"] / "runtime-manifest.json").read_bytes(), (second["codex"] / "runtime-manifest.json").read_bytes())
            self.assertEqual((first["codex"] / "stage-attestation.json").read_bytes(), (second["codex"] / "stage-attestation.json").read_bytes())

    def test_active_compatibility_alias_compiles_from_canonical_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_skill(root, "canonical", "# Canonical\n")
            entry = capability("canonical")
            entry["compatibility_aliases"] = ["legacy-name"]
            self.write_catalog(root, [entry])

            stages = COMPILER.compile_runtimes(
                root, root / "registry/capabilities.json", self.target(root), root / "runtime", source_commit="abc123"
            )

            stage = stages["codex"]
            self.assertEqual((stage / "skills/legacy-name/SKILL.md").read_text(), "# Canonical\n")
            manifest = json.loads((stage / "runtime-manifest.json").read_text())
            self.assertEqual(manifest["compatibility_aliases"], [{"alias": "legacy-name", "canonical_target": "canonical"}])
            self.assertEqual(manifest["included"][0]["compatibility_aliases"], ["legacy-name"])

    def test_compatibility_alias_collision_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_skill(root, "one")
            self.write_skill(root, "two")
            one, two = capability("one"), capability("two")
            one["compatibility_aliases"] = ["two"]
            self.write_catalog(root, [one, two])

            with self.assertRaisesRegex(COMPILER.RuntimeError, "alias collides"):
                COMPILER.compile_runtimes(root, root / "registry/capabilities.json", self.target(root), root / "runtime", source_commit="abc123")

    def test_validation_stops_publication_for_missing_paths_bad_references_and_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_catalog(root, [capability("missing")])
            targets = self.target(root)
            with self.assertRaisesRegex(COMPILER.RuntimeError, "source path"):
                COMPILER.compile_runtimes(root, root / "registry/capabilities.json", targets, root / "runtime")

            self.write_skill(root, "missing", "[missing](references/nope.md)\n")
            with self.assertRaisesRegex(COMPILER.RuntimeError, "reference"):
                COMPILER.compile_runtimes(root, root / "registry/capabilities.json", targets, root / "runtime")

            self.write_skill(root, "missing")
            self.write_catalog(root, [capability("missing", dependencies=["not-in-runtime"])])
            targets = self.target(root)
            with self.assertRaisesRegex(COMPILER.RuntimeError, "dependency"):
                COMPILER.compile_runtimes(root, root / "registry/capabilities.json", targets, root / "runtime")

    def test_fenced_markdown_example_links_are_not_runtime_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_skill(
                root,
                "active",
                "# Test\n\n```md\n[Generated project file](./src/example/CONTEXT.md)\n```\n",
            )
            catalog = self.write_catalog(root, [capability("active")])

            stages = COMPILER.compile_runtimes(
                root,
                catalog,
                self.target(root),
                root / "runtime",
                source_commit="abc123",
            )

            self.assertTrue((stages["codex"] / "skills/active/SKILL.md").is_file())

    def test_generated_template_links_are_not_runtime_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_skill(root, "active")
            template = root / "skills/active/templates/report.md"
            template.parent.mkdir(parents=True)
            template.write_text("[Generated index](./index.md)\n", encoding="utf-8")
            catalog = self.write_catalog(root, [capability("active")])

            stages = COMPILER.compile_runtimes(
                root,
                catalog,
                self.target(root),
                root / "runtime",
                source_commit="abc123",
            )

            self.assertTrue((stages["codex"] / "skills/active/templates/report.md").is_file())

    def test_declared_catalog_digest_must_match_before_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_skill(root, "active")
            catalog = self.write_catalog(root, [capability("active")])
            targets = self.target(root)
            target_value = json.loads(targets.read_text())
            target_value["catalog_digest"] = "0" * 64
            targets.write_text(json.dumps(target_value), encoding="utf-8")

            with self.assertRaisesRegex(COMPILER.RuntimeError, "catalog digest"):
                COMPILER.compile_runtimes(root, catalog, targets, root / "runtime")

    def test_nonempty_targets_require_catalog_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_skill(root, "active")
            catalog = self.write_catalog(root, [capability("active")])
            targets = self.target(root)
            value = json.loads(targets.read_text())
            value.pop("catalog_digest")
            targets.write_text(json.dumps(value), encoding="utf-8")

            with self.assertRaisesRegex(COMPILER.RuntimeError, "pin catalog_digest"):
                COMPILER.compile_runtimes(root, catalog, targets, root / "runtime")

    def test_empty_targets_do_not_require_clean_source_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = self.write_catalog(root, [])
            targets = root / "targets.json"
            targets.write_text(json.dumps({"schema_version": 1, "targets": []}), encoding="utf-8")
            original = COMPILER.compilation_identity
            COMPILER.compilation_identity = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not attest"))
            try:
                self.assertEqual(COMPILER.compile_runtimes(root, catalog, targets, root / "runtime"), {})
            finally:
                COMPILER.compilation_identity = original

    def test_public_catalog_and_generated_manifests_are_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_skill(root, "active")
            catalog = self.write_catalog(root, [capability("active")])
            targets = self.target(root)
            seen: list[Path] = []
            original = COMPILER.OVERLAY.scan_public_artifact
            COMPILER.OVERLAY.scan_public_artifact = lambda path: seen.append(path)
            try:
                COMPILER.compile_runtimes(root, catalog, targets, root / "runtime")
            finally:
                COMPILER.OVERLAY.scan_public_artifact = original

            self.assertEqual(seen[0], catalog.resolve())
            self.assertTrue(any(path.name == "runtime-manifest.json" for path in seen))

    def test_public_leak_rejects_before_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_skill(root, "active")
            catalog = self.write_catalog(root, [capability("active")])
            value = json.loads(catalog.read_text())
            value["public_note"] = "PRIVATE_PAYLOAD_SENTINEL"
            catalog.write_text(json.dumps(value), encoding="utf-8")

            with self.assertRaisesRegex(COMPILER.RuntimeError, "public artifact validation"):
                COMPILER.compile_runtimes(root, catalog, self.target(root), root / "runtime")
            self.assertFalse((root / "runtime").exists())

    def test_public_skill_provenance_url_is_allowed_in_runtime_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_skill(root, "active", "# Test\nSource: https://github.com/example/project\n")
            (root / "skills/active/image.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff")
            catalog = self.write_catalog(root, [capability("active")])
            stages = COMPILER.compile_runtimes(root, catalog, self.target(root), root / "runtime")
            self.assertTrue((stages["codex"] / "skills/active/SKILL.md").is_file())
            self.assertTrue((stages["codex"] / "skills/active/image.png").is_file())

    def test_stage_rewrites_cross_capability_and_docs_links_and_includes_stack_codex_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stack = root / "skills/core/stack"; run = root / "skills/core/run"
            stack.mkdir(parents=True); run.mkdir(parents=True)
            (stack / "SKILL.md").write_text("[run](../run/SKILL.md) [guide](../../../docs/guide.md)\n", encoding="utf-8")
            (run / "SKILL.md").write_text("# Run\n", encoding="utf-8")
            (root / "docs").mkdir(); (root / "docs/guide.md").write_text("# Guide\n", encoding="utf-8")
            entries = [capability("core-stack"), capability("core-run")]
            entries[0]["source"] = {"skill_path": "skills/core/stack/SKILL.md"}
            entries[1]["source"] = {"skill_path": "skills/core/run/SKILL.md"}
            catalog = self.write_catalog(root, entries)
            bundle = root / "packages/stack-codex/content"
            (bundle / "skills/stack-extra").mkdir(parents=True)
            (bundle / "skills/stack-extra/SKILL.md").write_text("# Extra\n", encoding="utf-8")
            (bundle / "commands").mkdir(); (bundle / "commands/extra.md").write_text("# Command\n", encoding="utf-8")
            (bundle / ".codex-plugin").mkdir()
            (bundle / ".codex-plugin/plugin.json").write_text(
                json.dumps({"homepage": "https://github.com/example/stack"}),
                encoding="utf-8",
            )
            (root / "registry/upstreams.json").write_text(json.dumps({"providers": [{"id": "stack-codex", "install": "repository-bundle", "bundle_path": "packages/stack-codex/content", "exports": ["stack-extra"]}]}), encoding="utf-8")

            stages = COMPILER.compile_runtimes(root, catalog, self.target(root), root / "runtime")
            stage = stages["codex"]
            COMPILER.validate_staged_links(stage)
            self.assertTrue((stage / "skills/stack-extra/SKILL.md").is_file())
            self.assertTrue((stage / "commands/extra.md").is_file())
            self.assertIn("../core-run/SKILL.md", (stage / "skills/core-stack/SKILL.md").read_text())
            self.assertIn("../../docs/guide.md", (stage / "skills/core-stack/SKILL.md").read_text())

    def test_private_overlay_is_separate_and_requires_target_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_skill(root, "active")
            catalog = self.write_catalog(root, [capability("active")])
            targets = self.target(root)
            target_value = json.loads(targets.read_text())
            target_value["targets"][0]["name"] = "codex-local"
            targets.write_text(json.dumps(target_value), encoding="utf-8")
            private = root / "private"; private.mkdir(mode=0o700); os.chmod(private, 0o700)
            payload = private / "payload.bin"; payload.write_text("PRIVATE_PAYLOAD_SENTINEL", encoding="utf-8"); os.chmod(payload, 0o600)
            target_manifest = private / "authorized-targets.json"
            target_manifest.write_text(json.dumps({
                "schema_version": 1,
                "owner_identity": "local-owner:test",
                "targets": {"codex-local": "local-target:codex-main"},
            }), encoding="utf-8")
            os.chmod(target_manifest, 0o600)
            overlay = private / "overlay.json"
            overlay.write_text(json.dumps({
                "schema_version": 1, "overlay_id": "private-overlay:reference-pack",
                "public_link": {"catalog_overlay_id": "private-overlay:reference-pack", "policy_id": "private-policy:owner-local"},
                "authorized_runtime_targets": {"codex-local": "local-target:codex-main"},
                "target_authorization": {
                    "manifest_path": str(target_manifest),
                    "owner_identity": "local-owner:test",
                },
                "owner_only": {"overlay_directory_mode": "0700", "file_mode": "0600"},
                "retention": {
                    "payload_retention": "owner-managed-local-only",
                    "delete_on_authorization_removal": True,
                    "delete_on_payload_removal": True,
                    "delete_on_validation_failure": True,
                },
                "payload": {"path": str(payload)},
            }), encoding="utf-8"); os.chmod(overlay, 0o600)
            public = root / "runtime"; private_output = root / "private-output"
            stages = COMPILER.compile_runtimes(root, catalog, targets, public, private_overlay=overlay, private_output_root=private_output)

            self.assertTrue((private_output / "codex-local/private/private-runtime-manifest.json").is_file())
            self.assertFalse((stages["codex-local"] / "private-runtime-manifest.json").exists())
            self.assertNotIn("PRIVATE_PAYLOAD_SENTINEL", (stages["codex-local"] / "runtime-manifest.json").read_text())

            target_value["targets"][0]["name"] = "hermes-local"
            targets.write_text(json.dumps(target_value), encoding="utf-8")
            COMPILER.compile_runtimes(root, catalog, targets, root / "other-public", private_overlay=overlay, private_output_root=root / "other-private")
            self.assertFalse((root / "other-private/hermes-local/private").exists())

    def test_symlinked_capability_input_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            external = root / "external"; external.mkdir()
            (external / "SKILL.md").write_text("PRIVATE_PAYLOAD_SENTINEL", encoding="utf-8")
            skill = root / "skills" / "active"; skill.mkdir(parents=True)
            (skill / "SKILL.md").symlink_to(external / "SKILL.md")
            catalog = self.write_catalog(root, [capability("active")])
            with self.assertRaisesRegex(COMPILER.RuntimeError, "symlinks are not allowed"):
                COMPILER.compile_runtimes(root, catalog, self.target(root), root / "runtime")

    def test_symlinked_shared_roots_and_readme_are_rejected_before_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cases = {
                "docs": "shared docs",
                "registry": "shared registry",
                "templates": "shared templates",
                "artifacts/private-overlay-verification": "private-overlay verification",
                "README.md": "shared README",
            }
            for index, (relative, label) in enumerate(cases.items()):
                with self.subTest(relative=relative):
                    root = Path(temporary) / str(index); root.mkdir()
                    self.write_skill(root, "active")
                    catalog = self.write_catalog(root, [capability("active")])
                    targets = self.target(root)
                    external = root / "outside.md"; external.write_text("# Outside\n", encoding="utf-8")
                    target = root / relative
                    if target.suffix:
                        target.symlink_to(external)
                    else:
                        target.mkdir(parents=True, exist_ok=True)
                        (target / "linked.md").symlink_to(external)
                    with self.assertRaisesRegex(COMPILER.RuntimeError, f"{label}.*symlinks are not allowed"):
                        COMPILER.compile_runtimes(root, catalog, targets, root / "runtime")

    def test_external_package_export_rejects_wrong_head_origin_and_dirty_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"; root.mkdir()
            origin = Path(temporary) / "origin"; origin.mkdir()
            subprocess.run(["git", "init", "-q", str(origin)], check=True)
            subprocess.run(["git", "-C", str(origin), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(origin), "config", "user.name", "Test"], check=True)
            skill = origin / "skills/delegate"; skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("# One\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(origin), "add", "."], check=True)
            subprocess.run(["git", "-C", str(origin), "commit", "-qm", "one"], check=True)
            first = subprocess.check_output(["git", "-C", str(origin), "rev-parse", "HEAD"], text=True).strip()
            (skill / "SKILL.md").write_text("# Two\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(origin), "commit", "-qam", "two"], check=True)
            pin = subprocess.check_output(["git", "-C", str(origin), "rev-parse", "HEAD"], text=True).strip()
            cache = Path(temporary) / "cache"; cache.mkdir()
            checkout = cache / "provider"
            subprocess.run(["git", "clone", "-q", str(origin), str(checkout)], check=True)
            registry = root / "registry"; registry.mkdir()
            upstreams = registry / "upstreams.json"
            upstreams.write_text(json.dumps({"providers": [{
                "id": "provider",
                "canonical_source": str(origin),
                "pin": {"value": pin},
                "exports": ["delegate"],
                "export_paths": {"delegate": "skills/delegate/SKILL.md"},
                "install": "pinned-git-checkout",
            }]}), encoding="utf-8")

            self.assertEqual(COMPILER.external_package_exports(root, cache)[0][1], "delegate")
            subprocess.run(["git", "-C", str(checkout), "checkout", "-q", first], check=True)
            with self.assertRaisesRegex(COMPILER.RuntimeError, "HEAD"):
                COMPILER.external_package_exports(root, cache)
            subprocess.run(["git", "-C", str(checkout), "checkout", "-q", pin], check=True)
            subprocess.run(["git", "-C", str(checkout), "remote", "set-url", "origin", str(root)], check=True)
            with self.assertRaisesRegex(COMPILER.RuntimeError, "origin"):
                COMPILER.external_package_exports(root, cache)
            subprocess.run(["git", "-C", str(checkout), "remote", "set-url", "origin", str(origin)], check=True)
            (checkout / "skills/delegate/SKILL.md").write_text("# Dirty\n", encoding="utf-8")
            with self.assertRaisesRegex(COMPILER.RuntimeError, "dirty"):
                COMPILER.external_package_exports(root, cache)

    def test_dirty_or_arbitrary_commit_override_is_rejected_for_real_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_skill(root, "active")
            catalog = self.write_catalog(root, [capability("active")])
            original = COMPILER.git_output
            COMPILER.git_output = lambda _root, *args: "deadbeef" if args[:2] == ("rev-parse", "--is-inside-work-tree") else ("dirty" if args == ("status", "--porcelain") else None)
            try:
                with self.assertRaisesRegex(COMPILER.RuntimeError, "dirty source tree"):
                    COMPILER.compile_runtimes(root, catalog, self.target(root), root / "runtime")
            finally:
                COMPILER.git_output = original


if __name__ == "__main__":
    unittest.main()
