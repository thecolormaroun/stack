from __future__ import annotations

import json
import os
import subprocess
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run-stack-bookmark-curation.sh"
INSTALLER = ROOT / "scripts" / "install-hermes-stack-curation-job.sh"


def _verification_receipts(root: Path) -> Path:
    root.mkdir(parents=True)
    root.chmod(0o700)
    for phase in ("collection", "curation"):
        receipt = root / f"{phase}-proof.json"
        receipt.write_text(json.dumps({"receipt_type": phase, "phase": phase, "complete": True, "manual_run": True, "mode": "apply"}))
        receipt.chmod(0o600)
        assert time.time() - receipt.stat().st_mtime < 5
    return root


def test_collection_uses_a_receipt_and_releases_its_own_lock(tmp_path):
    state = tmp_path / "state"
    sources = tmp_path / "sources.json"
    sources.write_text('{"sources": []}')
    env = {**os.environ, "STACK_BOOKMARK_STATE_ROOT": str(state), "STACK_BOOKMARK_SOURCES": str(sources)}
    result = subprocess.run([str(RUNNER), "collection"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    receipts = list((state / "receipts").glob("collection-*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt["mode"] == "dry-run"
    assert receipt["receipt_type"] == "collection"
    assert not (state / "collection.lock").exists()


def test_collection_and_curation_locks_are_separate(tmp_path):
    state = tmp_path / "state"
    (state / "collection.lock").mkdir(parents=True)
    env = {**os.environ, "STACK_BOOKMARK_STATE_ROOT": str(state)}
    blocked = subprocess.run([str(RUNNER), "collection"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert blocked.returncode == 75
    assert '"lock_busy"' in blocked.stdout
    # Curation reaches its independent input gate, proving it did not share the collection lock.
    curation = subprocess.run([str(RUNNER), "curation"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert curation.returncode != 75
    assert not (state / "curation.lock").exists()


def test_hermes_row_flows_to_ledger_packet_and_callback(tmp_path):
    state = tmp_path / "state"
    inbox = tmp_path / "hermes.sqlite"
    intake_ids = [f"intake_AbCdEf0123456789_XyZ{index}" for index in range(4)]
    con = sqlite3.connect(inbox)
    con.execute("CREATE TABLE links (intake_id TEXT, original_url TEXT, canonical_url TEXT, updated_at INTEGER)")
    for index, intake_id in enumerate(intake_ids):
        con.execute(
            "INSERT INTO links VALUES (?, ?, ?, ?)",
            (intake_id, f"https://example.com/original-{index}", f"https://example.com/canonical-{index}", index + 1),
        )
    con.commit(); con.close()
    sources = tmp_path / "sources.json"
    sources.write_text(json.dumps({"sources": [{"id": "hermes-links", "adapter": "hermes_link_inbox", "db_env": "STACK_TEST_HERMES_DB"}]}))
    catalog = tmp_path / "catalog.json"; catalog.write_text('{"capabilities": []}')
    callbacks = tmp_path / "callbacks.txt"
    fake = tmp_path / "fake-hermes.py"
    fake.write_text("import os, sys\nopen(os.environ['CALLBACKS'], 'a').write(' '.join(sys.argv[1:]) + '\\n')\n")
    env = {**os.environ, "STACK_BOOKMARK_STATE_ROOT": str(state), "STACK_BOOKMARK_SOURCES": str(sources),
           "STACK_TEST_HERMES_DB": str(inbox), "STACK_CAPABILITY_CATALOG": str(catalog),
           "HERMES_LINK_INBOX_SCRIPT": str(fake), "CALLBACKS": str(callbacks)}
    collected = subprocess.run([str(RUNNER), "collection", "--apply"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert collected.returncode == 0, collected.stderr
    curated = subprocess.run([str(RUNNER), "curation", "--apply"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert curated.returncode == 0, curated.stderr
    packet = json.loads(next((state / "receipts").glob("curation-*.json")).read_text())
    assert len(packet["candidates"]) == 3
    assert len(packet["deferred"]) == 1
    callback_text = callbacks.read_text()
    assert all(record["intake_id"] in callback_text for record in packet["candidates"])
    assert packet["deferred"][0]["intake_id"] not in callback_text
    assert "--state proposed" in callback_text
    remaining = tmp_path / "remaining.json"
    materialized = subprocess.run(
        ["python3", str(ROOT / "scripts/materialize-bookmark-candidates.py"), "--ledger", str(state / "bookmark-intake.sqlite"), "--out", str(remaining)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert materialized.returncode == 0, materialized.stderr
    assert [packet["deferred"][0]["intake_id"]] == [row["intake_id"] for row in json.loads(remaining.read_text())]


def test_failed_callback_leaves_partial_receipt_and_candidates_unmarked(tmp_path):
    state = tmp_path / "state"
    inbox = tmp_path / "hermes.sqlite"
    intake_id = "intake_AbCdEf0123456789_Callback"
    con = sqlite3.connect(inbox)
    con.execute("CREATE TABLE links (intake_id TEXT, original_url TEXT, canonical_url TEXT, updated_at INTEGER)")
    con.execute("INSERT INTO links VALUES (?, ?, ?, ?)", (intake_id, "https://example.com/original", "https://example.com/canonical", 1))
    con.commit(); con.close()
    sources = tmp_path / "sources.json"
    sources.write_text(json.dumps({"sources": [{"id": "hermes-links", "adapter": "hermes_link_inbox", "db_env": "STACK_TEST_HERMES_DB"}]}))
    catalog = tmp_path / "catalog.json"; catalog.write_text('{"capabilities": []}')
    failing = tmp_path / "failing.py"; failing.write_text("raise SystemExit(9)\n")
    env = {**os.environ, "STACK_BOOKMARK_STATE_ROOT": str(state), "STACK_BOOKMARK_SOURCES": str(sources),
           "STACK_TEST_HERMES_DB": str(inbox), "STACK_CAPABILITY_CATALOG": str(catalog), "HERMES_LINK_INBOX_SCRIPT": str(failing)}
    assert subprocess.run([str(RUNNER), "collection", "--apply"], cwd=ROOT, env=env).returncode == 0
    failed = subprocess.run([str(RUNNER), "curation", "--manual", "--apply"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert failed.returncode != 0
    receipt = json.loads(next((state / "receipts").glob("curation-*.json")).read_text())
    assert receipt["receipt_type"] == "partial" and receipt["complete"] is False
    assert receipt["manual_run"] is True and receipt["mode"] == "apply"
    remaining = subprocess.run(["python3", str(ROOT / "scripts/materialize-bookmark-candidates.py"), "--ledger", str(state / "bookmark-intake.sqlite")], cwd=ROOT, text=True, capture_output=True)
    assert remaining.returncode == 0
    assert [row["intake_id"] for row in json.loads(remaining.stdout)] == [intake_id]


def test_installer_is_dry_run_without_enablement(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}
    result = subprocess.run([str(INSTALLER)], cwd=ROOT, env=env, text=True, capture_output=True)
    assert result.returncode == 0
    assert "hermes cron create" in result.stdout
    assert "--enable" in result.stdout
    assert not (tmp_path / ".hermes" / "scripts" / "stack-bookmark-collection.sh").exists()


def test_installer_refuses_enablement_without_the_explicit_token(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}
    result = subprocess.run([str(INSTALLER), "--enable"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert result.returncode == 2
    assert "explicit approval token" in result.stderr


def test_installer_can_install_wrappers_without_creating_jobs(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}
    result = subprocess.run([str(INSTALLER), "--install-wrappers"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    collection = tmp_path / ".hermes/scripts/stack-bookmark-collection.sh"
    curation = tmp_path / ".hermes/scripts/stack-bookmark-curation.sh"
    assert collection.exists() and os.access(collection, os.X_OK)
    assert curation.exists() and os.access(curation, os.X_OK)
    assert "--dry-run" in collection.read_text()
    assert "STACK_HERMES_LINK_INBOX_DB" in collection.read_text()
    assert "collection --manual --apply" in collection.read_text()
    assert "collection --apply" in collection.read_text()
    assert "--manual" in curation.read_text()
    assert "HERMES_LINK_INBOX_SCRIPT" in curation.read_text()
    assert "curation --manual --apply" in curation.read_text()
    assert "curation --apply" in curation.read_text()
    assert "no cron jobs were created" in result.stdout


def test_installer_uses_exact_cron_argv_with_separate_wrappers(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    argv_log = tmp_path / "argv.log"
    fake = fake_bin / "hermes"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$1 $2\" == 'cron status' ]]; then echo 'Gateway is running'; exit 0; fi\n"
        "if [[ \"$1 $2\" == 'cron list' ]]; then exit 0; fi\n"
        "printf '%s\\n' \"$*\" >> \"$HERMES_ARGV_LOG\"\n"
        "if [[ \"$1 $2\" == 'cron create' ]]; then\n"
        "  name=''\n"
        "  for ((i=1; i<=$#; i++)); do if [[ \"${!i}\" == '--name' ]]; then j=$((i+1)); name=\"${!j}\"; fi; done\n"
        "  echo \"Created job: job-$name\"\n"
        "fi\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    receipts = _verification_receipts(tmp_path / "receipts")
    env = {**os.environ, "HOME": str(tmp_path / "home"), "PATH": f"{fake_bin}:{os.environ['PATH']}", "HERMES_ARGV_LOG": str(argv_log), "STACK_HERMES_VERIFICATION_DIR": str(receipts)}
    installed = subprocess.run([str(INSTALLER), "--install-wrappers"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert installed.returncode == 0, installed.stderr
    result = subprocess.run([str(INSTALLER), "--enable", "--approval-token", "I_APPROVE_HERMES_STACK_CURATION"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    collection, curation = argv_log.read_text().splitlines()
    assert collection == "cron create 17 1 * * * --name stack-bookmark-collection --script stack-bookmark-collection.sh --no-agent"
    assert curation == "cron create 23 9 * * 1 --name stack-bookmark-curation --script stack-bookmark-curation.sh --no-agent"


def test_installer_rejects_the_explicit_stopped_gateway_status(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "hermes"
    fake.write_text("#!/usr/bin/env bash\necho 'Gateway is not running'\n", encoding="utf-8")
    fake.chmod(0o755)
    receipts = _verification_receipts(tmp_path / "receipts")
    env = {**os.environ, "HOME": str(tmp_path / "home"), "PATH": f"{fake_bin}:{os.environ['PATH']}", "STACK_HERMES_VERIFICATION_DIR": str(receipts)}
    installed = subprocess.run([str(INSTALLER), "--install-wrappers"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert installed.returncode == 0, installed.stderr
    result = subprocess.run([str(INSTALLER), "--enable", "--approval-token", "I_APPROVE_HERMES_STACK_CURATION"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert result.returncode == 3
    assert "gateway is not running" in result.stderr.lower()


class StackBookmarkCurationTests(unittest.TestCase):
    """Expose the fixture-style tests to the dependency-free unittest suite."""


def _unittest_case(test_function):
    def run(self):
        with tempfile.TemporaryDirectory() as temporary:
            test_function(Path(temporary))

    return run


for _name, _test in tuple(globals().items()):
    if _name.startswith("test_") and callable(_test):
        setattr(StackBookmarkCurationTests, _name, _unittest_case(_test))
