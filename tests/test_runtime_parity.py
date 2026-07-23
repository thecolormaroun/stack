"""Contracts for the read-only runtime bootstrap and doctor."""

from __future__ import annotations

import importlib.util
import hashlib
import json
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


DOCTOR = load("stack_doctor_test", "stack-doctor.py")
BOOTSTRAP = load("bootstrap_stack_test", "bootstrap-stack.py")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def fixture(root: Path) -> None:
    provider = {"id": "provider", "pin": {"type": "git-commit", "value": "a" * 40}, "last_known_good": {"pin": "a" * 40}, "exports": ["delegate"]}
    write_json(root / "registry/families.json", {"schema_version": 1, "families": [{"id": "core", "allowed_roles": ["router"]}]})
    write_json(root / "registry/commands.json", {"schema_version": 1, "commands": [{"id": "stack", "runtimes": {"claude": "/stack", "codex": "stack"}, "aliases": [{"name": "stack", "kind": "runtime", "canonical_warning": False}]}]})
    write_json(root / "registry/upstreams.json", {"schema_version": 1, "providers": [provider]})
    write_json(root / "upstreams.lock.json", {"providers": {"provider": "a" * 40}})
    write_json(root / "packages/provider/package.json", {"schema_version": 1, "provider": "provider", "registry": "registry/upstreams.json", "copy_upstream_source": False, "exports": ["delegate"]})
    write_json(root / "registry/capabilities.json", {"schema_version": 1, "capabilities": [{"canonical_name": "stack", "lifecycle": "active", "family": "core", "role": "router", "runtimes": {"supported": ["claude", "codex"], "publish_targets": ["claude", "codex"]}}]})
    write_json(root / "config/runtime-targets.json", {"schema_version": 1, "targets": []})


class RuntimeParityTests(unittest.TestCase):
    def test_doctor_reports_primary_claude_codex_parity_and_public_source_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root)
            report = DOCTOR.doctor(root)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["summary"]["commands"], 1)
        self.assertNotIn(str(root), json.dumps(report))

    def test_doctor_fails_closed_for_unclassified_active_entry_and_missing_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root)
            catalog = json.loads((root / "registry/capabilities.json").read_text())
            catalog["capabilities"][0]["family"] = "unclassified"
            write_json(root / "registry/capabilities.json", catalog)
            commands = json.loads((root / "registry/commands.json").read_text())
            commands["commands"][0]["runtimes"].pop("codex")
            write_json(root / "registry/commands.json", commands)
            report = DOCTOR.doctor(root)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(any("unclassified" in error for error in report["errors"]))
        self.assertTrue(any("parity" in error for error in report["errors"]))

    def test_bootstrap_dry_run_is_idempotent_and_package_drift_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root)
            before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            first = BOOTSTRAP.bootstrap(root)
            second = BOOTSTRAP.bootstrap(root)
            after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            self.assertEqual(first, second)
            self.assertEqual(first["mode"], "dry-run")
            self.assertEqual(before, after)
            lock = json.loads((root / "upstreams.lock.json").read_text())
            lock["providers"]["provider"] = "b" * 40
            write_json(root / "upstreams.lock.json", lock)
            with self.assertRaisesRegex(BOOTSTRAP.BootstrapError, "doctor checks failed"):
                BOOTSTRAP.bootstrap(root)

    def test_live_install_requires_an_explicit_deployment_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root)
            with self.assertRaisesRegex(BOOTSTRAP.BootstrapError, "deployment-root"):
                BOOTSTRAP.bootstrap(
                    root,
                    install=True,
                    staging_root=root / "staging",
                    receipts_dir=root.parent / "receipts",
                )

    def test_doctor_fails_closed_when_a_repository_bundle_drifts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root)
            bundle = root / "packages/provider/content"
            bundle.mkdir(parents=True)
            (bundle / "SKILL.md").write_text("# Bundled\n", encoding="utf-8")
            digest = hashlib.sha256()
            digest.update(b"SKILL.md\0# Bundled\n\0")
            pin = digest.hexdigest()

            upstreams = json.loads((root / "registry/upstreams.json").read_text())
            provider = upstreams["providers"][0]
            provider.update({
                "install": "repository-bundle",
                "bundle_path": "packages/provider/content",
                "pin": {"type": "sha256", "value": pin},
                "last_known_good": {"pin": pin},
            })
            write_json(root / "registry/upstreams.json", upstreams)
            write_json(root / "upstreams.lock.json", {"providers": {"provider": pin}})
            self.assertEqual(DOCTOR.doctor(root)["status"], "ok")

            (bundle / "SKILL.md").write_text("# Tampered\n", encoding="utf-8")
            report = DOCTOR.doctor(root)
            self.assertEqual(report["status"], "failed")
            self.assertTrue(any("integrity" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
