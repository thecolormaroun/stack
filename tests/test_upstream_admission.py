"""Contracts for the upstream admission rule in docs/upstream-policy.md."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(filename: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


IMPORTER = load("import-pinned-skills.py", "admission_importer")
MAINTENANCE = load("stack-maintenance.py", "admission_maintenance")


def providers() -> dict[str, dict]:
    return {row["id"]: row for row in json.loads((ROOT / "registry/upstreams.json").read_text())["providers"]}


class TrackingFieldTests(unittest.TestCase):
    def test_every_provider_declares_a_tracking_mode(self) -> None:
        for provider_id, provider in providers().items():
            with self.subTest(provider=provider_id):
                self.assertIn(provider.get("tracking"), {"weekly", "pick-only"})

    def test_david_is_pick_only_and_fully_stack_owned(self) -> None:
        self.assertEqual(providers()["david"]["tracking"], "pick-only")
        self.assertFalse((ROOT / "skills/imported/david").exists())
        rules = {row["id"] for row in json.loads((ROOT / "registry/maintenance-imports.json").read_text())["providers"]}
        self.assertNotIn("david", rules)
        policy = json.loads((ROOT / "config/stack-maintenance.json").read_text())
        self.assertNotIn("skills/imported/david/", policy["diff_allowlist"])
        catalog = json.loads((ROOT / "registry/capabilities.json").read_text())["capabilities"]
        self.assertEqual([row["canonical_name"] for row in catalog if row["ownership"]["provider"] == "david"], [])

    def test_pick_only_providers_have_no_tracked_mappings(self) -> None:
        rules = {row["id"]: row for row in json.loads((ROOT / "registry/maintenance-imports.json").read_text())["providers"]}
        for provider_id, provider in providers().items():
            if provider["tracking"] == "pick-only":
                with self.subTest(provider=provider_id):
                    self.assertNotIn(provider_id, rules)
                    self.assertFalse((ROOT / "skills/imported" / provider_id).exists())

    def test_every_provider_is_in_the_audit_table(self) -> None:
        policy = (ROOT / "docs/upstream-policy.md").read_text(encoding="utf-8")
        table = policy.split("## Provider audit", 1)[1]
        rows = {line.split("|")[1].strip() for line in table.splitlines() if line.startswith("| ") and not line.startswith("| ---")}
        self.assertTrue(set(providers()) <= rows, sorted(set(providers()) - rows))

    def test_maintenance_rejects_a_provider_without_tracking(self) -> None:
        registry, lock = MAINTENANCE.load_upstream_metadata()
        MAINTENANCE.validate_upstream_metadata(registry, lock)
        for value in (None, "daily"):
            with self.subTest(tracking=value):
                broken = json.loads(json.dumps(registry))
                if value is None:
                    broken["providers"][0].pop("tracking")
                else:
                    broken["providers"][0]["tracking"] = value
                with self.assertRaisesRegex(MAINTENANCE.PolicyError, "upstream_tracking_invalid"):
                    MAINTENANCE.validate_upstream_metadata(broken, lock)


class ObservationTests(unittest.TestCase):
    def setUp(self) -> None:
        registry, lock = MAINTENANCE.load_upstream_metadata()
        self.providers = MAINTENANCE.validate_upstream_metadata(registry, lock)
        self.tracked = {
            provider_id: provider["pin"]["value"]
            for provider_id, provider in self.providers.items()
            if provider["pin"]["type"] == "git-commit" and provider["tracking"] == "weekly"
        }

    def test_pick_only_provider_is_never_observed_or_proposed(self) -> None:
        drifted = {**self.tracked, "david": "f" * 40}
        for refs in (self.tracked, drifted):
            with self.subTest(with_pick_only=("david" in refs)):
                report = MAINTENANCE.observe_upstream_heads(self.providers, observed_refs=refs)
                david = next(row for row in report["observations"] if row["provider_id"] == "david")
                self.assertEqual(david["status"], "pick_only")
                self.assertIsNone(david["observed_head"])
                self.assertNotIn("david", report["updates_available"])
                self.assertEqual(report["status"], "current")

    def test_missing_tracked_provider_ref_still_fails_closed(self) -> None:
        partial = dict(self.tracked)
        partial.pop("gstack")
        with self.assertRaisesRegex(MAINTENANCE.PolicyError, "observed_provider_set_invalid"):
            MAINTENANCE.observe_upstream_heads(self.providers, observed_refs=partial)


class ImporterAdmissionTests(unittest.TestCase):
    def test_pick_only_provider_is_refused_before_network(self) -> None:
        with self.assertRaises(IMPORTER.AdmissionError) as raised:
            IMPORTER.main(["--provider", "david", "--list-unmapped"])
        self.assertIn("pick-only", str(raised.exception))

    def test_provider_without_tracking_is_refused(self) -> None:
        with self.assertRaisesRegex(IMPORTER.AdmissionError, "must set tracking"):
            IMPORTER.require_tracked({"id": "example"})

    def checkout(self, root: Path, *, license_file: bool = True, readme: bool = True) -> Path:
        root.mkdir()
        if license_file:
            (root / "LICENSE").write_text("MIT License\n", encoding="utf-8")
        if readme:
            (root / "README.md").write_text("# Install\n", encoding="utf-8")
        return root

    def test_weekly_provider_needs_osi_license_license_file_and_readme(self) -> None:
        provider = {"id": "example", "tracking": "weekly", "license": "MIT"}
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            IMPORTER.admission_check(provider, self.checkout(base / "ok"))
            cases = (
                ({**provider, "license": "unknown"}, self.checkout(base / "license-id"), "not an approved OSI license"),
                (provider, self.checkout(base / "no-license", license_file=False), "no license file"),
                (provider, self.checkout(base / "no-readme", readme=False), "no README"),
                ({**provider, "tracking": "pick-only"}, self.checkout(base / "pick-only"), "pick-only"),
            )
            for value, checkout, message in cases:
                with self.subTest(message=message):
                    with self.assertRaisesRegex(IMPORTER.AdmissionError, message):
                        IMPORTER.admission_check(value, checkout)

    def test_symlinked_license_file_does_not_count(self) -> None:
        provider = {"id": "example", "tracking": "weekly", "license": "MIT"}
        with tempfile.TemporaryDirectory() as temporary:
            checkout = self.checkout(Path(temporary) / "repo", license_file=False)
            (Path(temporary) / "elsewhere").write_text("MIT License\n", encoding="utf-8")
            (checkout / "LICENSE").symlink_to(Path(temporary) / "elsewhere")
            with self.assertRaisesRegex(IMPORTER.AdmissionError, "no license file"):
                IMPORTER.admission_check(provider, checkout)


class DownstreamRefusalTests(unittest.TestCase):
    def test_discovery_refuses_a_pick_only_provider(self) -> None:
        discovery = load("discover-upstream-updates.py", "admission_discovery")
        with self.assertRaisesRegex(discovery.DiscoveryPolicyError, "provider_not_tracked"):
            discovery.discover_upstream_update("david", root=ROOT)


if __name__ == "__main__":
    unittest.main()
