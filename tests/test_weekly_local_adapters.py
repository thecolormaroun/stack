"""Integration and safety coverage for the owner-local weekly adapters."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "weekly_local_adapters.py"
RETRIEVAL_FIXTURE = ROOT / "tests" / "fixtures" / "design-retrieval" / "candidates.json"
EVALUATION_HELPER = ROOT / "tests" / "test_design_intelligence_candidate.py"


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

    def test_existing_candidate_harness_runs_the_real_evaluator_and_stops_at_approval(self) -> None:
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
        self.assertEqual("prepared", result["status"])
        receipt = self.assert_artifact("candidate_evaluation", result)
        self.assertEqual("awaiting_approval", receipt["status"])
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


if __name__ == "__main__":
    unittest.main()
