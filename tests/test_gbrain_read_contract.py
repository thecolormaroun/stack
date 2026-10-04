"""Execute the compatibility boundary without a database or private config."""
import json
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_real_helper_accepts_anchored_bootstrap_but_not_redirects(tmp_path):
    home = tmp_path / "owner"
    package = home / "bootstrap-candidate"
    (package / "src").mkdir(parents=True)
    cli = package / "src/cli.ts"
    cli.write_text("export {};\n")
    (package / "package.json").write_text(json.dumps({"name": "gbrain", "version": "0.48.2.0"}))
    installed = home / ".bun/install/global/node_modules/gbrain"
    installed.parent.mkdir(parents=True)
    installed.symlink_to(package, target_is_directory=True)
    launcher = home / ".bun/bin/gbrain"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(cli)
    environment = {
        "HOME": str(home), "PATH": "/opt/homebrew/bin:/usr/bin:/bin",
        "GBRAIN_SOURCE": "x-bookmarks", "GBRAIN_CLI_PATH": str(cli),
    }

    def invoke(operation):
        return subprocess.run(
            ["/opt/homebrew/bin/bun", "--no-env-file", str(ROOT / "scripts/gbrain-pinned-operation.ts")],
            input=json.dumps({"schema_version": 1, "source": "x-bookmarks", "expected_version": "0.48.2.0", **operation}),
            env=environment, text=True, capture_output=True, timeout=10,
        )

    version = invoke({"operation": "version"})
    assert version.returncode == 0
    assert version.stdout == "gbrain 0.48.2.0"
    denied_import = invoke({"operation": "import", "directory": str(package)})
    assert denied_import.returncode != 0
    assert denied_import.stdout == ""
    unexpected = home / "unexpected.ts"
    unexpected.write_text("export {};\n")
    environment["GBRAIN_CLI_PATH"] = str(unexpected)
    denied_redirect = invoke({"operation": "version"})
    assert denied_redirect.returncode != 0
    assert denied_redirect.stdout == ""


def check_read_versions_do_not_expand_import_or_unknown_operations():
    run_javascript("""
    for (const operation of ['version', 'sources_status', 'keyword']) {
      assert.equal(operationVersionAllowed('0.42.67.0', operation), true);
      assert.equal(operationVersionAllowed('0.48.2.0', operation), true);
      assert.equal(operationVersionAllowed('0.59.0.0', operation), true);
      assert.equal(operationVersionAllowed('0.48.3.0', operation), false);
    }
    assert.equal(operationVersionAllowed('0.42.67.0', 'import'), true);
    assert.equal(operationVersionAllowed('0.48.2.0', 'import'), false);
    assert.equal(operationVersionAllowed('0.59.0.0', 'import'), false);
    assert.equal(operationVersionAllowed('0.48.2.0', 'reindex'), false);
    assert.equal(operationVersionAllowed(undefined, 'version'), false);
    """)


def check_status_records_distinguish_verified_pages_from_quarantine():
    run_javascript("""
    assert.equal(extractionIsUnverified(new Set([1]), 1), true);
    assert.equal(extractionIsUnverified(new Set([1]), 2), false);
    const records = new Map([
      [1, {unverified: true, status: 'unverified'}],
      [2, {unverified: false, status: 'published'}],
    ]);
    assert.equal(extractionIsUnverified(records, 1), true);
    assert.equal(extractionIsUnverified(records, 2), false);
    assert.equal(extractionIsUnverified(records, 3), false);
    for (const invalid of [null, [], {}, new Map([[1, {}]]),
      new Map([[1, {unverified: 'false'}]])]) {
      assert.throws(() => extractionIsUnverified(invalid, 1));
    }
    """)


def run_javascript(assertions):
    node = shutil.which("node")
    assert node, "Node is required to verify the real JavaScript contract"
    module = (ROOT / "scripts/gbrain-read-contract.mjs").as_uri()
    program = (
        "import assert from 'node:assert/strict';\n"
        f"import {{operationVersionAllowed, extractionIsUnverified, readEngineConfig, assertReadOnlySession}} from {json.dumps(module)};\n"
        + assertions
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", program],
        env={"PATH": "/opt/homebrew/bin:/usr/bin:/bin"},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, "JavaScript read-contract assertions failed"


def check_real_059_helper_scopes_reads_and_rejects_embedded_backend(tmp_path):
    home = tmp_path.resolve() / "owner"
    package = home / ".bun/install/global/node_modules/gbrain"
    core = package / "src/core"
    core.mkdir(parents=True)
    cli = package / "src/cli.ts"
    cli.write_text("export {};\n")
    (package / "package.json").write_text(json.dumps({"name": "gbrain", "version": "0.59.0.0"}))
    launcher = home / ".bun/bin/gbrain"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(cli)
    config_dir = home / ".gbrain"
    config_dir.mkdir(mode=0o700)
    embedded = config_dir / "fixture"
    embedded.mkdir(mode=0o700)
    (core / "config.ts").write_text("""
        import {readFileSync} from 'node:fs';
        export function loadConfig() {return JSON.parse(readFileSync(process.env.GBRAIN_HOME+'/.gbrain/config.json','utf8'));}
        export function toEngineConfig(config) {return config;}
    """)
    (core / "engine-factory.ts").write_text("""
        import assert from 'node:assert/strict';
        import {writeFileSync} from 'node:fs';
        export function createEngine(config) {
          assert.equal(config.engine, 'postgres');
          assert.equal(new URL(config.database_url).searchParams.get('default_transaction_read_only'), 'on');
          return {
            async connect() {writeFileSync(process.env.HOME+'/.gbrain/connected','synthetic');},
            async executeRaw(query) {assert.equal(query, \"SELECT current_setting('default_transaction_read_only') AS read_only\"); return [{read_only:config.fixture_read_only}];},
            async searchKeyword(query, options) {
              writeFileSync(process.env.HOME+'/.gbrain/search-called','synthetic');
              assert.equal(query,'geometry'); assert.equal(options.sourceId,'x-bookmarks');
              return [{page_id:1,slug:'bookmarks/verified',source_id:'x-bookmarks'},
                      {page_id:2,slug:'bookmarks/quarantined',source_id:'x-bookmarks'}];
            },
            async getUnverifiedExtractionPageIds(ids, options) {
              assert.deepEqual(ids,[1,2]); assert.deepEqual(options,{sourceId:'x-bookmarks'});
              return new Map([[1,{unverified:false}],[2,{unverified:true}]]);
            },
            async disconnect() {},
          };
        }
    """)
    (core / "sources-ops.ts").write_text("""
        import assert from 'node:assert/strict';
        export async function getSourceStatus(engine, source) {
          assert.equal(source,'x-bookmarks');
          return {id:source,page_count:2,last_sync_at:null,last_commit:null,archived:false,clone_state:'healthy'};
        }
    """)

    def invoke(engine, operation, *, read_only="on"):
        import hashlib
        config = json.dumps({"engine": engine, "fixture_read_only": read_only, **(
            {"database_url": "postgres://fixture@127.0.0.1:5432/gbrain_mookie"}
            if engine == "postgres" else {"database_path": str(embedded)}
        )})
        config_path = config_dir / "config.json"
        config_path.write_text(config)
        config_path.chmod(0o600)
        return subprocess.run(
            ["/opt/homebrew/bin/bun", "--no-env-file", str(ROOT / "scripts/gbrain-pinned-operation.ts")],
            input=json.dumps({"schema_version": 1, "source": "x-bookmarks", "expected_version": "0.59.0.0", **operation}),
            env={"HOME": str(home), "PATH": "/opt/homebrew/bin:/usr/bin:/bin", "GBRAIN_SOURCE": "x-bookmarks",
                 "GBRAIN_CLI_PATH": str(cli), "GBRAIN_CONFIG_SHA256": hashlib.sha256(config.encode()).hexdigest()},
            text=True, capture_output=True, timeout=10,
        )

    denied_version = invoke("postgres", {"operation": "keyword", "query": "geometry", "limit": 2, "expected_version": "0.48.2.0"})
    assert denied_version.returncode != 0 and denied_version.stdout == ""
    assert not (config_dir / "connected").exists()
    denied = invoke("pglite", {"operation": "keyword", "query": "geometry", "limit": 2})
    assert denied.returncode != 0 and denied.stdout == ""
    assert not (config_dir / "connected").exists()
    writable = invoke("postgres", {"operation": "keyword", "query": "geometry", "limit": 2}, read_only="off")
    assert writable.returncode != 0 and writable.stdout == ""
    assert (config_dir / "connected").exists()
    assert not (config_dir / "search-called").exists()
    result = invoke("postgres", {"operation": "keyword", "query": "geometry", "limit": 2})
    assert result.returncode == 0, "synthetic scoped helper failed"
    rows = json.loads(result.stdout)
    assert rows[0].get("unverified") is None and rows[1]["unverified"] is True
    status = invoke("postgres", {"operation": "sources_status"})
    assert status.returncode == 0, "synthetic source status failed"
    assert json.loads(status.stdout)["clone_state"] == "healthy"
    assert not list(config_dir.glob(".stack-config-*"))


class GBrainReadContractTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("STACK_TEST_GBRAIN_PACKAGE"), "opt-in installed-package contract test")
    def test_installed_package_source_status_and_keyword_quarantine(self):
        self.assertTrue(Path("/usr/bin/sandbox-exec").is_file(), "network-denied sandbox is required")
        package = Path(os.environ["STACK_TEST_GBRAIN_PACKAGE"]).resolve(strict=True)
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve() / "owner"
            result = subprocess.run(
                ["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)(deny network*)",
                 "/opt/homebrew/bin/bun", "--no-env-file",
                 str(ROOT / "tests/fixtures/design-retrieval/installed-runtime-probe.ts"),
                 str(package), str(ROOT / "scripts/gbrain-pinned-operation.ts")],
                cwd=directory, env={"HOME": str(home), "PATH": "/opt/homebrew/bin:/usr/bin:/bin"},
                capture_output=True, text=True, timeout=90,
            )
            self.assertEqual(result.returncode, 0, "isolated installed-runtime probe failed")
            payload = json.loads(result.stdout.splitlines()[-1])
            self.assertIs(payload["ok"], True)
            spec = importlib.util.spec_from_file_location("stack_contract_query", ROOT / "scripts/query-design-intelligence.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            try:
                spec.loader.exec_module(module)
                accepted = [row["slug"] for row in payload["rows"] if module._gbrain_candidate(row) is not None]
                self.assertEqual(accepted, ["bookmarks/verified"])
            finally:
                sys.modules.pop(spec.name, None)

    @unittest.skipUnless(Path("/opt/homebrew/bin/bun").is_file(), "requires the pinned macOS Bun launcher")
    def test_real_helper_accepts_anchored_bootstrap_but_not_redirects(self):
        with tempfile.TemporaryDirectory() as directory:
            check_real_helper_accepts_anchored_bootstrap_but_not_redirects(Path(directory))

    @unittest.skipUnless(Path("/opt/homebrew/bin/bun").is_file(), "requires the pinned macOS Bun launcher")
    def test_real_059_helper_scopes_reads_and_rejects_embedded_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            check_real_059_helper_scopes_reads_and_rejects_embedded_backend(Path(directory))

    def test_read_versions_do_not_expand_import_or_unknown_operations(self):
        check_read_versions_do_not_expand_import_or_unknown_operations()

    def test_status_records_distinguish_verified_pages_from_quarantine(self):
        check_status_records_distinguish_verified_pages_from_quarantine()

    def test_read_backend_is_fenced_before_connect_and_not_applied_to_import(self):
        run_javascript("""
        const config = {engine: 'postgres', database_url: 'postgres://fixture@127.0.0.1:5432/gbrain_mookie'};
        const copy = {...config};
        for (const op of ['sources_status', 'keyword']) {
          const guarded = readEngineConfig('0.59.0.0', op, config);
          assert.equal(new URL(guarded.database_url).searchParams.get('default_transaction_read_only'), 'on');
          assert.deepEqual(config, copy);
          assert.throws(() => readEngineConfig('0.59.0.0', op, {engine:'pglite', database_path:'/fixture'}));
          assert.throws(() => readEngineConfig('0.59.0.0', op, {...config, database_url:config.database_url+'?default_transaction_read_only=off'}));
        }
        assert.equal(readEngineConfig('0.42.67.0', 'import', config), config);
        assert.throws(() => readEngineConfig('0.59.0.0', 'import', config));
        assertReadOnlySession([{read_only:'on'}]);
        for (const rows of [null, [], [{read_only:'off'}], [{read_only:true}], [{read_only:'on'}, {read_only:'on'}]]) {
          assert.throws(() => assertReadOnlySession(rows));
        }
        """)
