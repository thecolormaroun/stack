"""Contract and benchmark tests for U17 source-scoped design retrieval."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/query-design-intelligence.py"
FIXTURES = ROOT / "tests/fixtures/design-retrieval"
REQUEST_SCHEMA = ROOT / "registry/design-retrieval-request.schema.json"
RESPONSE_SCHEMA = ROOT / "registry/design-retrieval-response.schema.json"
SOURCE_GRANT_SCHEMA = ROOT / "registry/design-retrieval-source-grant.schema.json"


def load_query():
    spec = importlib.util.spec_from_file_location("design_retrieval", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load retrieval module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_fake_pinned_runtime(module, root: Path) -> dict[str, object]:
    """Install a private test-only copy of the exact pinned-path topology."""

    original = {
        name: getattr(module, name)
        for name in (
            "ACCOUNT_HOME",
            "DEFAULT_GBRAIN_CLI",
            "EXPECTED_GBRAIN_CLI",
            "DEFAULT_GBRAIN_CONFIG",
            "DEFAULT_BUN_CLI",
            "EXPECTED_BUN_CLI",
        )
    }
    account_home = root / "owner-home"
    gbrain_home = account_home / ".gbrain"
    gbrain_home.mkdir(parents=True)
    account_home.chmod(0o700)
    gbrain_home.chmod(0o700)

    bun_target = root / "pinned" / "bun" / "1.3.14" / "bin" / "bun"
    bun_target.parent.mkdir(parents=True)
    bun_target.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    bun_target.chmod(0o700)
    bun_launcher = root / "launcher" / "bin" / "bun"
    bun_launcher.parent.mkdir(parents=True)
    bun_launcher.symlink_to(bun_target)

    cli_target = account_home / ".bun" / "install" / "global" / "node_modules" / "gbrain" / "src" / "cli.ts"
    cli_target.parent.mkdir(parents=True)
    cli_target.write_text("export {};\n", encoding="utf-8")
    cli_target.chmod(0o700)
    package = cli_target.parents[1] / "package.json"
    package.write_text(json.dumps({"name": "gbrain", "version": "0.42.67.0"}), encoding="utf-8")
    package.chmod(0o600)
    cli_launcher = account_home / ".bun" / "bin" / "gbrain"
    cli_launcher.parent.mkdir(parents=True)
    cli_launcher.symlink_to(cli_target)

    module.ACCOUNT_HOME = account_home
    module.DEFAULT_GBRAIN_CLI = str(cli_launcher)
    module.EXPECTED_GBRAIN_CLI = cli_target
    module.DEFAULT_GBRAIN_CONFIG = gbrain_home / "config.json"
    module.DEFAULT_BUN_CLI = bun_launcher
    module.EXPECTED_BUN_CLI = bun_target
    return original


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
        self.runtime_tmp = tempfile.TemporaryDirectory()
        runtime_root = Path(self.runtime_tmp.name).resolve()
        runtime_root.chmod(0o700)
        self._runtime_constants = install_fake_pinned_runtime(self.query, runtime_root)
        self.gbrain_config = self.query.DEFAULT_GBRAIN_CONFIG
        self.gbrain_config.write_text(json.dumps({
            "engine": "postgres",
            "database_url": "postgresql://fixture:fixture@127.0.0.1:5432/gbrain_mookie",
        }), encoding="utf-8")
        os.chmod(self.gbrain_config, 0o600)
        self.gbrain_config = self.gbrain_config.resolve()
        self.query.DEFAULT_GBRAIN_CONFIG = self.gbrain_config
        self.approved_cli = self.query.DEFAULT_GBRAIN_CLI
        self.manifest = self.root / "target-authorizations.json"
        self.manifest.write_text(json.dumps({
            "schema_version": 1,
            "owner_identity": "local-owner:primary",
            "targets": {"codex-local": "local-target:codex-main"},
        }), encoding="utf-8")
        os.chmod(self.manifest, 0o600)
        self.grant = self.root / "x-bookmarks-source-grant.json"
        self.grant.write_text(json.dumps({
            "schema_version": 1,
            "grant_id": "source-grant:" + "f" * 64,
            "owner_identity": "local-owner:primary",
            "source": "x-bookmarks",
            "target_identity": "local-target:codex-main",
            "locator_scopes": ["bookmarks/", "bookmark-"],
            "expires_at": "2027-08-23T12:00:00+00:00",
            "egress_contract": "gbrain-keyword-fts-no-provider-v1",
            "allowed_cli_versions": ["0.42.67.0"],
        }), encoding="utf-8")
        os.chmod(self.grant, 0o600)

    def tearDown(self):
        for name, value in self._runtime_constants.items():
            setattr(self.query, name, value)
        self.runtime_tmp.cleanup()
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

    def assert_response_schema_contract(self, response):
        schema = json.loads(RESPONSE_SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(set(schema["required"]), set(response))
        self.assertIn(response["status"], schema["properties"]["status"]["enum"])
        allowed = set(schema["properties"]["degradations"]["items"]["enum"])
        self.assertTrue(set(response["degradations"]).issubset(allowed))
        reason = response["reason_code"]
        self.assertTrue(reason is None or self.query.re.fullmatch(r"[a-z0-9-]{1,64}", reason))

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
        self.assertTrue(all("metadata" not in item for item in result["results"]))

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

    def live_status(self, **changes):
        status = {
            "id": "x-bookmarks",
            "page_count": 4,
            "last_sync_at": "2026-08-22T12:00:00+00:00",
            "last_commit": "index-20260822",
            "archived": False,
            "clone_state": "healthy",
        }
        status.update(changes)
        return status

    def live_result(self, **changes):
        result = {
            "slug": "bookmarks/design-dense-dashboard",
            "source_id": "x-bookmarks",
            "chunk_text": "dashboard evidence",
            "page_id": 1,
            "chunk_id": 1,
            "score": 0.9,
            "stale": False,
            "effective_date": "2026-08-22T12:00:00+00:00",
        }
        result.update(changes)
        return result

    def live_runner(self, calls, *, status=None, results=None, version="gbrain 0.42.67.0"):
        def runner(argv, **kwargs):
            self.assertEqual([str(self.query.DEFAULT_BUN_CLI.resolve(strict=True)), "--no-env-file"], argv[0:2])
            self.assertEqual(str(ROOT / "scripts"), kwargs["cwd"])
            if argv[2].endswith("gbrain-pinned-operation.ts"):
                operation = json.loads(kwargs["input"])["operation"]
                if operation == "keyword":
                    operation = "keyword_search"
            else:
                raise AssertionError("unexpected live helper")
            calls.append({
                "operation": operation,
                "env_keys": sorted(kwargs["env"]),
                "source": kwargs["env"].get("GBRAIN_SOURCE"),
                "argv": argv,
                "cwd": kwargs["cwd"],
            })
            if operation == "version":
                return SimpleNamespace(returncode=0, stdout=version, stderr="")
            if operation == "sources_status":
                return SimpleNamespace(returncode=0, stdout=json.dumps(status or self.live_status()), stderr="")
            if operation == "keyword_search":
                self.assertEqual(str(ROOT / "scripts"), kwargs["cwd"])
                self.assertRegex(kwargs["env"]["GBRAIN_CONFIG_SHA256"], r"^[a-f0-9]{64}$")
                payload = json.loads(kwargs["input"])
                self.assertEqual({"limit", "operation", "query", "schema_version", "source"}, set(payload))
                return SimpleNamespace(returncode=0, stdout=json.dumps(results if results is not None else [self.live_result()]), stderr="")
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return runner

    def test_live_cli_is_opt_in_and_needs_a_verified_target_before_any_command(self):
        calls = []
        transport = self.query.CliGBrainTransport(cli_path=self.approved_cli, runner=self.live_runner(calls))
        unbound = transport.text_search("dashboard", 5)
        self.assertEqual("unavailable", unbound["state"])
        self.assertEqual([], calls)

        live = self.query.CliGBrainTransport(cli_path=self.approved_cli, runner=self.live_runner(calls), live=True)
        with mock.patch.dict(os.environ, {"UNRELATED_FLAG": "1"}):
            response = self.query.retrieve(
                self.request(), target_manifest=self.manifest, source_grant=self.grant, transport=live,
            )
        self.assertEqual(
            ["version", "sources_status", "keyword_search", "keyword_search", "version", "sources_status"],
            [call["operation"] for call in calls],
        )
        self.assertTrue(all(call["source"] == "x-bookmarks" for call in calls))
        self.assertTrue(all(
            call["env_keys"] == ["GBRAIN_CLI_PATH", "GBRAIN_CONFIG_SHA256", "GBRAIN_SOURCE", "HOME", "PATH", "TMPDIR"]
            for call in calls
        ))
        self.assertEqual("x-bookmarks", response["source"])
        self.assertEqual(self.query.validate_target(self.request(), self.manifest)["manifest_digest"], response["target"]["manifest_digest"])
        self.assertEqual("degraded", response["status"])

    def test_keyword_helper_disables_env_files_and_drops_database_overrides(self):
        calls = []
        transport = self.query.CliGBrainTransport(
            cli_path=self.approved_cli,
            runner=self.live_runner(calls),
            live=True,
        )
        with mock.patch.dict(os.environ, {
            "GBRAIN_HOME": "/attacker/home",
            "GBRAIN_DATABASE_URL": "postgresql://attacker.invalid/db",
            "DATABASE_URL": "postgresql://attacker.invalid/other",
        }):
            response = self.query.retrieve(
                self.request(),
                target_manifest=self.manifest,
                source_grant=self.grant,
                transport=transport,
            )
        self.assertEqual("degraded", response["status"])
        keyword_calls = [call for call in calls if call["operation"] == "keyword_search"]
        self.assertEqual(2, len(keyword_calls))
        for call in keyword_calls:
            self.assertNotIn("GBRAIN_HOME", call["env_keys"])
            self.assertNotIn("GBRAIN_DATABASE_URL", call["env_keys"])
            self.assertNotIn("DATABASE_URL", call["env_keys"])

    def test_attestation_calls_disable_env_files_and_ignore_hostile_cwd(self):
        calls = []
        transport = self.query.CliGBrainTransport(
            cli_path=self.approved_cli,
            runner=self.live_runner(calls),
            live=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            hostile_cwd = Path(directory)
            (hostile_cwd / ".env").write_text(
                "GBRAIN_HOME=/tmp/hostile-home\nDATABASE_URL=postgresql://remote.invalid/other\n",
                encoding="utf-8",
            )
            previous_cwd = Path.cwd()
            try:
                os.chdir(hostile_cwd)
                with mock.patch.dict(os.environ, {
                    "GBRAIN_HOME": "/tmp/hostile-home",
                    "GBRAIN_DATABASE_URL": "postgresql://remote.invalid/other",
                    "DATABASE_URL": "postgresql://remote.invalid/other",
                }):
                    response = self.query.retrieve(
                        self.request(),
                        target_manifest=self.manifest,
                        source_grant=self.grant,
                        transport=transport,
                    )
            finally:
                os.chdir(previous_cwd)

        self.assertEqual("degraded", response["status"])
        attestation_calls = [call for call in calls if call["operation"] in {"version", "sources_status"}]
        self.assertEqual(4, len(attestation_calls))
        for call in attestation_calls:
            self.assertEqual([str(self.query.DEFAULT_BUN_CLI.resolve(strict=True)), "--no-env-file"], call["argv"][0:2])
            self.assertEqual(str(ROOT / "scripts"), call["cwd"])
            self.assertTrue({"GBRAIN_HOME", "GBRAIN_DATABASE_URL", "DATABASE_URL"}.isdisjoint(call["env_keys"]))

    def test_live_transport_rejects_unpinned_bun_before_any_subprocess(self):
        calls = []
        transport = self.query.CliGBrainTransport(
            cli_path=self.approved_cli,
            bun_path="bun",
            runner=self.live_runner(calls),
            live=True,
        )
        response = self.query.retrieve(
            self.request(), target_manifest=self.manifest, source_grant=self.grant, transport=transport,
        )
        self.assertEqual("failed", response["status"])
        self.assertEqual([], calls)

    def test_live_transport_rejects_absolute_alternate_bun_before_any_subprocess(self):
        alternate = self.root / "alternate-bun"
        alternate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        os.chmod(alternate, 0o700)
        calls = []
        transport = self.query.CliGBrainTransport(
            cli_path=self.approved_cli,
            bun_path=str(alternate),
            runner=self.live_runner(calls),
            live=True,
        )
        response = self.query.retrieve(
            self.request(), target_manifest=self.manifest, source_grant=self.grant, transport=transport,
        )
        self.assertEqual("failed", response["status"])
        self.assertEqual([], calls)

    def test_live_transport_rejects_nonapproved_gbrain_script_before_any_subprocess(self):
        calls = []
        transport = self.query.CliGBrainTransport(
            cli_path="/tmp/not-gbrain.ts",
            runner=self.live_runner(calls),
            live=True,
        )
        response = self.query.retrieve(
            self.request(), target_manifest=self.manifest, source_grant=self.grant, transport=transport,
        )
        self.assertEqual("failed", response["status"])
        self.assertEqual([], calls)

    def test_config_bound_wrapper_rejects_provider_overrides_before_any_operation(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "portable environment-fence test requires Node.js")
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "GBRAIN_SOURCE": "x-bookmarks",
            "OPENAI_API_KEY": "synthetic-provider-override",
        }
        module_url = (ROOT / "scripts" / "gbrain-pinned-environment.mjs").resolve().as_uri()
        program = (
            f'import {{ assertSafeEnvironment }} from {json.dumps(module_url)};'
            'try { assertSafeEnvironment(process.env); process.exitCode = 2; } '
            'catch { process.stdout.write("rejected"); }'
        )
        result = subprocess.run(
            [node, "--input-type=module", "--eval", program],
            capture_output=True,
            text=True,
            env=environment,
            timeout=30,
            check=False,
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("rejected", result.stdout)
        self.assertEqual("", result.stderr)
        self.assertNotIn("synthetic-provider-override", result.stderr)

    def test_pinned_operation_keeps_exact_runtime_and_environment_fences(self):
        helper = self.query.PINNED_OPERATION_HELPER.read_text(encoding="utf-8")
        self.assertIn(
            'if (realpathSync(process.execPath) !== realpathSync("/opt/homebrew/bin/bun")) fail();',
            helper,
        )
        self.assertIn('import { assertSafeEnvironment } from "./gbrain-pinned-environment.mjs";', helper)
        self.assertIn("assertSafeEnvironment(process.env);", helper)

    def test_live_transport_rejects_default_launcher_redirected_to_unexpected_script(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            unexpected = Path(directory) / "unexpected.ts"
            unexpected.write_text("process.exit(0)\n", encoding="utf-8")
            os.chmod(unexpected, 0o700)
            launcher = Path(directory) / "gbrain"
            launcher.symlink_to(unexpected)
            with mock.patch.object(self.query, "DEFAULT_GBRAIN_CLI", str(launcher)):
                transport = self.query.CliGBrainTransport(
                    runner=self.live_runner(calls),
                    live=True,
                )
                response = self.query.retrieve(
                    self.request(), target_manifest=self.manifest, source_grant=self.grant, transport=transport,
                )
        self.assertEqual("failed", response["status"])
        self.assertEqual([], calls)

    def test_live_source_grant_is_required_and_target_bound_before_any_command(self):
        calls = []
        live = self.query.CliGBrainTransport(
            cli_path=self.approved_cli, runner=self.live_runner(calls), live=True,
        )
        with self.assertRaisesRegex(self.query.RetrievalError, "source grant"):
            self.query.retrieve(self.request(), target_manifest=self.manifest, transport=live)
        self.assertEqual([], calls)

        value = json.loads(self.grant.read_text(encoding="utf-8"))
        value["target_identity"] = "local-target:other-main"
        self.grant.write_text(json.dumps(value), encoding="utf-8")
        os.chmod(self.grant, 0o600)
        with self.assertRaisesRegex(self.query.RetrievalError, "target binding"):
            self.query.retrieve(
                self.request(), target_manifest=self.manifest, source_grant=self.grant, transport=live,
            )
        self.assertEqual([], calls)

    def test_live_version_and_command_allowlists_fail_closed(self):
        calls = []
        live = self.query.CliGBrainTransport(
            cli_path=self.approved_cli,
            runner=self.live_runner(calls, version="gbrain 0.42.68.0"),
            live=True,
        )
        response = self.query.retrieve(
            self.request(), target_manifest=self.manifest, source_grant=self.grant, transport=live,
        )
        self.assertEqual("failed", response["status"])
        self.assertEqual(["version"], [call["operation"] for call in calls])

        invoked = []
        guarded = self.query.CliGBrainTransport(
            cli_path=self.approved_cli,
            runner=lambda *args, **kwargs: invoked.append((args, kwargs)),
            live=True,
        )
        self.assertEqual((None, "failed"), guarded._run([self.approved_cli, "import", "/tmp/private"]))
        self.assertEqual(
            (None, "failed"),
            guarded._run([self.approved_cli, "call", "search", '{"query":"private"}']),
        )
        self.assertEqual([], invoked)

    def test_expired_grant_cannot_be_revived_by_backdating_request(self):
        value = json.loads(self.grant.read_text(encoding="utf-8"))
        value["expires_at"] = "2026-08-24T12:00:00+00:00"
        self.grant.write_text(json.dumps(value), encoding="utf-8")
        os.chmod(self.grant, 0o600)
        calls = []
        transport = self.query.CliGBrainTransport(
            cli_path=self.approved_cli, runner=self.live_runner(calls), live=True,
        )
        with mock.patch.object(
            self.query,
            "_utc_now",
            return_value=self.query._parse_time("2026-08-29T12:00:00+00:00"),
        ):
            with self.assertRaisesRegex(self.query.RetrievalError, "expired"):
                self.query.retrieve(
                    self.request(freshness={"as_of": "2026-08-23T12:00:00+00:00", "max_age_days": 14}),
                    target_manifest=self.manifest,
                    source_grant=self.grant,
                    transport=transport,
                )
        self.assertEqual([], calls)

    def test_grant_expiry_between_reads_stops_before_the_next_command(self):
        value = json.loads(self.grant.read_text(encoding="utf-8"))
        value["expires_at"] = "2026-08-24T12:00:00+00:00"
        self.grant.write_text(json.dumps(value), encoding="utf-8")
        os.chmod(self.grant, 0o600)
        before = self.query._parse_time("2026-08-23T13:00:00+00:00")
        after = self.query._parse_time("2026-08-24T13:00:00+00:00")
        assert before is not None and after is not None
        moments = iter((before, before, after))
        calls = []
        transport = self.query.CliGBrainTransport(
            cli_path=self.approved_cli,
            runner=self.live_runner(calls),
            live=True,
            now_provider=lambda: next(moments),
        )
        with mock.patch.object(self.query, "_utc_now", return_value=before):
            response = self.query.retrieve(
                self.request(),
                target_manifest=self.manifest,
                source_grant=self.grant,
                transport=transport,
            )
        self.assertEqual("failed", response["status"])
        self.assertEqual("source-grant-expired", response["reason_code"])
        self.assert_response_schema_contract(response)
        self.assertEqual(["version"], [call["operation"] for call in calls])

    def test_remote_database_config_is_rejected_before_any_subprocess(self):
        remote_config = self.root / "remote-gbrain-config.json"
        remote_config.write_text(json.dumps({
            "engine": "postgres",
            "database_url": "postgresql://fixture:fixture@db.example.invalid:5432/gbrain_mookie",
        }), encoding="utf-8")
        os.chmod(remote_config, 0o600)
        calls = []
        transport = self.query.CliGBrainTransport(
            cli_path=self.approved_cli,
            runner=self.live_runner(calls),
            live=True,
            gbrain_config_path=remote_config,
        )
        response = self.query.retrieve(
            self.request(),
            target_manifest=self.manifest,
            source_grant=self.grant,
            transport=transport,
        )
        self.assertEqual("failed", response["status"])
        self.assertEqual("local-backend-rejected", response["reason_code"])
        self.assert_response_schema_contract(response)
        self.assertEqual([], calls)

    def test_campaign_attestation_changes_with_live_index_state(self):
        first = self.query.CliGBrainTransport(
            cli_path=self.approved_cli, runner=self.live_runner([]), live=True,
        ).campaign_attestation(
            self.request(), target_manifest=self.manifest, source_grant=self.grant,
        )
        second = self.query.CliGBrainTransport(
            cli_path=self.approved_cli,
            runner=self.live_runner([], status=self.live_status(page_count=5, last_commit="index-20260823")),
            live=True,
        ).campaign_attestation(
            self.request(), target_manifest=self.manifest, source_grant=self.grant,
        )
        self.assertEqual("complete", first["state"])
        self.assertNotEqual(first["attestation_digest"], second["attestation_digest"])
        self.assertEqual("gbrain-keyword-fts-no-provider-v1", first["egress_contract"])
        self.assertEqual(0, first["provider_calls"])

    def test_live_result_order_is_canonical_for_a_pinned_index(self):
        values = [
            self.live_result(slug="bookmarks/design-a", page_id=1, chunk_id=1),
            self.live_result(slug="bookmarks/design-b", page_id=2, chunk_id=2),
            self.live_result(slug="bookmarks/design-c", page_id=3, chunk_id=3),
        ]
        responses = []
        for rows in (values, list(reversed(values))):
            transport = self.query.CliGBrainTransport(
                cli_path=self.approved_cli, runner=self.live_runner([], results=rows), live=True,
            )
            responses.append(self.query.retrieve(
                self.request(), target_manifest=self.manifest, source_grant=self.grant, transport=transport,
            ))
        self.assertEqual(
            [row["candidate_id"] for row in responses[0]["results"]],
            [row["candidate_id"] for row in responses[1]["results"]],
        )
        self.assertEqual(responses[0]["response_digest"], responses[1]["response_digest"])

    def test_live_text_transport_binds_verified_target_and_attestation_metadata(self):
        calls = []
        transport = self.query.CliGBrainTransport(cli_path=self.approved_cli, runner=self.live_runner(calls), live=True)
        response = self.query.retrieve(
            self.request(), target_manifest=self.manifest, source_grant=self.grant, transport=transport,
        )
        self.assertEqual(1, response["result_count"])
        self.assertEqual(["gbrain:x-bookmarks:index-20260822:pages-4"], response["index"]["versions"])
        self.assertEqual(1, len(response["index"]["model_versions"]))
        self.assertRegex(response["index"]["model_versions"][0], r"^gbrain-cli:0\.42\.67\.0:stack-keyword:[a-f0-9]{16}$")
        self.assertTrue(response["safety"]["target_attested"])
        self.assertTrue(response["safety"]["source_scope_enforced"])

    def test_live_source_attestation_failures_are_visible_and_stop_search(self):
        cases = {
            "wrong-source": self.live_status(id="other-source"),
            "missing-index": self.live_status(last_commit=None),
            "missing-archived": self.live_status(archived=None),
            "archived": self.live_status(archived=True),
            "corrupted": self.live_status(clone_state="corrupted"),
        }
        for label, status in cases.items():
            with self.subTest(label=label):
                calls = []
                transport = self.query.CliGBrainTransport(cli_path=self.approved_cli, runner=self.live_runner(calls, status=status), live=True)
                response = self.query.retrieve(
                    self.request(), target_manifest=self.manifest, source_grant=self.grant, transport=transport,
                )
                self.assertEqual("failed", response["status"])
                self.assertNotIn("search", [call["operation"] for call in calls])

    def test_config_bound_wrapper_can_attest_a_local_only_clone_without_exposing_its_path(self):
        head = "a" * 40
        status = self.live_status(
            clone_state="local-attested",
            last_commit=head,
        )
        transport = self.query.CliGBrainTransport(
            cli_path=self.approved_cli,
            runner=self.live_runner([], status=status),
            live=True,
        )
        response = self.query.retrieve(
            self.request(),
            target_manifest=self.manifest,
            source_grant=self.grant,
            transport=transport,
        )

        self.assertEqual(1, response["result_count"])
        self.assertEqual("degraded", response["status"])

    def test_live_result_source_mismatch_fails_closed(self):
        calls = []
        transport = self.query.CliGBrainTransport(
            cli_path=self.approved_cli,
            runner=self.live_runner(calls, results=[self.live_result(source_id="other-source")]),
            live=True,
        )
        response = self.query.retrieve(
            self.request(), target_manifest=self.manifest, source_grant=self.grant, transport=transport,
        )
        self.assertEqual("failed", response["status"])
        self.assertEqual("x-bookmarks", response["source"])

    def test_live_search_excludes_aggregate_pages_from_bookmark_results(self):
        results = [
            self.live_result(),
            self.live_result(slug="domains/ai", page_id=2, chunk_id=2),
            self.live_result(slug="categories/health", page_id=3, chunk_id=3),
        ]
        response = self.query.retrieve(
            self.request(),
            target_manifest=self.manifest,
            source_grant=self.grant,
            transport=self.query.CliGBrainTransport(
                cli_path=self.approved_cli,
                runner=self.live_runner([], results=results),
                live=True,
            ),
        )
        self.assertEqual(1, response["result_count"])
        self.assertEqual(
            "gbrain:x-bookmarks/bookmarks/design-dense-dashboard",
            response["results"][0]["citation_locator"],
        )

    def test_live_source_freshness_cannot_produce_a_complete_response(self):
        cases = {
            "stale": self.live_status(last_sync_at="2026-07-01T12:00:00+00:00"),
            "future": self.live_status(last_sync_at="2026-09-01T12:00:00+00:00"),
        }
        for label, status in cases.items():
            with self.subTest(label=label):
                transport = self.query.CliGBrainTransport(cli_path=self.approved_cli, runner=self.live_runner([], status=status), live=True)
                response = self.query.retrieve(
                    self.request(), target_manifest=self.manifest, source_grant=self.grant, transport=transport,
                )
                self.assertNotEqual("complete", response["status"])
                self.assertNotEqual("empty", response["status"])

    def test_live_image_search_is_unavailable_without_a_subprocess(self):
        calls = []
        request = self.request()
        request["context"]["screenshot"] = {"path": str(self.root / "screen.png"), "digest": "b" * 64}
        transport = self.query.CliGBrainTransport(cli_path=self.approved_cli, runner=self.live_runner(calls), live=True)
        response = self.query.retrieve(
            request, target_manifest=self.manifest, source_grant=self.grant, transport=transport,
        )
        self.assertEqual("degraded", response["status"])
        self.assertIn("image", response["missing_modalities"])
        self.assertNotIn("search_by_image", [call["operation"] for call in calls])

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

    def test_cli_error_envelopes_do_not_become_successful_empty_searches(self):
        for payload in ({"error": "error-marker"}, {"unexpected": []}, {"results": "wrong-shape"}, {"isError": True, "results": []}):
            with self.subTest(payload=payload):
                calls = []
                transport = self.query.CliGBrainTransport(cli_path=self.approved_cli, runner=self.live_runner(calls, results=payload), live=True)
                result = self.query.retrieve(
                    self.request(), target_manifest=self.manifest, source_grant=self.grant, transport=transport,
                )
                self.assertEqual("failed", result["status"])
                self.assertNotEqual("complete", result["status"])

    def test_unverified_live_extractions_are_not_retrieval_truth(self):
        candidate = self.query._gbrain_candidate(self.live_result(slug="bookmarks/unverified", unverified=True))
        self.assertIsNone(candidate)
        transport = self.query.CliGBrainTransport(
            cli_path=self.approved_cli,
            runner=self.live_runner([], results=[self.live_result(unverified=True)]),
            live=True,
        )
        response = self.query.retrieve(
            self.request(), target_manifest=self.manifest, source_grant=self.grant, transport=transport,
        )
        self.assertEqual("empty", response["status"])
        self.assertEqual(0, response["result_count"])

    def test_schema_and_contract_files_exist(self):
        for path in (
            REQUEST_SCHEMA,
            RESPONSE_SCHEMA,
            SOURCE_GRANT_SCHEMA,
            ROOT / "skills/design/design-intelligence/references/retrieval-contract.md",
        ):
            self.assertTrue(path.exists(), path)


if __name__ == "__main__":
    unittest.main()
