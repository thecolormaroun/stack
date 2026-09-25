"""Execute the compatibility boundary without a database or private config."""
import json
import shutil
import subprocess
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
            input=json.dumps({"schema_version": 1, "source": "x-bookmarks", **operation}),
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
      assert.equal(operationVersionAllowed('0.48.3.0', operation), false);
    }
    assert.equal(operationVersionAllowed('0.42.67.0', 'import'), true);
    assert.equal(operationVersionAllowed('0.48.2.0', 'import'), false);
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
        f"import {{operationVersionAllowed, extractionIsUnverified}} from {json.dumps(module)};\n"
        + assertions
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", program],
        env={"PATH": "/opt/homebrew/bin:/usr/bin:/bin"},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, "JavaScript read-contract assertions failed"


class GBrainReadContractTests(unittest.TestCase):
    @unittest.skipUnless(Path("/opt/homebrew/bin/bun").is_file(), "requires the pinned macOS Bun launcher")
    def test_real_helper_accepts_anchored_bootstrap_but_not_redirects(self):
        with tempfile.TemporaryDirectory() as directory:
            check_real_helper_accepts_anchored_bootstrap_but_not_redirects(Path(directory))

    def test_read_versions_do_not_expand_import_or_unknown_operations(self):
        check_read_versions_do_not_expand_import_or_unknown_operations()

    def test_status_records_distinguish_verified_pages_from_quarantine(self):
        check_status_records_distinguish_verified_pages_from_quarantine()
