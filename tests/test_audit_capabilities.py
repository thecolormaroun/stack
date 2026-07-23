import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/audit-capabilities.py"
SPEC = importlib.util.spec_from_file_location("audit_capabilities", SCRIPT)
AUDIT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(AUDIT)


class CapabilityAuditTests(unittest.TestCase):
    def write_fixture(self, root: Path) -> None:
        (root / "skills/design/references").mkdir(parents=True)
        (root / "skills/finance").mkdir(parents=True)
        (root / "skills/design/SKILL.md").write_text("---\nmetadata: yes\n---\n# Design\n")
        (root / "skills/design/references/source.md").write_text("source pin\n")
        (root / "skills/design/references/guide.md").write_text("guide\n")
        (root / "skills/design/agents").mkdir()
        (root / "skills/design/agents/openai.yaml").write_text("prompt: design\n")
        (root / "skills/design/nested").mkdir()
        (root / "skills/design/nested/SKILL.md").write_text("# Nested\n")
        (root / "skills/finance/SKILL.md").write_text("# Finance helper\n")

    def policy(self, root: Path) -> Path:
        policy = json.loads((ROOT / "config/audit-policy.json").read_text())
        policy["overlap_groups"] = [["skills/design/SKILL.md", "skills/design/nested/SKILL.md"]]
        path = root / "policy.json"
        path.write_text(json.dumps(policy))
        return path

    def test_tree_scan_covers_all_capability_files_and_separates_nested_callables(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_fixture(root)
            report, _ = AUDIT.audit(root, self.policy(root), ROOT / "templates/capability-audit.md")
            self.assertEqual(report["discovery_mode"], "tree-scan")
            self.assertEqual(report["inventory"]["artifact_coverage_percent"], 100)
            self.assertEqual(report["inventory"]["tracked_artifacts"], 6)
            self.assertEqual(report["inventory"]["nested_callable_entrypoints"], 1)
            self.assertEqual(report["inventory"]["capabilities"], 3)
            self.assertEqual(report["callable_entrypoints"], ["skills/design/SKILL.md", "skills/design/nested/SKILL.md", "skills/finance/SKILL.md"])
            finance = next(row for row in report["artifacts"] if row["path"] == "skills/finance/SKILL.md")
            self.assertEqual(finance["proposed_disposition"], "move")
            self.assertEqual(finance["review_state"], "unreviewed")
            design = next(row for row in report["capabilities"] if row["skill_path"] == "skills/design/SKILL.md")
            nested = next(row for row in report["capabilities"] if row["skill_path"] == "skills/design/nested/SKILL.md")
            self.assertNotIn("skills/design/nested/SKILL.md", design["artifact_paths"])
            self.assertIn("skills/design/nested/SKILL.md", nested["artifact_paths"])
            self.assertIn("provenance", design["evidence_locations"])
            self.assertIn("skills/design/references/source.md", design["evidence_locations"]["provenance"])
            self.assertIn("missing-provenance-or-source-pin", nested["evidence_gaps"])
            self.assertNotIn("skills/design/references/source.md", nested["artifact_paths"])

    def test_json_is_deterministic_and_outputs_are_optional(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_fixture(root)
            policy = self.policy(root)
            first = subprocess.run(["python3", str(SCRIPT), "--root", str(root), "--policy", str(policy)], check=True, capture_output=True, text=True).stdout
            second = subprocess.run(["python3", str(SCRIPT), "--root", str(root), "--policy", str(policy)], check=True, capture_output=True, text=True).stdout
            self.assertEqual(first, second)
            output = root / "artifacts/audits/fixture"
            subprocess.run(["python3", str(SCRIPT), "--root", str(root), "--policy", str(policy), "--output-dir", str(output)], check=True)
            self.assertTrue((output / "capability-audit.json").exists())
            self.assertTrue((output / "capability-audit.md").exists())

    def test_git_discovery_includes_nonignored_untracked_capability_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_fixture(root)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "skills/design/SKILL.md"], check=True)
            (root / ".gitignore").write_text("skills/design/ignored.json\n")
            (root / "skills/design/ignored.json").write_text("{}\n")
            (root / "skills/design/capability.json").write_text("{}\n")
            report, _ = AUDIT.audit(root, self.policy(root), ROOT / "templates/capability-audit.md")
            paths = [record["path"] for record in report["artifacts"]]
            self.assertEqual(report["discovery_mode"], "git")
            self.assertIn("skills/design/capability.json", paths)
            self.assertNotIn("skills/design/ignored.json", paths)

    def test_git_discovery_excludes_tracked_files_deleted_in_worktree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_fixture(root)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            tracked = root / "skills/design/SKILL.md"
            subprocess.run(["git", "-C", str(root), "add", tracked.relative_to(root)], check=True)
            tracked.unlink()

            report, _ = AUDIT.audit(root, self.policy(root), ROOT / "templates/capability-audit.md")

            self.assertNotIn("skills/design/SKILL.md", [record["path"] for record in report["artifacts"]])

    def test_missing_evidence_is_explicit_and_overlap_is_not_silently_merged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_fixture(root)
            report, markdown = AUDIT.audit(root, self.policy(root), ROOT / "templates/capability-audit.md")
            nested = next(row for row in report["artifacts"] if row["path"] == "skills/design/nested/SKILL.md")
            self.assertEqual(nested["proposed_disposition"], "merge")
            self.assertIn("missing-runtime-evidence", nested["evidence_gaps"])
            nested_capability = next(row for row in report["capabilities"] if row["skill_path"] == nested["path"])
            self.assertEqual(nested_capability["proposed_disposition"], "merge")
            self.assertIn("unreviewed", markdown)
            self.assertIn("Tracked capability artifacts: 6", markdown)
            self.assertNotIn("{{", markdown)

    def test_incidental_safety_language_does_not_change_product_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "skills/design-review/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: design-review\ndescription: Review software interface implementation.\n---\nNever expose finance or household data.\n")
            report, _ = AUDIT.audit(root, self.policy(root), ROOT / "templates/capability-audit.md")
            record = next(row for row in report["capabilities"] if row["canonical_name"] == "design-review")
            self.assertEqual(record["proposed_disposition"], "keep")
            self.assertNotEqual(next(row for row in report["artifacts"] if row["path"] == "skills/design-review/SKILL.md")["artifact_type"], "router")


if __name__ == "__main__":
    unittest.main()
