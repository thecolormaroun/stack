"""Focused contract tests for atomic compiled-runtime installation."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIGEST = "d" * 64
SPEC = importlib.util.spec_from_file_location("install_runtime", ROOT / "scripts" / "install-runtime.py")
INSTALLER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(INSTALLER)


class RuntimeInstallTests(unittest.TestCase):
    def source_commit(self, root: Path) -> str:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()

    def initialize_source(self, root: Path) -> str:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"], check=True)
        (root / ".fixture-source").write_text("main\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture main"], check=True)
        commit = self.source_commit(root)
        (root / ".git/info/exclude").write_text(
            "staging/\ninstalled/\nold/\n",
            encoding="utf-8",
        )
        origin = root.parent / f"{root.name}-origin.git"
        subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=True)
        subprocess.run(["git", "-C", str(root), "remote", "add", "origin", str(origin)], check=True)
        subprocess.run(["git", "-C", str(root), "push", "-q", "origin", "HEAD:refs/heads/main"], check=True)
        INSTALLER.CANONICAL_ORIGIN_URL = str(origin)
        return commit

    def publish_source(self, root: Path, message: str) -> str:
        subprocess.run(["git", "-C", str(root), "add", "registry", "config", ".fixture-source"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", message], check=True)
        subprocess.run(["git", "-C", str(root), "push", "-q", "--force", "origin", "HEAD:refs/heads/main"], check=True)
        return self.source_commit(root)

    def catalog_digest(self, root: Path) -> str:
        return INSTALLER.digest_file(root / "registry/capabilities.json")

    def write_stage(self, root: Path, name: str, digest: str, source_commit: str | None = None) -> Path:
        digest = self.catalog_digest(root) if digest == DIGEST else digest
        source_commit = source_commit or self.source_commit(root)
        stage = root / "staging" / name
        stage.mkdir(parents=True, exist_ok=True)
        (stage / "runtime-manifest.json").write_text(json.dumps({"target": name, "registry_digest": digest, "source_commit": source_commit}), encoding="utf-8")
        (stage / "stage-attestation.json").write_text(json.dumps({
            "schema_version": 1, "catalog_digest": digest,
            "runtime_manifest_digest": INSTALLER.digest_file(stage / "runtime-manifest.json"),
            "staged_tree_digest": INSTALLER.staged_tree_digest(stage),
            "source_commit": source_commit, "source_tree_digest": INSTALLER.COMPILER.source_tree_digest(root),
        }), encoding="utf-8")
        return stage

    def receipts(self, root: Path) -> Path:
        path = root.parent / f"{root.name}-receipts"
        path.mkdir(mode=0o700, exist_ok=True)
        os.chmod(path, 0o700)
        INSTALLER.TRUSTED_RUNTIME_RECEIPTS_ROOT = path.resolve()
        return path.resolve()

    def write_targets(self, root: Path) -> Path:
        catalog = root / "registry/capabilities.json"
        catalog.parent.mkdir(parents=True)
        catalog.write_text(json.dumps({"schema_version": 1, "capabilities": []}), encoding="utf-8")
        path = root / "config/runtime-targets.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"schema_version": 1, "catalog_digest": INSTALLER.digest_file(catalog), "targets": [
            {"name": "codex", "runtime": "codex", "destination": "installed/codex", "post_switch_verifier": ["true"]},
            {"name": "hermes", "runtime": "hermes", "destination": "installed/hermes", "post_switch_verifier": ["true"]},
        ]}), encoding="utf-8")
        self.initialize_source(root)
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
                INSTALLER._switch_compiled_runtimes(
                    root,
                    targets,
                    stages,
                    self.receipts(root),
                    source_repository=root,
                    expected_source_commit=self.source_commit(root),
                    fail_after="codex",
                )

            self.assertEqual((root / "installed/codex").resolve(), old_c.resolve())
            self.assertEqual((root / "installed/hermes").resolve(), old_h.resolve())
            receipt_path = self.receipts(root) / "latest.json"
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(receipt["registry_digest"], self.catalog_digest(root))
            self.assertEqual(receipt["prior_targets"], {"codex": True, "hermes": True})
            self.assertNotIn(str(old_c.resolve()), receipt_path.read_text())

    def test_success_switches_all_targets_and_links_manifest_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            stages = {"codex": self.write_stage(root, "codex", DIGEST), "hermes": self.write_stage(root, "hermes", DIGEST)}

            receipt_dir = self.receipts(root)
            receipt = INSTALLER._switch_compiled_runtimes(
                root,
                targets,
                stages,
                receipt_dir,
                source_repository=root,
                expected_source_commit=self.source_commit(root),
            )

            self.assertEqual(receipt["status"], "published")
            self.assertRegex(receipt["verified_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
            self.assertNotEqual((root / "installed/codex").resolve(), stages["codex"].resolve())
            self.assertEqual(
                INSTALLER.digest_file(root / "installed/codex/runtime-manifest.json"),
                INSTALLER.digest_file(stages["codex"] / "runtime-manifest.json"),
            )
            self.assertEqual(receipt["registry_digest"], self.catalog_digest(root))
            self.assertEqual(stat.S_IMODE((receipt_dir / "latest.json").stat().st_mode), 0o600)
            transaction = receipt_dir / "transactions" / receipt["transaction_id"]
            immutable_install = json.loads((transaction / "install.json").read_text())
            immutable_rollback = json.loads((transaction / "rollback.json").read_text())
            self.assertEqual(receipt["transaction_id"], immutable_install["transaction_id"])
            self.assertEqual(receipt["transaction_id"], immutable_rollback["transaction_id"])
            self.assertEqual({"codex": False, "hermes": False}, immutable_install["prior_targets"])
            self.assertEqual(
                immutable_install["prior_targets"],
                {target: value is not None for target, value in immutable_rollback["prior_targets"].items()},
            )
            self.assertEqual(0o700, stat.S_IMODE(transaction.stat().st_mode))
            self.assertEqual(0o600, stat.S_IMODE((transaction / "install.json").stat().st_mode))

    def test_absolute_destination_is_rejected_even_with_a_deployment_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            value = json.loads(targets.read_text())
            value["targets"][0]["destination"] = "/not-a-deployment-relative-target"
            targets.write_text(json.dumps(value), encoding="utf-8")
            self.publish_source(root, "absolute destination")
            stages = {"codex": self.write_stage(root, "codex", DIGEST), "hermes": self.write_stage(root, "hermes", DIGEST)}

            with self.assertRaisesRegex(INSTALLER.InstallError, "deployment root"):
                INSTALLER._switch_compiled_runtimes(
                    root, targets, stages, self.receipts(root), source_repository=root,
                    expected_source_commit=self.source_commit(root)
                )

    def test_forged_stage_is_rejected_before_switch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            stages = {"codex": self.write_stage(root, "codex", DIGEST), "hermes": self.write_stage(root, "hermes", DIGEST)}
            (stages["codex"] / "runtime-manifest.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(INSTALLER.InstallError, "staged manifest|attestation"):
                INSTALLER._switch_compiled_runtimes(
                    root, targets, stages, self.receipts(root), source_repository=root,
                    expected_source_commit=self.source_commit(root)
                )

    def test_public_cli_rejects_external_targets_and_self_attested_stage_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_targets(root)
            forged_targets = root / "forged-targets.json"
            forged_targets.write_text(json.dumps({
                "schema_version": 1,
                "catalog_digest": self.catalog_digest(root),
                "targets": [{
                    "name": "codex",
                    "runtime": "codex",
                    "destination": "installed/codex",
                    "post_switch_verifier": ["true"],
                }],
            }), encoding="utf-8")
            malicious_stage = root / "malicious-stage"
            malicious_stage.mkdir()
            (malicious_stage / "payload.txt").write_text("self-attested payload\n", encoding="utf-8")
            deployment = root / "deployment"
            result = subprocess.run(
                [
                    "/opt/homebrew/bin/python3.11",
                    str(ROOT / "scripts/install-runtime.py"),
                    "--root", str(deployment),
                    "--source-repository", str(root),
                    "--staging-root", str(root / "trusted-staging"),
                    "--receipts-dir", str(self.receipts(root)),
                    "--expected-source-commit", self.source_commit(root),
                    "--targets", str(forged_targets),
                    "--stage", f"codex={malicious_stage}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(2, result.returncode)
            self.assertIn("unrecognized arguments", result.stderr)
            self.assertFalse((deployment / "installed/codex").exists())

    def test_wrong_stage_commit_is_rejected_before_any_pointer_switch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            stages = {
                "codex": self.write_stage(root, "codex", DIGEST, "a" * 40),
                "hermes": self.write_stage(root, "hermes", DIGEST, "a" * 40),
            }
            with self.assertRaisesRegex(INSTALLER.InstallError, "expected merge commit"):
                INSTALLER._switch_compiled_runtimes(
                    root,
                    targets,
                    stages,
                    self.receipts(root),
                    source_repository=root,
                    expected_source_commit=self.source_commit(root),
                )
            self.assertFalse((root / "installed/codex").exists())
            self.assertFalse((root / "installed/hermes").exists())

    def test_forged_local_origin_main_ref_cannot_authorize_a_non_main_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            (root / ".fixture-source").write_text("candidate\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", ".fixture-source"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "candidate"], check=True)
            candidate_commit = self.source_commit(root)
            subprocess.run(
                ["git", "-C", str(root), "update-ref", "refs/remotes/origin/main", candidate_commit],
                check=True,
            )
            stages = {
                "codex": self.write_stage(root, "codex", DIGEST, candidate_commit),
                "hermes": self.write_stage(root, "hermes", DIGEST, candidate_commit),
            }
            with self.assertRaisesRegex(INSTALLER.InstallError, "origin/main merge commit"):
                INSTALLER._switch_compiled_runtimes(
                    root,
                    targets,
                    stages,
                    self.receipts(root),
                    source_repository=root,
                    expected_source_commit=candidate_commit,
                )
            self.assertFalse((root / "installed/codex").exists())
            self.assertFalse((root / "installed/hermes").exists())

    def test_staged_private_marker_is_rejected_before_switch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            stages = {"codex": self.write_stage(root, "codex", DIGEST), "hermes": self.write_stage(root, "hermes", DIGEST)}
            (stages["codex"] / "payload.txt").write_text("PRIVATE_PAYLOAD_SENTINEL", encoding="utf-8")
            with self.assertRaisesRegex(INSTALLER.InstallError, "leak scan"):
                INSTALLER._switch_compiled_runtimes(
                    root, targets, stages, self.receipts(root), source_repository=root,
                    expected_source_commit=self.source_commit(root)
                )

    def test_verifier_failure_rolls_back_and_receipt_has_no_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            value = json.loads(targets.read_text())
            value["targets"][0]["post_switch_verifier"] = ["false"]
            targets.write_text(json.dumps(value), encoding="utf-8")
            self.publish_source(root, "failing verifier")
            stages = {"codex": self.write_stage(root, "codex", DIGEST), "hermes": self.write_stage(root, "hermes", DIGEST)}
            old = root / "old/codex"; old.mkdir(parents=True); (root / "installed").mkdir(); (root / "installed/codex").symlink_to(old)
            receipts = self.receipts(root)
            with self.assertRaisesRegex(INSTALLER.InstallError, "post-switch verifier"):
                INSTALLER._switch_compiled_runtimes(
                    root, targets, stages, receipts, source_repository=root,
                    expected_source_commit=self.source_commit(root)
                )
            self.assertEqual((root / "installed/codex").resolve(), old.resolve())
            self.assertNotIn(str(old.resolve()), (receipts / "latest.json").read_text())

    def test_verifier_timeout_restores_all_pointers_and_persists_failed_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            value = json.loads(targets.read_text())
            value["targets"][0]["post_switch_verifier"] = [
                "python3", "-c", "import time; time.sleep(0.2)",
            ]
            targets.write_text(json.dumps(value), encoding="utf-8")
            self.publish_source(root, "timeout verifier")
            stages = {"codex": self.write_stage(root, "codex", DIGEST), "hermes": self.write_stage(root, "hermes", DIGEST)}
            old_c = root / "old/codex"; old_h = root / "old/hermes"
            old_c.mkdir(parents=True); old_h.mkdir(parents=True)
            (root / "installed").mkdir()
            (root / "installed/codex").symlink_to(old_c)
            (root / "installed/hermes").symlink_to(old_h)
            receipts = self.receipts(root)
            original_timeout = INSTALLER.VERIFIER_TIMEOUT_SECONDS
            INSTALLER.VERIFIER_TIMEOUT_SECONDS = 0.01
            try:
                with self.assertRaisesRegex(INSTALLER.InstallError, "timed out"):
                    INSTALLER._switch_compiled_runtimes(
                        root,
                        targets,
                        stages,
                        receipts,
                        source_repository=root,
                        expected_source_commit=self.source_commit(root),
                    )
            finally:
                INSTALLER.VERIFIER_TIMEOUT_SECONDS = original_timeout
            self.assertEqual((root / "installed/codex").resolve(), old_c.resolve())
            self.assertEqual((root / "installed/hermes").resolve(), old_h.resolve())
            failed = json.loads((receipts / "latest.json").read_text())
            self.assertEqual("failed", failed["status"])
            transaction = receipts / "transactions" / failed["transaction_id"]
            self.assertTrue((transaction / "install.json").is_file())
            self.assertTrue((transaction / "rollback.json").is_file())

    def test_verifier_tamper_is_confined_to_disposable_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            value = json.loads(targets.read_text())
            value["targets"][0]["post_switch_verifier"] = [
                "python3",
                "-c",
                "from pathlib import Path; p=Path('runtime-manifest.json'); p.chmod(0o600); p.write_text('{}')",
            ]
            targets.write_text(json.dumps(value), encoding="utf-8")
            self.publish_source(root, "tampering verifier")
            stages = {"codex": self.write_stage(root, "codex", DIGEST), "hermes": self.write_stage(root, "hermes", DIGEST)}
            receipts = self.receipts(root)
            receipt = INSTALLER._switch_compiled_runtimes(
                root,
                targets,
                stages,
                receipts,
                source_repository=root,
                expected_source_commit=self.source_commit(root),
            )
            self.assertEqual("published", receipt["status"])
            self.assertEqual(
                self.source_commit(root),
                json.loads((root / "installed/codex/runtime-manifest.json").read_text())["source_commit"],
            )
            INSTALLER.validate_sealed_stage((root / "installed/codex").resolve())

    def test_delayed_verifier_child_is_terminated_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            value = json.loads(targets.read_text())
            child = "import time; from pathlib import Path; time.sleep(0.2); p=Path('runtime-manifest.json'); p.chmod(0o600); p.write_text('{}')"
            value["targets"][0]["post_switch_verifier"] = [
                "python3",
                "-c",
                f"import subprocess, sys; subprocess.Popen([sys.executable, '-c', {child!r}])",
            ]
            targets.write_text(json.dumps(value), encoding="utf-8")
            self.publish_source(root, "delayed verifier child")
            stages = {"codex": self.write_stage(root, "codex", DIGEST), "hermes": self.write_stage(root, "hermes", DIGEST)}
            receipt = INSTALLER._switch_compiled_runtimes(
                root,
                targets,
                stages,
                self.receipts(root),
                source_repository=root,
                expected_source_commit=self.source_commit(root),
            )
            self.assertEqual("published", receipt["status"])
            time.sleep(0.3)
            installed = (root / "installed/codex").resolve()
            INSTALLER.validate_sealed_stage(installed)
            self.assertEqual(self.source_commit(root), json.loads((installed / "runtime-manifest.json").read_text())["source_commit"])

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
            self.publish_source(root, "broken pointer verifier")
            stages = {"codex": self.write_stage(root, "codex", DIGEST), "hermes": self.write_stage(root, "hermes", DIGEST)}

            with self.assertRaisesRegex(INSTALLER.InstallError, "post-switch verifier"):
                INSTALLER._switch_compiled_runtimes(
                    root, targets, stages, self.receipts(root), source_repository=root,
                    expected_source_commit=self.source_commit(root)
                )

            self.assertFalse((root / "installed/codex").exists())
            self.assertFalse((root / "installed/codex").is_symlink())
            self.assertFalse((root / "installed/hermes").exists())
            self.assertFalse((root / "installed/hermes").is_symlink())

    def test_nonempty_targets_require_catalog_digest_and_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            value = json.loads(targets.read_text())
            value.pop("catalog_digest")
            targets.write_text(json.dumps(value), encoding="utf-8")
            self.publish_source(root, "missing catalog digest")
            stages = {"codex": self.write_stage(root, "codex", DIGEST), "hermes": self.write_stage(root, "hermes", DIGEST)}
            with self.assertRaisesRegex(INSTALLER.InstallError, "pin catalog_digest"):
                INSTALLER._switch_compiled_runtimes(
                    root, targets, stages, self.receipts(root), source_repository=root,
                    expected_source_commit=self.source_commit(root)
                )

            value["catalog_digest"] = self.catalog_digest(root)
            value["targets"][0].pop("post_switch_verifier")
            targets.write_text(json.dumps(value), encoding="utf-8")
            self.publish_source(root, "missing verifier")
            stages = {"codex": self.write_stage(root, "codex", DIGEST), "hermes": self.write_stage(root, "hermes", DIGEST)}
            with self.assertRaisesRegex(INSTALLER.InstallError, "requires a non-empty post_switch_verifier"):
                INSTALLER._switch_compiled_runtimes(
                    root, targets, stages, self.receipts(root), source_repository=root,
                    expected_source_commit=self.source_commit(root)
                )

    def test_trusted_receipt_root_cannot_redirect_through_a_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            targets = self.write_targets(root)
            stages = {
                "codex": self.write_stage(root, "codex", DIGEST),
                "hermes": self.write_stage(root, "hermes", DIGEST),
            }
            external = root.parent / f"{root.name}-external-receipts"
            external.mkdir(mode=0o700)
            redirected = root.parent / f"{root.name}-trusted-link"
            redirected.symlink_to(external, target_is_directory=True)
            original_root = INSTALLER.TRUSTED_RUNTIME_RECEIPTS_ROOT
            INSTALLER.TRUSTED_RUNTIME_RECEIPTS_ROOT = redirected
            try:
                with self.assertRaisesRegex(INSTALLER.InstallError, "must not contain symlinks"):
                    INSTALLER._switch_compiled_runtimes(
                        root,
                        targets,
                        stages,
                        redirected,
                        source_repository=root,
                        expected_source_commit=self.source_commit(root),
                    )
            finally:
                INSTALLER.TRUSTED_RUNTIME_RECEIPTS_ROOT = original_root

            self.assertFalse((root / "installed/codex").exists())
            self.assertFalse((root / "installed/hermes").exists())


if __name__ == "__main__":
    unittest.main()
