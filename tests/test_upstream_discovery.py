from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "discover-upstream-updates.py"


def _module():
    spec = importlib.util.spec_from_file_location("upstream_discovery", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _provider():
    registry = json.loads((ROOT / "registry/upstreams.json").read_text(encoding="utf-8"))
    return next(row for row in registry["providers"] if row["id"] == "gstack")


class UpstreamDiscoveryTests(unittest.TestCase):
    def test_unchanged_provider_is_a_true_no_action(self) -> None:
        discovery = _module()
        provider = _provider()
        before = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout

        result = discovery.discover_upstream_update(
            "gstack",
            {"candidate_pin": provider["pin"]["value"]},
            root=ROOT,
        )

        after = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        self.assertEqual(result["status"], "no_action")
        self.assertEqual(result["terminal_classification"], "no_action")
        self.assertEqual(result["old_pin"], result["new_pin"])
        self.assertEqual(result["changed_exports"], [])
        self.assertTrue(result["checks"]["source_tree_digest_identical"])
        self.assertTrue(result["checks"]["generated_manifest_digest_identical"])
        self.assertTrue(result["checks"]["output_semantic_digest_identical"])
        self.assertFalse(result["receipt"]["persisted"])
        self.assertEqual(before, after)

    def test_synthetic_newer_pin_is_provider_scoped_prepared_packet(self) -> None:
        discovery = _module()
        result = discovery.discover_upstream_update(
            "gstack",
            {
                "candidate": {
                    "pin": "f" * 40,
                    "source_tree_digest": "candidate-source-tree",
                    "generated_manifest_digest": "candidate-generated-manifest",
                    "output_semantic_digest": "candidate-output",
                    "changed_exports": ["qa"],
                    "version_risk_class": "compatible",
                    "compatibility_evidence": {
                        "status": "verified",
                        "checks": ["tests/test_upstream_packages.py"],
                    },
                    "release_evidence": {"url": "https://example.invalid/releases/next"},
                    "deprecation_evidence": {"status": "none"},
                }
            },
            root=ROOT,
        )

        self.assertEqual(result["status"], "prepared")
        self.assertEqual(result["terminal_classification"], "prepared")
        self.assertEqual(result["old_pin"], _provider()["pin"]["value"])
        self.assertEqual(result["new_pin"], "f" * 40)
        self.assertEqual(result["changed_exports"], ["qa"])
        self.assertEqual(result["version_risk_class"], "compatible")
        self.assertEqual(result["affected_runtimes"], ["claude", "codex"])
        self.assertEqual(result["approval_owner"], "stack-maintainer")
        self.assertTrue(result["checks"]["candidate_evidence_complete"])
        self.assertTrue(result["checks"]["materializer_invoked"] is False)
        self.assertTrue(result["checks"]["publication_attempted"] is False)
        self.assertEqual(result["rollback_pointer"]["pin"], result["old_pin"])

    def test_newer_pin_without_candidate_evidence_awaits_evidence(self) -> None:
        discovery = _module()
        result = discovery.discover_upstream_update(
            "gstack",
            {"candidate_pin": "e" * 40},
            root=ROOT,
        )
        self.assertEqual(result["status"], "prepared")
        self.assertEqual(result["version_risk_class"], "unknown")
        self.assertTrue(result["checks"]["candidate_evidence_pending"])
        self.assertFalse(result["checks"]["candidate_evidence_complete"])
        self.assertEqual(result["compatibility_evidence"]["status"], "pending")
        self.assertEqual(result["reason_code"], "candidate_evidence_pending")

    def test_unsafe_lineage_multiple_candidates_and_protected_vendor_block(self) -> None:
        discovery = _module()
        cases = [
            ({"candidates": [{"pin": "a" * 40}, {"pin": "b" * 40}]}, "multiple_candidates"),
            ({"candidate_pin": "c" * 40, "lineage_status": "ambiguous"}, "unsafe_lineage"),
            ({"candidate_pin": "d" * 40, "protected_vendor": {"status": "dirty"}}, "dirty_protected_vendor"),
            ({"candidate_pin": "e" * 40, "duplicate_pr_lane": True}, "duplicate_pr_lane"),
            ({"candidate_pin": "f" * 40, "unexpected_paths": ["unexpected.txt"]}, "unexpected_path"),
            ({"candidate_pin": "a" * 40, "deleted_paths": ["skills/qa/SKILL.md"]}, "deletion_requires_review"),
        ]
        for observation, reason in cases:
            with self.subTest(reason=reason):
                result = discovery.discover_upstream_update("gstack", observation, root=ROOT)
                self.assertEqual(result["status"], "blocked")
                self.assertIn(reason, result["unsafe_reasons"])

    def test_same_pin_digest_mismatch_blocks_semantic_churn(self) -> None:
        discovery = _module()
        result = discovery.discover_upstream_update(
            "gstack",
            {
                "candidate_pin": _provider()["pin"]["value"],
                "candidate": {
                    "source_tree_digest": "different-source-tree",
                    "generated_manifest_digest": "different-generated-manifest",
                    "output_semantic_digest": "different-output",
                },
            },
            root=ROOT,
        )
        self.assertEqual(result["status"], "blocked")
        self.assertIn("same_pin_digest_mismatch", result["unsafe_reasons"])

    def test_live_observation_is_scoped_to_selected_provider(self) -> None:
        discovery = _module()
        provider = _provider()
        providers = {
            "gstack": provider,
            "matt": {**provider, "id": "matt"},
        }
        observer = mock.Mock(
            observe_upstream_heads=mock.Mock(
                return_value={
                    "observations": [{
                        "provider_id": "gstack",
                        "pin": provider["pin"]["value"],
                        "observed_head": provider["pin"]["value"],
                        "status": "current",
                    }]
                }
            )
        )
        value, refs = discovery._normalise_observation(
            None,
            provider_id="gstack",
            candidate_pin=None,
            live=True,
            maintenance=observer,
            providers=providers,
        )
        observer.observe_upstream_heads.assert_called_once_with({"gstack": provider})
        self.assertEqual(value["provider"]["provider_id"], "gstack")
        self.assertEqual(refs, {"gstack": provider["pin"]["value"]})

    def test_receipt_binding_reuses_maintenance_audit_lane(self) -> None:
        discovery = _module()
        maintenance = discovery._maintenance_module(ROOT)
        receipt = {
            "run_id": "discovery-proof",
            "terminal_classification": "awaiting_approval",
            "result": "upstream_updates_detected",
        }
        with (
            mock.patch.object(discovery, "_maintenance_module", return_value=maintenance),
            mock.patch.object(maintenance, "run", return_value=receipt) as run,
        ):
            result = discovery.discover_upstream_update(
                "gstack",
                {
                    "candidate": {
                        "pin": "f" * 40,
                        "source_tree_digest": "candidate-source-tree",
                        "generated_manifest_digest": "candidate-generated-manifest",
                        "output_semantic_digest": "candidate-output",
                        "compatibility_evidence": {"status": "verified"},
                    }
                },
                root=ROOT,
                state_dir=Path("/owner-local/maintenance"),
            )

        kwargs = run.call_args.kwargs
        self.assertEqual("audit", kwargs["mode"])
        self.assertEqual(result["provider_id"], kwargs["discovery_packet"]["provider_id"])
        self.assertEqual(result["new_pin"], kwargs["discovery_packet"]["new_pin"])
        self.assertEqual("f" * 40, kwargs["observed_refs"]["gstack"])
        self.assertNotIn("github", kwargs)
        self.assertTrue(result["receipt"]["persisted"])
        self.assertEqual("awaiting_approval", result["receipt"]["terminal_classification"])

    def test_private_or_oversized_release_evidence_is_rejected(self) -> None:
        discovery = _module()
        private = discovery.discover_upstream_update(
            "gstack",
            {
                "candidate_pin": "a" * 40,
                "release_evidence": {"notes": str(Path.home() / "private")},
            },
            root=ROOT,
        )
        self.assertEqual(private["status"], "blocked")
        self.assertIn("evidence_private_data", private["unsafe_reasons"])
        oversized = discovery.discover_upstream_update(
            "gstack",
            {
                "candidate_pin": "b" * 40,
                "release_evidence": {"notes": "x" * 17000},
            },
            root=ROOT,
        )
        self.assertEqual(oversized["status"], "blocked")
        self.assertIn("evidence_too_large", oversized["unsafe_reasons"])

    def test_cli_help_is_available_without_network(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("provider", result.stdout)


if __name__ == "__main__":
    unittest.main()
