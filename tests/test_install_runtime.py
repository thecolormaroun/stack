"""Focused contract tests for atomic compiled-runtime installation."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIGEST = "d" * 64
SPEC = importlib.util.spec_from_file_location("install_runtime", ROOT / "scripts" / "install-runtime.py")
INSTALLER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(INSTALLER)


class RuntimeInstallTests(unittest.TestCase):
    def write_stage(self, root: Path, name: str, digest: str) -> Path:
        stage = root / "staging" / name
        stage.mkdir(parents=True)
        (stage / "runtime-manifest.json").write_text(json.dumps({"target": name, "registry_digest": digest, "source_commit": "abc"}), encoding="utf-8")
        (stage / "stage-attestation.json").write_text(json.dumps({
            "schema_version": 1, "catalog_digest": digest,
            "runtime_manifest_digest": INSTALLER.digest_file(stage / "runtime-manifest.json"),
            "staged_tree_digest": INSTALLER.staged_tree_digest(stage),
            "source_commit": "abc", "source_tree_digest": "tree",
        }), encoding="utf-8")
        return stage

    def receipts(self, root: Path) -> Path:
        path = root.parent / f"{root.name}-receipts"
        path.mkdir(mode=0o700, exist_ok=True)
        os.chmod(path, 0o700)
        return path

    def write_targets(self, root: Path) -> Path:
        path = root / "targets.json"
        path.write_text(json.dumps({"schema_version": 1, "catalog_digest": DIGEST, "targets": [
            {"name": "codex", "runtime": "codex", "destination": "installed/codex", "post_switch_verifier": ["true"]},
            {"name": "hermes", "runtime": "hermes", "destination": "installed/hermes", "post_switch_verifier": ["true"]},
        ]}), encoding="utf-8")
        return path

    def test_second_target_failure_restores_every_prior_pointer_and_records_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            stages = {"codex": self.write_stage(root, "codex", DIGEST), "hermes": self.write_stage(root, "hermes", DIGEST)}
            old_c = root / "old/codex"; old_h = root / "old/hermes"
            old_c.mkdir(parents=True); old_h.mkdir(parents=True)
            (root / "installed").mkdir()
            (root / "installed/codex").symlink_to(old_c)
            (root / "installed/hermes").symlink_to(old_h)

            with self.assertRaisesRegex(INSTALLER.InstallError, "simulated"):
                INSTALLER.install_runtimes(root, targets, stages, self.receipts(root), fail_after="codex")

            self.assertEqual((root / "installed/codex").resolve(), old_c.resolve())
            self.assertEqual((root / "installed/hermes").resolve(), old_h.resolve())
            receipt_path = self.receipts(root) / "latest.json"
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(receipt["registry_digest"], DIGEST)
            self.assertEqual(receipt["prior_targets"], {"codex": True, "hermes": True})
            self.assertNotIn(str(old_c.resolve()), receipt_path.read_text())

    def test_success_switches_all_targets_and_links_manifest_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            stages = {"codex": self.write_stage(root, "codex", DIGEST), "hermes": self.write_stage(root, "hermes", DIGEST)}

            receipt_dir = self.receipts(root)
            receipt = INSTALLER.install_runtimes(root, targets, stages, receipt_dir)

            self.assertEqual(receipt["status"], "published")
            self.assertRegex(receipt["verified_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
            self.assertEqual((root / "installed/codex").resolve(), stages["codex"].resolve())
            self.assertEqual(receipt["registry_digest"], DIGEST)
            self.assertEqual(stat.S_IMODE((receipt_dir / "latest.json").stat().st_mode), 0o600)

    def test_absolute_destination_is_rejected_even_with_a_deployment_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            value = json.loads(targets.read_text())
            value["targets"][0]["destination"] = "/not-a-deployment-relative-target"
            targets.write_text(json.dumps(value), encoding="utf-8")
            stages = {"codex": self.write_stage(root, "codex", DIGEST), "hermes": self.write_stage(root, "hermes", DIGEST)}

            with self.assertRaisesRegex(INSTALLER.InstallError, "deployment root"):
                INSTALLER.install_runtimes(root, targets, stages, self.receipts(root))

    def test_forged_stage_is_rejected_before_switch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            stages = {"codex": self.write_stage(root, "codex", DIGEST), "hermes": self.write_stage(root, "hermes", DIGEST)}
            (stages["codex"] / "runtime-manifest.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(INSTALLER.InstallError, "staged manifest|attestation"):
                INSTALLER.install_runtimes(root, targets, stages, self.receipts(root))

    def test_staged_private_marker_is_rejected_before_switch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            stages = {"codex": self.write_stage(root, "codex", DIGEST), "hermes": self.write_stage(root, "hermes", DIGEST)}
            (stages["codex"] / "payload.txt").write_text("PRIVATE_PAYLOAD_SENTINEL", encoding="utf-8")
            with self.assertRaisesRegex(INSTALLER.InstallError, "leak scan"):
                INSTALLER.install_runtimes(root, targets, stages, self.receipts(root))

    def test_verifier_failure_rolls_back_and_receipt_has_no_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            value = json.loads(targets.read_text())
            value["targets"][0]["post_switch_verifier"] = ["false"]
            targets.write_text(json.dumps(value), encoding="utf-8")
            stages = {"codex": self.write_stage(root, "codex", DIGEST), "hermes": self.write_stage(root, "hermes", DIGEST)}
            old = root / "old/codex"; old.mkdir(parents=True); (root / "installed").mkdir(); (root / "installed/codex").symlink_to(old)
            receipts = self.receipts(root)
            with self.assertRaisesRegex(INSTALLER.InstallError, "post-switch verifier"):
                INSTALLER.install_runtimes(root, targets, stages, receipts)
            self.assertEqual((root / "installed/codex").resolve(), old.resolve())
            self.assertNotIn(str(old.resolve()), (receipts / "latest.json").read_text())

    def test_broken_installed_pointer_fails_verification_and_rolls_back_all_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            value = json.loads(targets.read_text())
            broken = root / "installed/hermes"
            value["targets"][0]["post_switch_verifier"] = [
                "python3",
                "-c",
                f"from pathlib import Path; Path({str(broken)!r}).unlink()",
            ]
            targets.write_text(json.dumps(value), encoding="utf-8")
            stages = {"codex": self.write_stage(root, "codex", DIGEST), "hermes": self.write_stage(root, "hermes", DIGEST)}

            with self.assertRaisesRegex(INSTALLER.InstallError, "resolvable runtime pointer"):
                INSTALLER.install_runtimes(root, targets, stages, self.receipts(root))

            self.assertFalse((root / "installed/codex").exists())
            self.assertFalse((root / "installed/codex").is_symlink())
            self.assertFalse((root / "installed/hermes").exists())
            self.assertFalse((root / "installed/hermes").is_symlink())

    def test_nonempty_targets_require_catalog_digest_and_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            stages = {"codex": self.write_stage(root, "codex", DIGEST), "hermes": self.write_stage(root, "hermes", DIGEST)}
            value = json.loads(targets.read_text())
            value.pop("catalog_digest")
            targets.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(INSTALLER.InstallError, "pin catalog_digest"):
                INSTALLER.install_runtimes(root, targets, stages, self.receipts(root))

            value["catalog_digest"] = DIGEST
            value["targets"][0].pop("post_switch_verifier")
            targets.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(INSTALLER.InstallError, "requires a non-empty post_switch_verifier"):
                INSTALLER.install_runtimes(root, targets, stages, self.receipts(root))


if __name__ == "__main__":
    unittest.main()
