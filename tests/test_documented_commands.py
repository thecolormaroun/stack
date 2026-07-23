"""Keep Stack's public governance documentation executable and safe."""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "config/CLAUDE.md",
    ROOT / "docs/architecture.md",
    ROOT / "docs/capability-lifecycle.md",
    ROOT / "docs/bookmark-curation.md",
    ROOT / "docs/runtime-publication.md",
    ROOT / "docs/private-overlay.md",
    ROOT / "templates/periodic-reassessment.md",
)
REFERENCE_PATTERN = re.compile(r"(?<![\w.-])((?:config|docs|registry|scripts|templates|tests)/[A-Za-z0-9_./-]+)")
COMMAND_PATTERN = re.compile(r"^python3 (scripts/[A-Za-z0-9_.-]+\.py)(?:\s|$)", re.MULTILINE)
TEST_COMMAND_PATTERN = re.compile(r"^python3 -m unittest ([A-Za-z0-9_.\s]+)$", re.MULTILINE)


class DocumentedCommandsTests(unittest.TestCase):
    def texts(self) -> str:
        return "\n".join(document.read_text(encoding="utf-8") for document in DOCUMENTS)

    def test_every_documented_repository_reference_resolves(self) -> None:
        for document in DOCUMENTS:
            text = document.read_text(encoding="utf-8")
            for reference in REFERENCE_PATTERN.findall(text):
                with self.subTest(document=document.relative_to(ROOT), reference=reference):
                    self.assertTrue((ROOT / reference.rstrip("/")).exists(), reference)

    def test_every_documented_script_command_is_available(self) -> None:
        for script in set(COMMAND_PATTERN.findall(self.texts())):
            with self.subTest(script=script):
                path = ROOT / script
                self.assertTrue(path.is_file())
                result = subprocess.run(
                    ["python3", str(path), "--help"], cwd=ROOT, text=True,
                    capture_output=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_every_documented_unittest_module_resolves(self) -> None:
        for command in TEST_COMMAND_PATTERN.findall(self.texts()):
            for module in command.split():
                with self.subTest(module=module):
                    self.assertTrue((ROOT / (module.replace(".", "/") + ".py")).is_file())

    def test_core_governance_safety_language_is_not_removed(self) -> None:
        text = self.texts().lower()
        for required in (
            "design and build software",
            "authoritative capability-local manifest",
            "generated",
            "human review",
            "untrusted evidence",
            "private",
            "rollback",
            "no live scheduler",
            "low usage alone never auto-archives",
            "only a reviewed, validated `active` entry",
        ):
            with self.subTest(required=required):
                self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
