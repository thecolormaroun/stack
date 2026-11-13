"""Claude and Codex share one instruction file and one context folder."""
from __future__ import annotations

import os
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "docs/context"
SHARED = (ROOT / "AGENTS.md", CONTEXT / "state.md", CONTEXT / "decisions.md", CONTEXT / "handoff.md")
FORBIDDEN = (
    re.compile(r"/(?:Users|home)/[^/\s`]+"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9-]{20,}|xox[abpr]-[A-Za-z0-9-]{10,})"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
)
DECISION = re.compile(r"^- (\d{4}-\d{2}-\d{2}): .+ \[#\d+\]\(https://github\.com/thecolormaroun/stack/pull/\d+\)$")


class AgentContextTests(unittest.TestCase):
    def test_claude_md_is_a_symlink_to_agents_md(self) -> None:
        claude = ROOT / "CLAUDE.md"
        self.assertTrue(claude.is_symlink(), "CLAUDE.md must be a symlink to AGENTS.md")
        self.assertEqual(os.readlink(claude), "AGENTS.md")
        agents = ROOT / "AGENTS.md"
        self.assertTrue(agents.is_file())
        self.assertFalse(agents.is_symlink(), "AGENTS.md is the source of truth, not a link")
        self.assertFalse((ROOT / "config/CLAUDE.md").exists(), "a second instruction file would drift")

    def test_shared_context_files_exist(self) -> None:
        for path in SHARED:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertTrue(path.is_file(), f"{path.relative_to(ROOT)} is missing")

    def test_agents_md_requires_reading_and_updating_the_context(self) -> None:
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("reads `docs/context/state.md` and `docs/context/handoff.md`", text)
        self.assertIn("before starting work", text)
        self.assertIn("update `state.md` and `handoff.md`", text)
        self.assertIn("No secrets or personal data", text)

    def test_context_files_hold_no_secrets_or_personal_paths(self) -> None:
        for path in SHARED:
            text = path.read_text(encoding="utf-8")
            for pattern in FORBIDDEN:
                with self.subTest(path=path.relative_to(ROOT), pattern=pattern.pattern):
                    self.assertIsNone(pattern.search(text))

    def test_decisions_are_dated_linked_and_in_order(self) -> None:
        lines = [line for line in (CONTEXT / "decisions.md").read_text(encoding="utf-8").splitlines() if line.startswith("- ")]
        self.assertTrue(lines)
        dates = []
        for line in lines:
            with self.subTest(line=line):
                match = DECISION.match(line)
                self.assertIsNotNone(match)
                dates.append(match.group(1))
        self.assertEqual(dates, sorted(dates))

    def test_handoff_names_author_and_date(self) -> None:
        text = (CONTEXT / "handoff.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^- Author: (Claude|Codex)$")
        self.assertRegex(text, r"(?m)^- Date: \d{4}-\d{2}-\d{2}$")
        self.assertIn("## Done", text)
        self.assertIn("## Next", text)


if __name__ == "__main__":
    unittest.main()
