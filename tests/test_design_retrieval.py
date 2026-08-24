"""Contract and benchmark tests for U17 source-scoped design retrieval."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/query-design-intelligence.py"
FIXTURES = ROOT / "tests/fixtures/design-retrieval"
REQUEST_SCHEMA = ROOT / "registry/design-retrieval-request.schema.json"
RESPONSE_SCHEMA = ROOT / "registry/design-retrieval-response.schema.json"


def load_query():
    spec = importlib.util.spec_from_file_location("design_retrieval", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load retrieval module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FixtureTransport:
    def __init__(self, candidates: list[dict], *, image_available: bool = True, fail_text: bool = False):
        self.candidates = candidates
        self.image_available = image_available
        self.fail_text = fail_text
        self.calls: list[tuple[str, str]] = []

    def text_search(self, query: str, limit: int) -> dict:
        self.calls.append(("text", query))
        if self.fail_text:
            return {"state": "failed", "results": [], "index_version": "fixture-index-v1", "model_version": "fixture-lexical-v1"}
        terms = set(query.lower().split())
        ranked = sorted(self.candidates, key=lambda row: (-len(terms & set(row["text_terms"])), row["candidate_id"]))
        return {"state": "complete", "results": ranked[:limit], "index_version": "fixture-index-v1", "model_version": "fixture-lexical-v1"}

    def image_search(self, image: str, query: str, limit: int) -> dict:
        self.calls.append(("image", image))
        if not self.image_available:
            return {"state": "unavailable", "results": [], "index_version": "fixture-index-v1", "model_version": "fixture-image-v1"}
        terms = set(query.lower().split())
        ranked = sorted(self.candidates, key=lambda row: (-len(terms & set(row["image_terms"])), row["candidate_id"]))
        return {"state": "complete", "results": ranked[:limit], "index_version": "fixture-index-v1", "model_version": "fixture-image-v1"}


class DesignRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.query = load_query()
        cls.fixture = json.loads((FIXTURES / "candidates.json").read_text(encoding="utf-8"))
        cls.candidates = cls.fixture["candidates"]
        cls.qrels = json.loads((FIXTURES / "qrels.json").read_text(encoding="utf-8"))
        cls.baseline = json.loads((FIXTURES / "baseline.json").read_text(encoding="utf-8"))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.chmod(self.root, 0o700)
        self.manifest = self.root / "target-authorizations.json"
        self.manifest.write_text(json.dumps({
            "schema_version": 1,
            "owner_identity": "local-owner:primary",
            "targets": {"codex-local": "local-target:codex-main"},
        }), encoding="utf-8")
        os.chmod(self.manifest, 0o600)

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, **changes):
        request = {
            "schema_version": 1,
            "request_id": "request:" + "a" * 64,
            "source": "x-bookmarks",
            "target": {"name": "codex-local", "identity": "local-target:codex-main", "owner_identity": "local-owner:primary"},
            "context": {
                "project": "stack", "repository": "stack", "route": "/admin",
                "component": "dashboard", "viewport": {"width": 1440, "height": 900},
                "device": "desktop", "brief": "dense dashboard table filters side-panel",
                "code": "table filters validation", "markup": "dashboard side-panel", "screenshot": None,
            },
            "filters": {},
            "freshness": {"as_of": "2026-08-23T12:00:00+00:00", "max_age_days": 14},
            "top_k": 5,
        }
        for key, value in changes.items():
            request[key] = value
        return request

    def test_exact_filters_rank_one_and_response_is_source_scoped(self):
        request = self.request(filters={"author": "designer-a", "date": "2026-08-20", "folder": "design-systems", "url": "https://x.com/designer-a/status/1"})
        result = self.query.retrieve(request, target_manifest=self.manifest, transport=FixtureTransport(self.candidates))
        self.assertEqual("complete", result["status"])
        self.assertEqual(self.candidates[0]["candidate_id"], result["results"][0]["candidate_id"])
        self.assertIn("exact-author", result["results"][0]["similarity_reasons"])
        self.assertTrue(all(item["source"] == "x-bookmarks" for item in result["results"]))

    def test_each_exact_canary_ranks_one_and_every_result_is_cited(self):
        expected = self.candidates[0]
        canaries = {
            "evidence_id": expected["evidence_id"],
            "author": expected["metadata"]["author"],
            "date": expected["metadata"]["date"],
            "folder": expected["metadata"]["folder"],
            "url": expected["metadata"]["url"],
        }
        for key, value in canaries.items():
            with self.subTest(key=key):
                result = self.query.retrieve(
                    self.request(filters={key: value}),
                    target_manifest=self.manifest,
                    transport=FixtureTransport(self.candidates),
                )
                self.assertEqual(expected["candidate_id"], result["results"][0]["candidate_id"])
                self.assertEqual(len(result["results"]), sum(bool(row["citation_locator"]) for row in result["results"]))

    def test_unauthorized_target_and_caller_supplied_identity_fail_closed(self):
        wrong = self.request(target={"name": "codex-local", "identity": "local-target:other-main", "owner_identity": "local-owner:primary"})
        with self.assertRaises(self.query.RetrievalError):
            self.query.retrieve(wrong, target_manifest=self.manifest, transport=FixtureTransport(self.candidates))

    def test_cross_target_candidate_leaks_no_identity_or_metadata(self):
        result = self.query.retrieve(self.request(), target_manifest=self.manifest, transport=FixtureTransport(self.candidates))
        encoded = json.dumps(result)
        self.assertNotIn("candidate:555555", encoded)
        self.assertNotIn("private-author", encoded)
        self.assertNotIn("unauthorized-secret", encoded)

    def test_image_unavailable_is_labeled_degradation_without_fallback(self):
        request = self.request()
        request["context"]["screenshot"] = {"path": str(self.root / "screen.png"), "digest": "b" * 64}
        transport = FixtureTransport(self.candidates, image_available=False)
        result = self.query.retrieve(request, target_manifest=self.manifest, transport=transport)
        self.assertEqual("degraded", result["status"])
        self.assertIn("image", result["missing_modalities"])
        self.assertFalse(result["safety"]["reindex_attempted"])
        self.assertFalse(result["safety"]["paid_fallback_attempted"])

    def test_empty_error_sparse_and_stale_states_are_explicit(self):
        empty = self.query.retrieve(self.request(), target_manifest=self.manifest, transport=FixtureTransport([]))
        self.assertEqual("empty", empty["status"])
        failed = self.query.retrieve(self.request(), target_manifest=self.manifest, transport=FixtureTransport([], fail_text=True))
        self.assertEqual("failed", failed["status"])
        stale_request = self.request(freshness={"as_of": "2026-10-23T12:00:00+00:00", "max_age_days": 14})
        stale = self.query.retrieve(stale_request, target_manifest=self.manifest, transport=FixtureTransport(self.candidates[:1]))
        self.assertEqual("degraded", stale["status"])
        self.assertIn("stale-index", stale["degradations"])

    def test_corrupt_media_keeps_provenance_and_never_erases_text_result(self):
        request = self.request()
        request["context"]["brief"] = "dashboard table error-state"
        result = self.query.retrieve(request, target_manifest=self.manifest, transport=FixtureTransport(self.candidates))
        corrupt = next(item for item in result["results"] if item["candidate_id"].startswith("candidate:666"))
        self.assertEqual("corrupt", corrupt["media_state"])
        self.assertRegex(corrupt["evidence_id"], r"^evidence:[a-f0-9]{16,64}$")

    def test_deterministic_benchmark_meets_recall_and_ndcg_gate(self):
        cases = {
            "dashboard-dense": self.request(),
            "mobile-table": self.request(context={
                "project": "stack", "repository": "stack", "route": "/mobile", "component": "table",
                "viewport": {"width": 390, "height": 844}, "device": "mobile",
                "brief": "mobile table responsive priority cards", "code": "", "markup": "", "screenshot": None,
            }),
        }
        metrics = []
        for name, request in cases.items():
            first = self.query.retrieve(request, target_manifest=self.manifest, transport=FixtureTransport(self.candidates))
            second = self.query.retrieve(request, target_manifest=self.manifest, transport=FixtureTransport(self.candidates))
            self.assertEqual([row["candidate_id"] for row in first["results"]], [row["candidate_id"] for row in second["results"]])
            metrics.append(self.query.evaluate_ranking([row["candidate_id"] for row in first["results"]], self.qrels[name], k=5))
        recall = sum(row["recall_at_k"] for row in metrics) / len(metrics)
        ndcg = sum(row["ndcg_at_k"] for row in metrics) / len(metrics)
        baseline = self.baseline["fresh_baseline"]
        ratio = self.baseline["minimum_baseline_ratio"]
        self.assertGreaterEqual(recall, self.baseline["minimum_recall_at_5"])
        self.assertGreaterEqual(ndcg, self.baseline["minimum_ndcg_at_5"])
        self.assertGreaterEqual(recall, baseline["mean_recall_at_5"] * ratio)
        self.assertGreaterEqual(ndcg, baseline["mean_ndcg_at_5"] * ratio)

    def test_cli_gbrain_contract_is_read_only_scoped_and_redacted(self):
        calls = []
        payload = [{
            "slug": "design/dense-dashboard", "source_id": "x-bookmarks", "chunk_text": "Evidence identity: bookmark:" + "c" * 64,
            "score": 0.9, "stale": False, "page_id": 1,
        }]

        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stdout="diagnostic\n" + json.dumps(payload), stderr="secret provider log")

        transport = self.query.CliGBrainTransport(cli_path="gbrain-test", runner=runner)
        result = transport.text_search("dense dashboard", 5)
        self.assertEqual(["gbrain-test", "call", "search", json.dumps({"query": "dense dashboard", "limit": 5}, separators=(",", ":"), sort_keys=True)], calls[0][0])
        self.assertEqual("x-bookmarks", calls[0][1]["env"]["GBRAIN_SOURCE"])
        self.assertEqual("complete", result["state"])
        self.assertNotIn("secret", json.dumps(result))

    def test_response_writer_never_weakens_an_existing_directory(self):
        unsafe = self.root / "shared"
        unsafe.mkdir()
        os.chmod(unsafe, 0o755)
        with self.assertRaises(self.query.RetrievalError):
            self.query.write_response(unsafe / "response.json", {"status": "empty"})
        self.assertEqual(0o755, stat.S_IMODE(unsafe.stat().st_mode))

        private = self.root / "private"
        private.mkdir()
        os.chmod(private, 0o700)
        output = self.query.write_response(private / "response.json", {"status": "empty"})
        self.assertEqual(0o600, stat.S_IMODE(output.stat().st_mode))

    def test_schema_and_contract_files_exist(self):
        for path in (REQUEST_SCHEMA, RESPONSE_SCHEMA, ROOT / "skills/design/design-intelligence/references/retrieval-contract.md"):
            self.assertTrue(path.exists(), path)


if __name__ == "__main__":
    unittest.main()
