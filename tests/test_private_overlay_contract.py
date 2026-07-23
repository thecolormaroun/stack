"""Contract tests for Stack's local-only private overlay boundary."""

from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "private-overlay"
SPEC = importlib.util.spec_from_file_location("private_overlay", ROOT / "scripts" / "validate-private-overlay.py")
assert SPEC and SPEC.loader
OVERLAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OVERLAY)


class PrivateOverlayContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.chmod(self.root, 0o700)
        self.payload = self.root / "payload.bin"
        self.payload.write_text("PRIVATE_PAYLOAD_SENTINEL", encoding="utf-8")
        os.chmod(self.payload, 0o600)
        overlay = json.loads((FIXTURES / "authorized-overlay.json").read_text(encoding="utf-8"))
        overlay["payload"]["path"] = str(self.payload)
        self.target_manifest = self.root / "target-authorizations.json"
        self.target_manifest.write_text(json.dumps({
            "schema_version": 1,
            "owner_identity": "local-owner:primary",
            "targets": {"codex-local": "local-target:codex-main"},
        }), encoding="utf-8")
        os.chmod(self.target_manifest, 0o600)
        overlay["target_authorization"]["manifest_path"] = str(self.target_manifest)
        self.overlay_path = self.root / "overlay.json"
        self.overlay_path.write_text(json.dumps(overlay), encoding="utf-8")
        os.chmod(self.overlay_path, 0o600)
        self.output = self.root / "compiled"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_authorized_local_runtime_gets_separate_private_manifest(self) -> None:
        result = OVERLAY.compile_overlay(self.overlay_path, "codex-local", self.output)

        self.assertEqual(result["status"], "compiled")
        manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["payload_path"], str(self.payload))
        self.assertEqual(stat.S_IMODE(Path(result["manifest"]).stat().st_mode), 0o600)
        self.assertTrue(Path(result["receipt"]).is_file())

    def test_unauthorized_runtime_is_excluded_without_payload_inference(self) -> None:
        result = OVERLAY.compile_overlay(self.overlay_path, "public-runtime", self.output)

        self.assertEqual(result, {"status": "excluded", "reason": "target_not_authorized"})
        self.assertFalse(self.output.exists())
        self.assertNotIn("payload", json.dumps(result))

    def test_public_artifact_leaks_are_rejected(self) -> None:
        with self.assertRaisesRegex(OVERLAY.OverlayError, "forbidden"):
            OVERLAY.scan_public_artifact(FIXTURES / "public-artifact-leak.json")

        for leak in ("PRIVATE_PAYLOAD_SENTINEL", "PRIVATE_TITLE_SENTINEL", "PRIVATE_URL_SENTINEL", "PRIVATE_EXCERPT_SENTINEL", "https://example.invalid/non-public", "/Users/local-only/payload"):
            with self.subTest(leak=leak), self.assertRaisesRegex(OVERLAY.OverlayError, "forbidden"):
                OVERLAY.scan_public_value({"receipt": leak})

        OVERLAY.scan_public_value({"overlay_id": "private-overlay:reference-pack", "policy_id": "private-policy:owner-local"})

    def test_public_runtime_payload_allows_provenance_links_but_rejects_sensitive_urls(self) -> None:
        skill = self.root / "SKILL.md"
        skill.write_text(
            "Read https://github.com/example/project for provenance, connect to http://localhost:9222, "
            "open file:///absolute/path/to/report.html, and write a disposable report under /tmp/stack-report.\n",
            encoding="utf-8",
        )
        OVERLAY.scan_public_runtime_payload(skill)

        credentialed = "https://" + "user:pass@" + "example.com/repo"
        for leak in (
            "file:///Users/local/private",
            "/home/local/private",
            credentialed,
            "https://example.com/repo?token=secret",
        ):
            skill.write_text(leak, encoding="utf-8")
            with self.subTest(leak=leak), self.assertRaisesRegex(OVERLAY.OverlayError, "forbidden"):
                OVERLAY.scan_public_runtime_payload(skill)

    def test_public_runtime_payload_allows_binary_assets_but_scans_embedded_markers(self) -> None:
        asset = self.root / "asset.png"
        asset.write_bytes(b"\x89PNG\r\n\x1a\n\x00\xffpublic-binary")
        OVERLAY.scan_public_runtime_payload(asset)

        asset.write_bytes(b"\x89PNG\r\n\x1a\n\x00\xffPRIVATE_PAYLOAD_SENTINEL")
        with self.assertRaisesRegex(OVERLAY.OverlayError, "forbidden"):
            OVERLAY.scan_public_runtime_payload(asset)

    def test_removed_authorization_or_payload_fails_closed_without_public_output(self) -> None:
        overlay = json.loads(self.overlay_path.read_text(encoding="utf-8"))
        overlay["authorized_runtime_targets"] = {"other-local": "local-target:other-main"}
        self.overlay_path.write_text(json.dumps(overlay), encoding="utf-8")
        self.assertEqual(OVERLAY.compile_overlay(self.overlay_path, "codex-local", self.output)["status"], "excluded")

        overlay["authorized_runtime_targets"] = {"codex-local": "local-target:codex-main"}
        self.overlay_path.write_text(json.dumps(overlay), encoding="utf-8")
        self.payload.unlink()
        with self.assertRaisesRegex(OVERLAY.OverlayError, "missing owner-only"):
            OVERLAY.compile_overlay(self.overlay_path, "codex-local", self.output)
        self.assertFalse(self.output.exists())

    def test_stale_output_is_revoked_on_authorization_removal(self) -> None:
        OVERLAY.compile_overlay(self.overlay_path, "codex-local", self.output)
        overlay = json.loads(self.overlay_path.read_text(encoding="utf-8"))
        overlay["authorized_runtime_targets"] = {"other-local": "local-target:other-main"}
        self.overlay_path.write_text(json.dumps(overlay), encoding="utf-8")

        self.assertEqual(OVERLAY.compile_overlay(self.overlay_path, "codex-local", self.output)["status"], "excluded")
        self.assertFalse(self.output.exists())

    def test_trusted_manifest_revocation_removes_existing_private_output(self) -> None:
        OVERLAY.compile_overlay(self.overlay_path, "codex-local", self.output)
        manifest = json.loads(self.target_manifest.read_text(encoding="utf-8"))
        manifest["targets"] = {"codex-local": "local-target:revoked"}
        self.target_manifest.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaisesRegex(OVERLAY.OverlayError, "trusted local target manifest"):
            OVERLAY.compile_overlay(self.overlay_path, "codex-local", self.output)
        self.assertFalse(self.output.exists())

    def test_invalid_owner_mode_or_payload_revokes_existing_private_output(self) -> None:
        OVERLAY.compile_overlay(self.overlay_path, "codex-local", self.output)
        os.chmod(self.target_manifest, 0o644)

        with self.assertRaisesRegex(OVERLAY.OverlayError, "must be owned"):
            OVERLAY.compile_overlay(self.overlay_path, "codex-local", self.output)
        self.assertFalse(self.output.exists())

        os.chmod(self.target_manifest, 0o600)
        OVERLAY.compile_overlay(self.overlay_path, "codex-local", self.output)
        os.chmod(self.payload, 0o644)
        with self.assertRaisesRegex(OVERLAY.OverlayError, "must be owned"):
            OVERLAY.compile_overlay(self.overlay_path, "codex-local", self.output)
        self.assertFalse(self.output.exists())

    def test_cli_output_and_receipt_are_opaque(self) -> None:
        result = OVERLAY.compile_overlay(self.overlay_path, "codex-local", self.output)
        receipt = Path(result["receipt"]).read_text(encoding="utf-8")
        self.assertNotIn(str(self.payload), receipt)
        self.assertNotIn("PRIVATE_PAYLOAD_SENTINEL", receipt)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(OVERLAY.main([
                "--overlay", str(self.overlay_path),
                "--target", "codex-local",
                "--output", str(self.output),
            ]), 0)
        self.assertNotIn(str(self.payload), stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
