from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / "config" / "weekly-intelligence-automation-prompt.md"
CONFIG = ROOT / "config" / "weekly-intelligence.json"


class WeeklyIntelligenceAutomationPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.prompt_bytes = PROMPT.read_bytes()
        cls.prompt = cls.prompt_bytes.decode("utf-8")
        cls.config = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_preflight_is_first_and_ready_is_required_before_live_workflow(self) -> None:
        gate = "/opt/homebrew/bin/python3.11 -I -B scripts/x_bookmark_infrastructure_status.py weekly-preflight"
        live = "/opt/homebrew/bin/python3.11 -I -B scripts/run-stack-weekly-live.py"

        self.assertIn(gate, self.prompt)
        self.assertIn(live, self.prompt)
        self.assertLess(self.prompt.index(gate), self.prompt.index(live))
        self.assertIn('exits successfully and its JSON result has `"status": "ready"`', self.prompt)
        self.assertIn("Do not invoke `scripts/run-stack-weekly-live.py`", self.prompt)
        self.assertIn("a GBrain mutator or importer", self.prompt)
        self.assertIn("`gbrain_maintenance_active`", self.prompt)
        self.assertIn("leave the separate GBrain task and state untouched", self.prompt)

    def test_live_prompt_forbids_gbrain_mutation_but_allows_read_only_downstream_use(self) -> None:
        self.assertIn("nonmutating with respect to GBrain", self.prompt)
        self.assertIn("must never invoke `scripts/import-bookmark-deltas.py`", self.prompt)
        self.assertIn("read-only GBrain retrieval", self.prompt)
        self.assertNotIn("imports only missing `x-bookmarks` through GBrain", self.prompt)

    def test_prompt_digest_matches_scheduler_contract(self) -> None:
        canonical = self.prompt_bytes[:-1] if self.prompt_bytes.endswith(b"\n") else self.prompt_bytes
        self.assertEqual(
            hashlib.sha256(canonical).hexdigest(),
            self.config["scheduler"]["prompt_digest"],
        )
        self.assertEqual("gpt-5.6-sol", self.config["scheduler"]["model"])
        self.assertEqual("high", self.config["scheduler"]["reasoning_effort"])


if __name__ == "__main__":
    unittest.main()
