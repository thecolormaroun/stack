from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UpstreamPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = json.loads((ROOT / "registry/upstreams.json").read_text())
        self.lock = json.loads((ROOT / "upstreams.lock.json").read_text())

    def test_allowlisted_immutable_pins_and_last_known_good(self) -> None:
        required = {"compound-engineering", "gstack", "stack-codex", "matt", "david", "emil"}
        providers = {provider["id"]: provider for provider in self.registry["providers"]}
        self.assertEqual(set(providers), required)
        for provider_id, provider in providers.items():
            self.assertTrue(provider["canonical_source"].startswith("https://"))
            self.assertIn(provider["pin"]["type"], {"git-commit", "sha256"})
            self.assertEqual(self.lock["providers"][provider_id], provider["pin"]["value"])
            self.assertEqual(provider["last_known_good"]["pin"], provider["pin"]["value"])
            self.assertTrue(provider["exports"])
            if provider["install"] == "pinned-git-checkout":
                self.assertEqual(set(provider["export_paths"]), set(provider["exports"]))
                self.assertTrue(all(path.endswith("/SKILL.md") and not path.startswith("/") and ".." not in Path(path).parts for path in provider["export_paths"].values()))

    def test_packages_declare_adapters_without_copying_source(self) -> None:
        for package in ("compound-engineering", "gstack", "stack-codex", "imported-skills"):
            manifest = json.loads((ROOT / "packages" / package / "package.json").read_text())
            self.assertFalse(manifest["copy_upstream_source"])
            self.assertEqual(manifest["registry"], "registry/upstreams.json")

    def test_stack_codex_is_complete_bundled_stack_owned_package(self) -> None:
        expected = {
            "orchestrate-parallel-goals",
            "stack-gemini-review",
            "stack-ideate",
            "stack-lfg",
            "stack-mega",
            "stack-review",
            "stack-ship",
            "stack-sync",
        }
        provider = next(item for item in self.registry["providers"] if item["id"] == "stack-codex")
        manifest = json.loads((ROOT / "packages/stack-codex/package.json").read_text())
        self.assertEqual(provider["canonical_source"], "https://github.com/thecolormaroun/stack.git")
        self.assertEqual(provider["pin"]["type"], "sha256")
        self.assertEqual(set(provider["exports"]), expected)
        self.assertEqual(set(manifest["exports"]), expected)
        self.assertTrue(manifest["bundled_stack_owned_source"])
        self.assertEqual(manifest["content_sha256"], provider["pin"]["value"])
        content = ROOT / provider["bundle_path"]
        self.assertEqual({path.parent.name for path in (content / "skills").glob("*/SKILL.md")}, expected)
        self.assertEqual(
            {path.stem for path in (content / "commands").glob("*.md")},
            {"gemini-review", "ideate", "lfg", "mega", "review", "ship", "sync"},
        )
        for relative in ("agents/explorer.toml", "agents/reviewer.toml", "agents/worker.toml", "references/agent-execution-policy.md", "references/frontend-libraries.md", "references/upstreams.md"):
            self.assertTrue((content / relative).is_file(), relative)

    def test_stack_codex_content_digest_matches_pin(self) -> None:
        provider = next(item for item in self.registry["providers"] if item["id"] == "stack-codex")
        directory = ROOT / provider["bundle_path"]
        digest = hashlib.sha256()
        for path in sorted(path for path in directory.rglob("*") if path.is_file()):
            digest.update(path.relative_to(directory).as_posix().encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        self.assertEqual(digest.hexdigest(), provider["pin"]["value"])

    def test_stack_codex_bundle_has_no_machine_specific_user_paths(self) -> None:
        content = (ROOT / "packages/stack-codex/content")
        for path in (path for path in content.rglob("*") if path.is_file()):
            with self.subTest(path=path.relative_to(content)):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("/Users/" + "maroun/", text)
                self.assertNotIn("~/", text)

    def test_stack_codex_exports_have_clean_home_resources_or_fallbacks(self) -> None:
        content = ROOT / "packages/stack-codex/content"
        skills = sorted((content / "skills").glob("*/SKILL.md"))
        self.assertEqual(len(skills), 8)
        combined = "\n".join(path.read_text(encoding="utf-8") for path in content.rglob("*") if path.is_file())
        for forbidden in (
            "CODEX_WORKSPACE",
            "codex-quota-preflight.sh",
            "bootstrap-upstreams.sh",
            "install-claude-stack.sh",
            "install-codex-stack.sh",
            "install-build-skills.sh",
            "gemini-review.sh",
        ):
            self.assertNotIn(forbidden, combined)

        referenced_scripts = set(re.findall(r"scripts/[A-Za-z0-9_.-]+\.(?:py|sh)", combined))
        self.assertEqual(
            referenced_scripts,
            {
                "scripts/bootstrap-stack.py",
                "scripts/stack-doctor.py",
                "scripts/stack-run-state.py",
                "scripts/sync-upstreams.py",
            },
        )
        for relative in referenced_scripts:
            self.assertTrue((ROOT / relative).is_file(), relative)

        for document in [*skills, *sorted((content / "commands").glob("*.md"))]:
            text = document.read_text(encoding="utf-8")
            for relative in re.findall(r"(?:\.\./)+(?:references)/[A-Za-z0-9_.-]+\.md", text):
                self.assertTrue((document.parent / relative).resolve().is_file(), f"{document}: {relative}")
        self.assertTrue((ROOT / "skills/engineering/gemini-review/SKILL.md").is_file())

        with tempfile.TemporaryDirectory() as clean_home:
            environment = os.environ.copy()
            environment["HOME"] = clean_home
            environment.pop("CODEX_HOME", None)
            environment.pop("CODEX_WORKSPACE", None)
            environment.pop("STACK_REPO", None)
            for relative in sorted(referenced_scripts):
                result = subprocess.run(
                    ["python3", relative, "--help"],
                    cwd=ROOT,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, f"{relative}: {result.stderr}")

        policy = (content / "references/agent-execution-policy.md").read_text()
        self.assertIn("tested fail-closed fallback", policy)
        self.assertIn("When the helper is unavailable", policy)

    def test_sync_preflight_fails_closed_for_a_missing_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(["python3", "scripts/sync-upstreams.py", "--check-checkout", "gstack", temporary], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("active outputs must remain last-known-good", result.stderr)

    def test_sync_preflight_verifies_metadata_without_side_effects(self) -> None:
        result = subprocess.run(["python3", "scripts/sync-upstreams.py"], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("extraction and staging may proceed", result.stdout)


if __name__ == "__main__":
    unittest.main()
