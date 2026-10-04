"""Integration and safety coverage for the owner-local weekly adapters."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "weekly_local_adapters.py"
RETRIEVAL_FIXTURE = ROOT / "tests" / "fixtures" / "design-retrieval" / "candidates.json"
EVALUATION_HELPER = ROOT / "tests" / "test_design_intelligence_candidate.py"
BROWSER_HELPER = ROOT / "tests" / "test_design_intelligence_evaluation.py"
WEEKLY_SCRIPT = ROOT / "scripts" / "run-stack-weekly-intelligence.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WeeklyLocalAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.adapters = load_module("weekly_local_adapters_test", SCRIPT)
        cls.query = load_module("weekly_local_adapter_query_fixture", ROOT / "scripts" / "query-design-intelligence.py")

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        os.chmod(self.root, 0o700)
        self.state_dir = self.root / "state"
        self.state_dir.mkdir(mode=0o700)
        os.chmod(self.state_dir, 0o700)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_json(self, name: str, value: object) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        path.write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        os.chmod(path, 0o600)
        return path

    def source_export(self, sentinel: str = "RAW-SENTINEL", *, partial: bool = False) -> dict:
        pages = [{
            "page_ordinal": 0,
            "requested_cursor": None,
            "returned_cursor": "next-page" if partial else None,
            "rows": [{
                "id": "bookmark-1",
                "tweet_id": "tweet-1",
                "url": "https://x.example.invalid/designer/status/1",
                "text": f"{sentinel} dense dashboard table hierarchy and responsive filters",
                "author_handle": "designer",
                "synced_at": "2026-08-23T12:00:00+00:00",
            }],
        }]
        if partial:
            pages.append({
                "page_ordinal": 1,
                "requested_cursor": "next-page",
                "returned_cursor": None,
                "error": {"status": 429, "attempts": 1},
            })
        return {
            "schema_version": 1,
            "source_id": "x-bookmarks",
            "captured_at": "2026-08-23T12:00:00+00:00",
            "pages": pages,
        }

    def target_manifest(self) -> dict:
        return {
            "schema_version": 1,
            "owner_identity": "local-owner:primary",
            "targets": {"codex-local": "local-target:codex-main"},
        }

    def source_grant(self) -> dict:
        return {
            "schema_version": 1,
            "grant_id": "source-grant:" + "f" * 64,
            "owner_identity": "local-owner:primary",
            "source": "x-bookmarks",
            "target_identity": "local-target:codex-main",
            "locator_scopes": ["bookmarks/", "bookmark-"],
            "expires_at": "2027-08-23T12:00:00+00:00",
            "egress_contract": "gbrain-keyword-fts-no-provider-v1",
            "allowed_cli_versions": ["0.42.67.0"],
        }

    def retrieval_request(self) -> dict:
        return {
            "schema_version": 1,
            "request_id": "request:" + "a" * 64,
            "source": "x-bookmarks",
            "target": {
                "name": "codex-local",
                "identity": "local-target:codex-main",
                "owner_identity": "local-owner:primary",
            },
            "context": {
                "project": "stack",
                "repository": "stack",
                "route": "/admin",
                "component": "dashboard",
                "viewport": {"width": 1440, "height": 900},
                "device": "desktop",
                "brief": "dense dashboard table filters side-panel",
                "code": "table filters validation",
                "markup": "dashboard side-panel",
                "screenshot": None,
            },
            "filters": {},
            "freshness": {"as_of": "2026-08-23T12:00:00+00:00", "max_age_days": 14},
            "top_k": 5,
        }

    def config(self, source_path: Path, *, request_path: Path | None = None, target_path: Path | None = None, grant_path: Path | None = None, include_target: bool = True, evaluation: dict | None = None, retrieval_transport: str | None = None) -> Path:
        payload: dict[str, object] = {
            "schema_version": 1,
            "source_document": str(source_path),
        }
        if include_target:
            target_path = target_path or self.write_json("inputs/target-manifest.json", self.target_manifest())
            payload["target_manifest"] = str(target_path)
        if request_path is not None:
            payload["retrieval_request"] = str(request_path)
        if evaluation is not None:
            payload["evaluation"] = evaluation
        if retrieval_transport is not None:
            payload["retrieval_transport"] = retrieval_transport
        if grant_path is not None:
            payload["retrieval_grant"] = str(grant_path)
        return self.write_json("inputs/local-adapter-config.json", payload)

    def snapshot_config(self, snapshot_path: Path, ledger_path: Path) -> Path:
        return self.write_json("inputs/local-adapter-snapshot-config.json", {
            "schema_version": 1,
            "source_snapshot": str(snapshot_path),
            "source_ledger": str(ledger_path),
        })

    def adapter(self, source_path: Path, **kwargs: object):
        return self.adapters.LocalPreparationAdapters(self.config(source_path, **kwargs), self.state_dir)

    def context(self, stage: str) -> dict:
        return {
            "run_id": "local-adapter-run",
            "stage": stage,
            "maintenance": {"status": "linked"},
        }

    def artifact(self, stage: str) -> Path:
        return self.state_dir / "artifacts" / "local-adapter-run" / f"{stage}.json"

    def assert_artifact(self, stage: str, result: dict) -> dict:
        path = self.artifact(stage)
        self.assertTrue(path.is_file(), path)
        self.assertEqual(0o700, stat.S_IMODE(path.parent.stat().st_mode))
        self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
        self.assertEqual(f"artifacts/local-adapter-run/{stage}.json", result["artifact_path"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), result["output_digest"])
        return json.loads(path.read_text(encoding="utf-8"))

    def test_source_to_quarantined_packet_is_real_deterministic_and_redacted(self) -> None:
        source = self.write_json("inputs/source.json", self.source_export())
        adapter = self.adapter(source)

        inputs = adapter.campaign_inputs()
        self.assertEqual("complete", inputs["source_manifest"]["state"])
        self.assertIn("source_document_digest", inputs["source_manifest"])
        self.assertIn("policy_digest", inputs["source_manifest"])
        self.assertIn("retrieval_inputs", inputs["source_manifest"])
        self.assertNotIn(str(self.root), json.dumps(inputs, sort_keys=True))

        source_result = adapter("source_intake", self.context("source_intake"))
        packet_result = adapter("design_packet", self.context("design_packet"))
        self.assertEqual("prepared", source_result["status"])
        self.assertEqual("prepared", packet_result["status"])
        snapshot = self.assert_artifact("source_intake", source_result)
        packet = self.assert_artifact("design_packet", packet_result)
        self.assertEqual("2026-08-23T12:00:00+00:00", snapshot["capture_time"])
        self.assertEqual("complete", snapshot["completeness_state"])
        self.assertTrue(packet["cards"])
        self.assertTrue(all(card["status"] == "quarantined" for card in packet["cards"]))
        self.assertTrue(packet["privacy"]["unapproved_outputs_quarantined"])
        receipt_text = "\n".join(path.read_text(encoding="utf-8") for path in sorted(self.state_dir.rglob("*.json")))
        self.assertNotIn("RAW-SENTINEL", receipt_text)
        self.assertNotIn(str(self.root), receipt_text)

        self.assertEqual(source_result, adapter("source_intake", self.context("source_intake")))
        self.assertEqual(packet_result, adapter("design_packet", self.context("design_packet")))

    def test_sealed_snapshot_and_ledger_reuse_real_reconciliation_outputs(self) -> None:
        corpus = load_module(
            "weekly_local_adapter_corpus_fixture",
            ROOT / "scripts" / "bookmark_private_corpus.py",
        )
        snapshot, raw_records = corpus.reconcile_pages(
            self.source_export(),
            {"schema_version": 1, "network": "deny"},
        )
        snapshot_path = self.write_json("inputs/source-snapshot.json", snapshot)
        ledger_path = self.root / "inputs" / "source-ledger.sqlite3"
        corpus.store_owner_records(ledger_path, raw_records)
        os.chmod(ledger_path, 0o600)

        adapter = self.adapters.LocalPreparationAdapters(
            self.snapshot_config(snapshot_path, ledger_path),
            self.state_dir,
        )
        inputs = adapter.campaign_inputs()
        packet_result = adapter("design_packet", self.context("design_packet"))

        self.assertEqual("complete", inputs["source_manifest"]["state"])
        self.assertEqual("prepared", packet_result["status"])
        packet = self.assert_artifact("design_packet", packet_result)
        self.assertTrue(packet["cards"])
        self.assertNotIn("RAW-SENTINEL", json.dumps(packet, sort_keys=True))

    def test_partial_source_persists_safe_evidence_and_blocks(self) -> None:
        source = self.write_json("inputs/source.json", self.source_export(partial=True))
        result = self.adapter(source)("source_intake", self.context("source_intake"))
        self.assertEqual("blocked", result["status"])
        self.assertEqual("source_snapshot_incomplete", result["reason_code"])
        snapshot = self.assert_artifact("source_intake", result)
        self.assertEqual("partial", snapshot["completeness_state"])

    def test_legacy_snapshot_ledger_remains_readable_after_content_identity_upgrade(self) -> None:
        corpus = load_module("weekly_legacy_corpus_fixture", ROOT / "scripts" / "bookmark_private_corpus.py")
        snapshot, records = corpus.reconcile_pages(self.source_export(), {"schema_version": 1, "network": "deny"})
        for index, record in enumerate(records):
            public, legacy = corpus.normalize_observation(record["row"], record["source_id"], snapshot["snapshot_id"],
                evidence_identity_contract="source-revision-v1")
            public["derivation"].pop("evidence_identity_contract")
            snapshot["observations"][index] = public
            records[index] = legacy
        ledger = self.root / "inputs" / "legacy.sqlite3"
        corpus.store_owner_records(ledger, records)
        legacy_bytes = ledger.read_bytes()
        snapshot_path = self.write_json("inputs/legacy-snapshot.json", snapshot)
        adapter = self.adapters.LocalPreparationAdapters(self.snapshot_config(snapshot_path, ledger), self.state_dir)
        self.assertEqual(adapter("design_packet", self.context("design_packet"))["status"], "prepared")
        self.assertEqual(ledger.read_bytes(), legacy_bytes)
        # An unrecognized contract must never silently select a weaker ID.
        snapshot["observations"][0]["derivation"]["evidence_identity_contract"] = "unknown"
        snapshot_path = self.write_json("inputs/legacy-snapshot.json", snapshot)
        adapter = self.adapters.LocalPreparationAdapters(self.snapshot_config(snapshot_path, ledger), self.state_dir)
        self.assertEqual(adapter("design_packet", self.context("design_packet"))["reason_code"], "source_ledger_mismatch")

    def test_missing_retrieval_prerequisite_stops_after_two_real_artifacts(self) -> None:
        source = self.write_json("inputs/source.json", self.source_export())
        adapter = self.adapter(source)
        adapter("source_intake", self.context("source_intake"))
        adapter("design_packet", self.context("design_packet"))
        result = adapter("retrieval", self.context("retrieval"))
        self.assertEqual({"status": "blocked", "reason_code": "retrieval_request_missing"}, result)
        self.assertEqual(
            {"source_intake.json", "design_packet.json"},
            {path.name for path in (self.state_dir / "artifacts" / "local-adapter-run").glob("*.json")},
        )

    def test_programmatic_offline_transport_uses_real_retrieval_without_claiming_live(self) -> None:
        source = self.write_json("inputs/source.json", self.source_export())
        request = self.write_json("inputs/request.json", self.retrieval_request())
        config = self.config(source, request_path=request)
        candidates = json.loads(RETRIEVAL_FIXTURE.read_text(encoding="utf-8"))
        transport = self.query.FixtureFileTransport(candidates)
        adapter = self.adapters.LocalPreparationAdapters(config, self.state_dir, transport=transport)
        result = adapter("retrieval", self.context("retrieval"))
        self.assertEqual("prepared", result["status"])
        response = self.assert_artifact("retrieval", result)
        self.assertEqual("complete", response["status"])
        self.assertEqual("programmatic_offline", response["adapter_transport"]["mode"])
        self.assertFalse(response["adapter_transport"]["live"])

    def test_live_config_constructs_real_cli_transport_and_marks_receipt_live(self) -> None:
        source = self.write_json("inputs/source.json", self.source_export())
        request = self.write_json("inputs/request.json", self.retrieval_request())
        config = self.config(
            source,
            request_path=request,
            grant_path=self.write_json("inputs/source-grant.json", self.source_grant()),
            retrieval_transport="live-gbrain-text-v1",
        )
        constructed = self.adapters.LocalPreparationAdapters(config, self.state_dir)
        self.assertIsInstance(constructed._transport, constructed._query.CliGBrainTransport)
        self.assertTrue(constructed._transport.live)

        candidates = json.loads(RETRIEVAL_FIXTURE.read_text(encoding="utf-8"))
        injected = self.adapters.LocalPreparationAdapters(
            config,
            self.state_dir,
            transport=self.query.FixtureFileTransport(candidates),
        )
        result = injected("retrieval", self.context("retrieval"))
        response = self.assert_artifact("retrieval", result)
        self.assertEqual("live-gbrain-text-v1", response["adapter_transport"]["mode"])
        self.assertTrue(response["adapter_transport"]["live"])

    def test_live_source_attestation_and_freshness_date_are_campaign_inputs(self) -> None:
        source = self.write_json("inputs/source.json", self.source_export())
        request = self.write_json("inputs/request.json", self.retrieval_request())
        grant = self.write_json("inputs/source-grant.json", self.source_grant())
        config = self.config(
            source,
            request_path=request,
            grant_path=grant,
            retrieval_transport="live-gbrain-text-v1",
        )

        class AttestedTransport:
            def __init__(self, index_version: str) -> None:
                self.index_version = index_version
                self.as_of = None

            def campaign_attestation(self, request, **_kwargs):
                self.as_of = request["freshness"]["as_of"]
                material = {
                    "state": "complete",
                    "reason_code": None,
                    "source": "x-bookmarks",
                    "target_manifest_digest": "a" * 64,
                    "source_grant_digest": "b" * 64,
                    "index_version": self.index_version,
                    "model_version": "gbrain-cli:0.42.67.0",
                    "source_freshness_at": "2026-08-29T12:00:00+00:00",
                    "egress_contract": "gbrain-keyword-fts-no-provider-v1",
                    "provider_calls": 0,
                    "attestation_digest": hashlib.sha256(self.index_version.encode()).hexdigest(),
                }
                return material

        first_transport = AttestedTransport("gbrain:x-bookmarks:index-a:pages-4")
        first = self.adapters.LocalPreparationAdapters(
            config, self.state_dir, transport=first_transport, as_of="2026-08-29T18:00:00+00:00",
        ).campaign_inputs()
        second = self.adapters.LocalPreparationAdapters(
            config,
            self.state_dir,
            transport=AttestedTransport("gbrain:x-bookmarks:index-b:pages-5"),
            as_of="2026-08-29T18:00:00+00:00",
        ).campaign_inputs()

        self.assertEqual("2026-08-29T18:00:00+00:00", first_transport.as_of)
        self.assertEqual("2026-08-29", first["source_manifest"]["retrieval_inputs"]["freshness_date"])
        self.assertNotEqual(
            first["source_manifest"]["retrieval_inputs"]["live_source_attestation"]["attestation_digest"],
            second["source_manifest"]["retrieval_inputs"]["live_source_attestation"]["attestation_digest"],
        )
        self.assertEqual("local-cli-read-only", first["model_config"]["execution"])
        self.assertEqual("local-subprocess-only", first["model_config"]["network"])
        self.assertEqual(0, first["model_config"]["provider_calls"])

    def test_missing_target_manifest_is_late_bound_to_retrieval(self) -> None:
        source = self.write_json("inputs/source.json", self.source_export())
        request = self.write_json("inputs/request.json", self.retrieval_request())
        config = self.config(source, request_path=request, include_target=False)
        adapter = self.adapters.LocalPreparationAdapters(config, self.state_dir)
        self.assertEqual(
            {"status": "blocked", "reason_code": "target_manifest_missing"},
            adapter("retrieval", self.context("retrieval")),
        )

    def test_missing_selected_candidate_is_an_explicit_quarantined_noop(self) -> None:
        source = self.write_json("inputs/source.json", self.source_export())
        result = self.adapter(source)("candidate_evaluation", self.context("candidate_evaluation"))
        self.assertEqual("prepared", result["status"])
        receipt = self.assert_artifact("candidate_evaluation", result)
        self.assertEqual("no_candidate_selected", receipt["status"])
        self.assertEqual("no_material_candidate_selected", receipt["reason_code"])
        self.assertEqual("not_run", receipt["evaluation"])
        self.assertEqual("prohibited", receipt["promotion"])

    def test_selected_candidate_with_incomplete_harness_is_not_a_noop(self) -> None:
        source = self.write_json("inputs/source.json", self.source_export())
        for evaluation in ({}, {"packet": "/unavailable/candidate.json"}):
            with self.subTest(evaluation=evaluation):
                adapter = self.adapter(source, evaluation=evaluation)
                self.assertEqual("incomplete", adapter.campaign_inputs()["eval_config"]["state"])
                result = adapter("candidate_evaluation", self.context("candidate_evaluation"))
                self.assertEqual("blocked", result["status"])
                self.assertEqual("candidate_evaluation_inputs_incomplete", result["reason_code"])
                self.assertFalse(self.artifact("candidate_evaluation").exists())

    def test_existing_candidate_harness_does_not_accept_claimed_real_feedback(self) -> None:
        helper_module = load_module("weekly_local_adapter_evaluation_fixture", EVALUATION_HELPER)
        fixture = helper_module.DesignIntelligenceCandidateTests("runTest")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        packet_path = fixture.root / "candidate-packet.json"
        materialization_path = fixture.root / "materialization-receipt.json"
        packet_path.write_bytes(json.dumps(fixture.packet, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        materialization_path.write_bytes(json.dumps(fixture.materialization, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        os.chmod(packet_path, 0o600)
        os.chmod(materialization_path, 0o600)
        results = fixture.results()
        source = self.write_json("inputs/source.json", self.source_export())
        evaluation = {
            "packet": str(packet_path),
            "materialization_receipt": str(materialization_path),
            "harness_root": str(fixture.harness),
            "manifests": {name: str(path) for name, path in fixture.manifests.items()},
            "results": {name: str(path) for name, path in results.items()},
        }
        result = self.adapter(source, evaluation=evaluation)("candidate_evaluation", self.context("candidate_evaluation"))
        self.assertEqual("blocked", result["status"])
        self.assertEqual("candidate_evaluation_human_review_required", result["reason_code"])
        receipt = self.assert_artifact("candidate_evaluation", result)
        self.assertEqual("human_review_required", receipt["status"])
        self.assertIn("unverified_task_usefulness_feedback", receipt["reason_codes"])
        self.assertEqual(0, receipt["metrics"]["real_task_usefulness_feedback_count"])
        self.assertFalse(receipt["activation"]["publish"])
        self.assertFalse(receipt["activation"]["install"])

    def test_permissions_symlinks_and_stack_paths_fail_closed(self) -> None:
        source = self.write_json("inputs/source.json", self.source_export())
        config = self.config(source)
        os.chmod(source, 0o644)
        with self.assertRaises(self.adapters.LocalAdapterError) as permissions:
            self.adapters.LocalPreparationAdapters(config, self.state_dir)
        self.assertEqual("owner_local_file_permissions_invalid", permissions.exception.code)

        source = self.write_json("inputs/source-private.json", self.source_export())
        source_link = self.root / "inputs" / "source-link.json"
        source_link.symlink_to(source)
        with self.assertRaises(self.adapters.LocalAdapterError) as symlink:
            self.adapters.LocalPreparationAdapters(self.config(source_link), self.state_dir)
        self.assertEqual("owner_local_symlink_detected", symlink.exception.code)

        with self.assertRaises(self.adapters.LocalAdapterError) as repository:
            self.adapters.LocalPreparationAdapters(self.config(ROOT / "scripts" / "bookmark_private_corpus.py"), self.state_dir)
        self.assertEqual("owner_local_path_in_stack", repository.exception.code)

    def test_same_source_path_with_new_bytes_changes_fingerprint(self) -> None:
        source = self.write_json("inputs/source.json", self.source_export("RAW-SENTINEL-ONE"))
        first = self.adapter(source).campaign_inputs()
        self.write_json("inputs/source.json", self.source_export("RAW-SENTINEL-TWO"))
        second = self.adapter(source).campaign_inputs()
        self.assertNotEqual(first["source_manifest"]["source_document_digest"], second["source_manifest"]["source_document_digest"])
        self.assertNotEqual(first["source_delta"]["digest"], second["source_delta"]["digest"])

    def test_first_run_creates_only_the_private_state_leaf_and_pins_capture_fallback(self) -> None:
        parent = self.root / "state-parent"
        parent.mkdir(mode=0o700)
        os.chmod(parent, 0o700)
        fresh_state = parent / "campaign"
        source_doc = self.source_export()
        row = source_doc["pages"][0]["rows"][0]
        row.pop("synced_at")
        row["posted_at"] = "2026-08-19T12:00:00+00:00"
        row["revision_at"] = "2026-08-22T12:00:00+00:00"
        source = self.write_json("inputs/source.json", source_doc)
        adapter = self.adapters.LocalPreparationAdapters(self.config(source), fresh_state)
        self.assertTrue(fresh_state.is_dir())
        self.assertEqual(0o700, stat.S_IMODE(fresh_state.stat().st_mode))
        result = adapter("source_intake", self.context("source_intake"))
        snapshot = self.assert_artifact_from(fresh_state, "source_intake", result)
        self.assertEqual(source_doc["captured_at"], snapshot["observations"][0]["capture_time"])
        self.assertEqual(row["revision_at"], snapshot["observations"][0]["revision_time"])

    def assert_artifact_from(self, state_dir: Path, stage: str, result: dict) -> dict:
        path = state_dir / "artifacts" / "local-adapter-run" / f"{stage}.json"
        self.assertTrue(path.is_file(), path)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), result["output_digest"])
        return json.loads(path.read_text(encoding="utf-8"))


class WeeklyBrowserEvidenceTests(unittest.TestCase):
    """Real adapter/collector/store chain; only browser commands are simulated."""

    def setUp(self) -> None:
        self.local = WeeklyLocalAdapterTests("runTest")
        self.local.setUpClass()
        self.local.setUp()
        self.addCleanup(self.local.tearDown)
        helper = load_module("weekly_browser_candidate_fixture", EVALUATION_HELPER)
        self.fixture = helper.DesignIntelligenceCandidateTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        browser_helper = load_module("weekly_browser_command_fixture", BROWSER_HELPER)
        self.fake = browser_helper.FakeBrowser()
        self.overflow = 0
        self.failed_workflow_variant: str | None = None
        self.error_variant: str | None = None
        self.active_variant: str | None = None
        self.variant_opens: list[str] = []
        self.weekly = load_module("weekly_browser_test_weekly_coordinator", WEEKLY_SCRIPT)
        self.now = 1_788_268_800.0
        self.maintenance = {
            "schema_version": 1,
            "task_id": "stack-maintenance",
            "run_id": "fixture-maintenance",
            "mode": "audit",
            "manual_audit": False,
            "observed_at": self.weekly._now_iso(self.now - 60),
            "input_fingerprint": "c" * 64,
            "provider_refs": [],
            "catalog_digest": "d" * 64,
            "policy_digest": "e" * 64,
            "changed_paths_digest": "f" * 64,
            "checks": {"fixture_only": True},
            **{key: {"status": "fixture_only"} for key in (
                "checkout_state", "pr_state", "approval_state", "cleanup_state", "thread_state"
            )},
            "terminal_classification": "no_action",
            "receipt_persisted": True,
        }
        self.source = self.local.write_json("inputs/source.json", self.local.source_export())
        self.evaluation = {
            "packet": str(self.local.write_json("inputs/packet.json", self.fixture.packet)),
            "materialization_receipt": str(self.local.write_json("inputs/materialization.json", self.fixture.materialization)),
            "harness_root": str(self.fixture.harness),
            "manifests": {name: str(path) for name, path in self.fixture.manifests.items()},
        }
        self.browser_path = self.local.root / "inputs" / "fake-browser"
        self.browser_path.write_bytes(b"fixture executable; commands injected\n")
        self.browser_path.chmod(0o700)
        cases = []
        for manifest_path in self.fixture.manifests.values():
            for fixture in json.loads(manifest_path.read_bytes())["fixtures"]:
                identity = fixture["id"]
                assets = {}
                for variant, text in (("task", "Complete the synthetic task."), ("baseline", "Continue"), ("candidate", "Updated")):
                    payload = text if variant == "task" else f'<main><button id="continue">{text}</button><p id="result">Complete</p></main>'
                    path = self.local.root / "inputs" / f"{identity}-{variant}.{'md' if variant == 'task' else 'html'}"
                    path.write_text(payload)
                    path.chmod(0o600)
                    assets[variant] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                cases.append({
                    "case_id": identity, "task_asset": assets["task"],
                    "viewport": {"width": 1280, "height": 800},
                    "variants": {name: {"html": assets[name], "assets": []} for name in ("baseline", "candidate")},
                    "primary_workflow": [{"action": "click", "selector": "#continue", "assertions": [{"kind": "visible", "selector": "#result"}]}],
                })
        self.manifest = {
            "schema_version": 1, "run_id": "weekly-browser-test", "content_scope": "synthetic_non_private",
            "offline_asset_policy": "self-contained-data-url-csp-and-abort-external-requests",
            "browser": {"executable": str(self.browser_path), "arguments": []}, "cases": cases,
        }
        self.pin_manifest()
        self.collector = self.local.adapters._load_fixed_module("weekly_browser_test_collector", "run-design-intelligence-evaluation.py")
        allowlist = patch.object(self.collector, "ALLOWED_BROWSER_EXECUTABLES", {str(self.browser_path)})
        allowlist.start()
        self.addCleanup(allowlist.stop)
        original_load = self.local.adapters._load_fixed_module
        loader = patch.object(self.local.adapters, "_load_fixed_module", side_effect=lambda name, filename:
            self.collector if filename == "run-design-intelligence-evaluation.py" else original_load(name, filename))
        loader.start()
        self.addCleanup(loader.stop)
        actual_run = self.collector.run_evaluation
        runner = patch.object(self.collector, "run_evaluation", side_effect=lambda *args, **kwargs:
            actual_run(*args, **kwargs, command_runner=self.command))
        runner.start()
        self.addCleanup(runner.stop)

    def pin_manifest(self) -> None:
        path = self.local.write_json("inputs/browser-manifest.json", self.manifest)
        self.evaluation["browser_collection"] = {
            "manifest": str(path), "reviewed_manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "candidate_packet_digest": self.local.adapters._digest_json(self.fixture.packet),
            "materialization_receipt_digest": self.local.adapters._digest_json(self.fixture.materialization),
        }

    def adapter(self):
        return self.local.adapter(self.source, evaluation=self.evaluation)

    def command(self, argv, **kwargs):
        result = self.fake(argv, **kwargs)
        command = tuple(argv[argv.index("--session") + 2:])
        if len(command) == 2 and command[0] == "open" and command[1].startswith("data:"):
            page = base64.b64decode(command[1].split(",", 1)[1])
            self.active_variant = "candidate" if b"Updated" in page else "baseline"
            self.variant_opens.append(self.active_variant)
        if command[:2] == ("is", "visible") and self.failed_workflow_variant == self.active_variant:
            result.stdout = b"false"
        if command == ("errors", "--clear") and self.error_variant == self.active_variant:
            result.stdout = b"Uncaught Error: synthetic page failure\n"
        if command[0] == "eval":
            measurement = json.loads(result.stdout)
            measurement["scroll_width"] = measurement["viewport_width"] + self.overflow
            result.stdout = json.dumps(measurement).encode()
        return result

    def coordinator_run(self, evaluation: dict | None = None, *, run_id: str | None = None, resume: bool = False) -> dict:
        request = self.local.retrieval_request()
        request["freshness"]["as_of"] = self.weekly._now_iso(self.now)
        request_path = self.local.write_json("inputs/weekly-request.json", request)
        config = self.local.config(
            self.source,
            request_path=request_path,
            evaluation=evaluation or self.evaluation,
        )
        candidates = json.loads(RETRIEVAL_FIXTURE.read_text(encoding="utf-8"))
        adapter = self.local.adapters.LocalPreparationAdapters(
            config,
            self.local.state_dir,
            transport=self.local.query.FixtureFileTransport(candidates),
            as_of=self.weekly._now_iso(self.now),
        )
        inputs = adapter.campaign_inputs()
        inputs["maintenance_receipt"] = self.maintenance
        coordinator = self.weekly.WeeklyIntelligenceCoordinator(
            state_dir=self.local.state_dir,
            adapters=adapter,
            now=self.now,
        )
        return coordinator.run(inputs, run_id=run_id, resume=resume)

    def test_collects_without_scores_and_repeat_does_not_replay_browser(self) -> None:
        adapter = self.adapter()
        result = adapter("candidate_evaluation", self.local.context("candidate_evaluation"))
        self.assertEqual("candidate_evaluation_results_pending", result["reason_code"])
        summary = self.local.assert_artifact("browser_collection", result)
        self.assertEqual("evidence_collected", summary["status"])
        self.assertEqual("not_evaluated", summary["evaluation_status"])
        self.assertEqual("pending", summary["human_task_usefulness"])
        self.assertEqual("unverified", summary["candidate_render_binding_status"])
        self.assertNotIn("candidate_failures_observed", summary)
        self.assertEqual(
            "artifacts/browser-evidence-" + summary["collection_binding_digest"] + "/run-receipt.json",
            summary["collector_receipt_path"],
        )
        self.assertNotIn(str(self.local.root), json.dumps(summary))
        self.assertFalse(self.local.artifact("candidate_evaluation").exists())
        count = len(self.fake.calls)
        self.assertEqual(result, adapter("candidate_evaluation", self.local.context("candidate_evaluation")))
        self.assertEqual(count, len(self.fake.calls))

    def test_wrong_candidate_or_frozen_cases_fail_before_browser(self) -> None:
        self.evaluation["browser_collection"]["candidate_packet_digest"] = "0" * 64
        with self.assertRaisesRegex(self.local.adapters.LocalAdapterError, "browser_collection_candidate_binding_invalid"):
            self.adapter()
        self.assertEqual([], self.fake.calls)

    def test_private_content_or_unfrozen_cases_are_rejected(self) -> None:
        self.manifest["content_scope"] = "private"
        self.pin_manifest()
        with self.assertRaisesRegex(self.local.adapters.LocalAdapterError, "browser_collection_manifest_invalid"):
            self.adapter()
        self.assertEqual([], self.fake.calls)

    def test_objective_failure_blocks_even_before_scores_arrive(self) -> None:
        self.overflow = 16
        result = self.adapter()("candidate_evaluation", self.local.context("candidate_evaluation"))
        self.assertEqual("candidate_evaluation_objective_failure", result["reason_code"])
        self.assertTrue(self.local.assert_artifact("browser_collection", result)["objective_candidate_failure"])

    def test_candidate_page_errors_block_without_scores(self) -> None:
        self.error_variant = "candidate"
        result = self.adapter()("candidate_evaluation", self.local.context("candidate_evaluation"))
        self.assertEqual("candidate_evaluation_objective_failure", result["reason_code"])
        self.assertTrue(self.local.assert_artifact("browser_collection", result)["objective_candidate_failure"])

    def test_candidate_page_errors_block_with_complete_scores(self) -> None:
        self.error_variant = "candidate"
        self.evaluation["results"] = {name: str(path) for name, path in self.fixture.results().items()}
        result = self.adapter()("candidate_evaluation", self.local.context("candidate_evaluation"))
        self.assertEqual("candidate_evaluation_objective_failure", result["reason_code"])
        self.assertFalse(self.local.artifact("candidate_evaluation").exists())

    def test_candidate_workflow_failure_blocks_without_scores(self) -> None:
        self.failed_workflow_variant = "candidate"
        result = self.adapter()("candidate_evaluation", self.local.context("candidate_evaluation"))
        self.assertEqual("candidate_evaluation_objective_failure", result["reason_code"])
        self.assertTrue(self.local.assert_artifact("browser_collection", result)["objective_candidate_failure"])

    def test_candidate_workflow_failure_blocks_with_complete_scores(self) -> None:
        self.failed_workflow_variant = "candidate"
        self.evaluation["results"] = {name: str(path) for name, path in self.fixture.results().items()}
        result = self.adapter()("candidate_evaluation", self.local.context("candidate_evaluation"))
        self.assertEqual("candidate_evaluation_objective_failure", result["reason_code"])
        self.assertFalse(self.local.artifact("candidate_evaluation").exists())

    def test_baseline_workflow_failure_is_retained_as_comparison_evidence(self) -> None:
        self.failed_workflow_variant = "baseline"
        result = self.adapter()("candidate_evaluation", self.local.context("candidate_evaluation"))
        self.assertEqual("candidate_evaluation_results_pending", result["reason_code"])
        summary = self.local.assert_artifact("browser_collection", result)
        self.assertEqual("blocked", summary["status"])
        self.assertEqual("baseline_workflow_failure_only", summary["collection_validation"])
        self.assertNotIn("objective_candidate_failure", summary)

    def test_complete_scores_must_bind_collected_receipt(self) -> None:
        self.evaluation["results"] = {name: str(path) for name, path in self.fixture.results().items()}
        result = self.adapter()("candidate_evaluation", self.local.context("candidate_evaluation"))
        self.assertEqual("candidate_evaluation_browser_binding_invalid", result["reason_code"])

    def test_bound_synthetic_scores_stop_at_missing_renderer_gate(self) -> None:
        pending = self.adapter()("candidate_evaluation", self.local.context("candidate_evaluation"))
        digest = self.local.assert_artifact("browser_collection", pending)["collector_receipt_digest"]
        results = self.fixture.results(feedback={"kind": "synthetic", "text": "Fixture feedback, not human task use."})
        for path in results.values():
            value = json.loads(path.read_bytes())
            value["browser_evidence_digest"] = digest
            path.write_text(json.dumps(value))
        self.evaluation["results"] = {name: str(path) for name, path in results.items()}
        count = len(self.fake.calls)
        adapter = self.adapter()
        evaluator = patch.object(
            adapter._evaluator,
            "evaluate_design_candidate",
            side_effect=AssertionError("unverified render reached evaluator"),
        )
        evaluator.start()
        self.addCleanup(evaluator.stop)
        result = adapter("candidate_evaluation", self.local.context("candidate_evaluation"))
        self.assertEqual("candidate_evaluation_render_binding_unavailable", result["reason_code"])
        self.assertFalse(self.local.artifact("candidate_evaluation").exists())
        link = self.local.assert_artifact("browser_collection", result)
        self.assertEqual(digest, link["collector_receipt_digest"])
        self.assertEqual("unverified", link["candidate_render_binding_status"])
        self.assertNotIn("candidate_failures_observed", link)
        self.assertEqual(count, len(self.fake.calls))

    def test_missing_primary_workflow_is_not_quality_evidence(self) -> None:
        self.manifest["cases"][0].pop("primary_workflow")
        self.pin_manifest()
        with self.assertRaisesRegex(self.local.adapters.LocalAdapterError, "browser_collection_primary_workflow_required"):
            self.adapter()
        self.assertEqual([], self.fake.calls)

    def test_frozen_case_coverage_and_workflows_fail_closed(self) -> None:
        self.manifest["cases"].pop()
        self.pin_manifest()
        with self.assertRaisesRegex(self.local.adapters.LocalAdapterError, "browser_collection_frozen_cases_mismatch"):
            self.adapter()
        self.assertEqual([], self.fake.calls)

    def test_overlapping_frozen_split_ids_are_rejected(self) -> None:
        packet = json.loads(json.dumps(self.fixture.packet))
        manifests = {name: json.loads(path.read_text()) for name, path in self.fixture.manifests.items()}
        manifests["holdout"]["fixtures"][0]["id"] = manifests["development"]["fixtures"][0]["id"]
        paths = dict(self.fixture.manifests)
        paths["holdout"] = self.local.write_json("inputs/overlap-holdout.json", manifests["holdout"])
        packet["evaluation"]["holdout_manifest_digest"] = hashlib.sha256(paths["holdout"].read_bytes()).hexdigest()
        packet_path = self.local.write_json("inputs/overlap-packet.json", packet)
        materialization = dict(self.fixture.materialization)
        evaluator = self.local.adapters._load_fixed_module(
            "weekly_overlap_candidate_evaluator",
            "evaluate-design-intelligence-candidate.py",
        )
        materialization["change_digest"] = evaluator.digest_json(packet)
        materialization_path = self.local.write_json("inputs/overlap-materialization.json", materialization)
        self.evaluation.update({
            "packet": str(packet_path),
            "materialization_receipt": str(materialization_path),
            "manifests": {name: str(path) for name, path in paths.items()},
        })
        self.evaluation["browser_collection"]["candidate_packet_digest"] = self.local.adapters._digest_json(packet)
        self.evaluation["browser_collection"]["materialization_receipt_digest"] = self.local.adapters._digest_json(materialization)
        with self.assertRaisesRegex(self.local.adapters.LocalAdapterError, "browser_collection_frozen_splits_overlap"):
            self.adapter()
        self.assertEqual([], self.fake.calls)

    def test_browser_digest_drift_blocks_without_commands(self) -> None:
        adapter = self.adapter()
        self.browser_path.write_bytes(b"changed fixture executable\n")
        result = adapter("candidate_evaluation", self.local.context("candidate_evaluation"))
        self.assertEqual("browser_collection_execution_drift", result["reason_code"])
        self.assertEqual([], self.fake.calls)

    def test_parent_lease_loss_stops_before_browser(self) -> None:
        adapter = self.adapter()
        def lost():
            raise RuntimeError("credential-like-error-must-not-escape")
        result = adapter("candidate_evaluation", {**self.local.context("candidate_evaluation"), "renew_lease": lost})
        self.assertEqual("parent_workflow_lease_lost", result["reason_code"])
        self.assertNotIn("credential-like", json.dumps(result))
        self.assertEqual([], self.fake.calls)

    def test_parent_lease_loss_after_verified_variant_resumes_without_replay(self) -> None:
        adapter = self.adapter()
        output_roots: list[Path] = []

        def lose_after_evidence_checkpoint() -> None:
            roots = list((self.local.state_dir / "artifacts").glob("browser-evidence-*"))
            output_roots[:] = roots
            if not roots:
                return
            store = self.collector._run_state.WorkflowStore(roots[0] / "workflow.sqlite3")
            try:
                snapshot = store.snapshot(self.manifest["run_id"])
            finally:
                store.close()
            if any(row["kind"] == "evidence" for row in self.collector._checkpoint_rows(snapshot)):
                raise RuntimeError("parent lease lost after verified checkpoint")

        first = adapter("candidate_evaluation", {
            **self.local.context("candidate_evaluation"),
            "renew_lease": lose_after_evidence_checkpoint,
        })
        self.assertEqual("parent_workflow_lease_lost", first["reason_code"])
        self.assertEqual(1, len(output_roots))
        store = self.collector._run_state.WorkflowStore(output_roots[0] / "workflow.sqlite3")
        try:
            snapshot = store.snapshot(self.manifest["run_id"])
        finally:
            store.close()
        checkpoints = self.collector._checkpoint_rows(snapshot)
        self.assertEqual(1, sum(row["kind"] == "evidence" for row in checkpoints))
        self.assertEqual(["baseline"], self.variant_opens)

        resumed = adapter("candidate_evaluation", self.local.context("candidate_evaluation"))
        self.assertEqual("candidate_evaluation_results_pending", resumed["reason_code"])
        self.assertEqual(len(self.manifest["cases"]), self.variant_opens.count("baseline"))
        self.assertEqual(len(self.manifest["cases"]), self.variant_opens.count("candidate"))

    def test_coordinator_missing_partial_then_complete_scores_reuses_collection(self) -> None:
        missing = self.coordinator_run()
        self.assertEqual("candidate_evaluation_results_pending", missing["reason_code"])
        self.assertEqual(0, missing["circuit"]["strike_count"])
        missing_link_path = self.local.state_dir / missing["stages"][3]["artifact_path"]
        missing_link = json.loads(missing_link_path.read_text())
        receipt_digest = missing_link["collector_receipt_digest"]
        collection_path = self.local.state_dir / missing_link["collector_receipt_path"]
        self.assertTrue(collection_path.is_file())
        self.assertEqual(
            receipt_digest,
            self.local.adapters._digest_json(json.loads(collection_path.read_text())),
        )
        first_calls = len(self.fake.calls)

        results = self.fixture.results(feedback={"kind": "synthetic", "text": "Fixture feedback, not human task use."})
        for path in results.values():
            value = json.loads(path.read_bytes())
            value["browser_evidence_digest"] = receipt_digest
            path.write_text(json.dumps(value))
            path.chmod(0o600)
        partial_evaluation = {**self.evaluation, "results": {"development": str(results["development"])}}
        partial = self.coordinator_run(partial_evaluation)
        self.assertNotEqual(missing["run_id"], partial["run_id"])
        self.assertEqual("candidate_evaluation_results_pending", partial["reason_code"])
        self.assertEqual(0, partial["circuit"]["strike_count"])
        self.assertEqual(first_calls, len(self.fake.calls))

        complete_evaluation = {**self.evaluation, "results": {name: str(path) for name, path in results.items()}}
        complete = self.coordinator_run(complete_evaluation)
        self.assertNotEqual(partial["run_id"], complete["run_id"])
        self.assertEqual("candidate_evaluation_render_binding_unavailable", complete["reason_code"])
        self.assertEqual(first_calls, len(self.fake.calls))
        self.assertEqual(1, complete["circuit"]["strike_count"])
        self.assertFalse(
            (self.local.state_dir / "artifacts" / complete["run_id"] / "candidate_evaluation.json").exists()
        )
        self.assertEqual(1, len(list((self.local.state_dir / "artifacts").glob("browser-evidence-*"))))

    def test_overlapping_campaign_collector_lock_wait_never_opens_circuit(self) -> None:
        adapter = self.adapter()
        binding = adapter._evaluation["browser_collection"]["collection_binding_digest"]
        output = adapter._artifact_directory(f"browser-evidence-{binding}")
        descriptor = self.collector._acquire_execution_lock(output)
        results = self.fixture.results(feedback={"kind": "synthetic", "text": "Fixture feedback only."})
        partial_evaluation = {**self.evaluation, "results": {"development": str(results["development"])}}
        try:
            waiting = adapter("candidate_evaluation", self.local.context("candidate_evaluation"))
            self.assertEqual("workflow_execution_locked", waiting["reason_code"])
            self.assertEqual("transient", waiting.get("retry_class"))
            missing_run_id = None
            partial_run_id = None
            for _ in range(3):
                missing = self.coordinator_run(run_id=missing_run_id, resume=missing_run_id is not None)
                partial = self.coordinator_run(partial_evaluation, run_id=partial_run_id, resume=partial_run_id is not None)
                missing_run_id = missing["run_id"]
                partial_run_id = partial["run_id"]
                self.assertNotEqual(missing_run_id, partial["run_id"])
                for receipt in (missing, partial):
                    self.assertEqual("workflow_execution_locked", receipt["reason_code"])
                    self.assertEqual(0, receipt["circuit"]["strike_count"])
            self.assertEqual([], self.fake.calls)
        finally:
            self.collector._release_execution_lock(descriptor)

        resumed = self.coordinator_run(run_id=missing_run_id, resume=True)
        self.assertEqual(missing_run_id, resumed["run_id"])
        self.assertEqual("candidate_evaluation_results_pending", resumed["reason_code"])
        self.assertEqual(0, resumed["circuit"]["strike_count"])
        first_calls = len(self.fake.calls)
        self.assertGreater(first_calls, 0)
        other = self.coordinator_run(partial_evaluation, run_id=partial_run_id, resume=True)
        self.assertEqual("candidate_evaluation_results_pending", other["reason_code"])
        self.assertEqual(0, other["circuit"]["strike_count"])
        self.assertEqual(first_calls, len(self.fake.calls))

    def test_concurrent_first_collection_creates_shared_directory_without_failure(self) -> None:
        adapters = [self.adapter(), self.adapter()]
        binding = adapters[0]._evaluation["browser_collection"]["collection_binding_digest"]
        output = adapters[0]._state_dir / "artifacts" / f"browser-evidence-{binding}"
        output.parent.mkdir(mode=0o700)
        self.assertFalse(output.exists())
        ready = threading.Barrier(2)
        mkdir = Path.mkdir

        def concurrent_mkdir(directory: Path, *args, **kwargs):
            if directory == output and not kwargs.get("exist_ok"):
                ready.wait(timeout=5)
            return mkdir(directory, *args, **kwargs)

        contexts = [
            {**self.local.context("candidate_evaluation"), "run_id": f"weekly-first-{index}"}
            for index in range(2)
        ]
        with patch.object(Path, "mkdir", new=concurrent_mkdir), ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(adapter, "candidate_evaluation", context) for adapter, context in zip(adapters, contexts)]
            results = [future.result(timeout=10) for future in futures]
        reasons = [result["reason_code"] for result in results]
        self.assertIn("candidate_evaluation_results_pending", reasons)
        self.assertTrue(set(reasons) <= {"candidate_evaluation_results_pending", "workflow_execution_locked"})
        for result in results:
            self.assertEqual("transient", result["retry_class"])
        self.assertEqual(0o700, stat.S_IMODE(output.stat().st_mode))
        count = len(self.fake.calls)
        for adapter, context in zip(adapters, contexts):
            self.assertEqual("candidate_evaluation_results_pending", adapter("candidate_evaluation", context)["reason_code"])
        self.assertEqual(count, len(self.fake.calls))

    def test_existing_artifact_directory_remains_strictly_owner_private(self) -> None:
        adapter = self.adapter()
        artifacts = adapter._state_dir / "artifacts"
        artifacts.mkdir(mode=0o700)
        unsafe = artifacts / "unsafe-mode"
        unsafe.mkdir(mode=0o700)
        unsafe.chmod(0o755)
        regular = artifacts / "unsafe-file"
        regular.write_text("Synthetic fixture, not a directory.")
        regular.chmod(0o600)
        target = self.local.root / "owned-link-target"
        target.mkdir(mode=0o700)
        (artifacts / "unsafe-link").symlink_to(target, target_is_directory=True)
        for identity in ("unsafe-mode", "unsafe-file", "unsafe-link"):
            with self.subTest(identity=identity), self.assertRaisesRegex(self.local.adapters.LocalAdapterError, "stage_artifact_permissions_invalid"):
                adapter._artifact_directory(identity)


if __name__ == "__main__":
    unittest.main()
