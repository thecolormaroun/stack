from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "list_pending_weekly_design_promotions",
    ROOT / "scripts" / "list-pending-weekly-design-promotions.py",
)
assert SPEC and SPEC.loader
PENDING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PENDING)


class ListPendingWeeklyDesignPromotionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.receipts = self.root / "receipts"
        self.decisions = self.root / "decisions"
        self.receipts.mkdir(mode=0o700)
        self.decisions.mkdir(mode=0o700)
        self.run_id = "weekly-fixture"
        self.candidate_digest = "a" * 64

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, directory: Path, name: str, document: dict) -> str:
        path = directory / name
        raw = json.dumps(document).encode("utf-8")
        path.write_bytes(raw)
        path.chmod(0o600)
        return PENDING.hashlib.sha256(raw).hexdigest()

    def write_decision(self, *, run_id: str | None = None, legacy: bool = False) -> str:
        document = self.decision()
        raw = json.dumps(document).encode("utf-8")
        digest = PENDING.hashlib.sha256(raw).hexdigest()
        campaign = run_id or self.run_id
        name = (
            f"{campaign}.json"
            if legacy
            else f"{campaign}--{self.candidate_digest}--{digest}.json"
        )
        self.write(self.decisions, name, document)
        return name

    def write_receipt(self, disposition: str) -> str:
        document = self.receipt(disposition)
        raw = json.dumps(document).encode("utf-8")
        digest = PENDING.hashlib.sha256(raw).hexdigest()
        name = f"{self.run_id}--{self.candidate_digest}--{digest}.json"
        self.write(self.receipts, name, document)
        return name

    def receipt(self, disposition: str) -> dict:
        return {
            "schema_version": 1,
            "receipt_kind": "weekly-design-automatic-promotion",
            "authorization_contract": PENDING.AUTHORIZATION_CONTRACT,
            "disposition": disposition,
            "campaign": {"run_id": self.run_id},
            "candidate": {"state": "selected", "digest": self.candidate_digest},
        }

    def decision(self) -> dict:
        return {
            "authorization_contract": PENDING.AUTHORIZATION_CONTRACT,
            "disposition": "retry_with_alert",
            "candidate": {"state": "selected", "digest": self.candidate_digest},
        }

    def test_retry_is_pending_with_only_safe_decision_filename(self) -> None:
        self.write_receipt("retry_with_alert")
        decision_name = self.write_decision()

        result = PENDING.pending_promotions(self.receipts, self.decisions)

        self.assertEqual("ready", result["status"])
        self.assertEqual(1, result["count"])
        self.assertEqual([decision_name], result["pending"][0]["decision_files"])
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_later_terminal_receipt_closes_the_same_candidate_digest(self) -> None:
        self.write_receipt("retry_with_alert")
        self.write_receipt("published")
        self.write_decision()

        result = PENDING.pending_promotions(self.receipts, self.decisions)

        self.assertEqual("ready", result["status"])
        self.assertEqual([], result["pending"])

    def test_missing_retry_decision_fails_closed(self) -> None:
        self.write_receipt("retry_with_alert")

        result = PENDING.pending_promotions(self.receipts, self.decisions)

        self.assertEqual("blocked", result["status"])
        self.assertEqual(1, len(result["missing_decisions"]))

    def test_wrong_campaign_decision_cannot_satisfy_pending_retry(self) -> None:
        self.write_receipt("retry_with_alert")
        self.write_decision(run_id="weekly-other")

        result = PENDING.pending_promotions(self.receipts, self.decisions)

        self.assertEqual("blocked", result["status"])
        self.assertEqual([], result["pending"][0]["decision_files"])

    def test_legacy_selected_receipt_and_decision_remain_resumable(self) -> None:
        self.write(self.receipts, f"{self.run_id}.json", self.receipt("retry_with_alert"))
        decision_name = self.write_decision(legacy=True)

        result = PENDING.pending_promotions(self.receipts, self.decisions)

        self.assertEqual("ready", result["status"])
        self.assertEqual(1, result["count"])
        self.assertEqual([decision_name], result["pending"][0]["decision_files"])

    def test_legacy_terminal_selected_receipt_is_closed(self) -> None:
        self.write(self.receipts, f"{self.run_id}.json", self.receipt("published"))

        result = PENDING.pending_promotions(self.receipts, self.decisions)

        self.assertEqual("ready", result["status"])
        self.assertEqual([], result["pending"])

    def test_wrong_receipt_filename_fails_closed(self) -> None:
        self.write(self.receipts, "retry.json", self.receipt("retry_with_alert"))

        with self.assertRaisesRegex(PENDING.PendingPromotionError, "filename digest"):
            PENDING.pending_promotions(self.receipts, self.decisions)


if __name__ == "__main__":
    unittest.main()
