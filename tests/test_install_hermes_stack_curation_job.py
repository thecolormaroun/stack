from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-hermes-stack-curation-job.sh"


def _fake_hermes(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv = tmp_path / "argv.log"
    command = bin_dir / "hermes"
    command.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$1 $2\" == 'cron status' ]]; then echo 'Gateway is running'; exit 0; fi\n"
        "if [[ \"$1 $2\" == 'cron list' ]]; then cat \"$HERMES_JOBS_FILE\" 2>/dev/null || true; exit 0; fi\n"
        "printf '%s\\n' \"$*\" >> \"$HERMES_ARGV_LOG\"\n"
        "if [[ \"$1 $2\" == 'cron create' ]]; then\n"
        "  name=''\n"
        "  for ((i=1; i<=$#; i++)); do\n"
        "    if [[ \"${!i}\" == '--name' ]]; then j=$((i+1)); name=\"${!j}\"; fi\n"
        "  done\n"
        "  if [[ \"${HERMES_FAIL_CREATE_NAME:-}\" == \"$name\" ]]; then echo \"injected create failure\" >&2; exit 1; fi\n"
        "  id=\"job-$name\"\n"
        "  printf '%s %s\\n' \"$id\" \"$name\" >> \"$HERMES_JOBS_FILE\"\n"
        "  echo \"Created job: $id\"\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$1 $2\" == 'cron remove' ]]; then\n"
        "  id=\"$3\"\n"
        "  if [[ -f \"$HERMES_JOBS_FILE\" ]]; then grep -v \"^$id \" \"$HERMES_JOBS_FILE\" > \"$HERMES_JOBS_FILE.next\" || true; mv \"$HERMES_JOBS_FILE.next\" \"$HERMES_JOBS_FILE\"; fi\n"
        "  exit 0\n"
        "fi\n",
        encoding="utf-8",
    )
    command.chmod(0o755)
    return bin_dir, argv


def _receipts(root: Path, *, partial: bool = False, stale: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    for phase in ("collection", "curation"):
        receipt = root / f"{phase}-proof.json"
        receipt.write_text(json.dumps({"receipt_type": phase, "phase": phase, "complete": not partial, "manual_run": True, "mode": "apply"}), encoding="utf-8")
        receipt.chmod(0o600)
        if stale:
            old = time.time() - 90_000
            os.utime(receipt, (old, old))
    return root


def _env(tmp_path: Path, bin_dir: Path, argv: Path, receipts: Path) -> dict[str, str]:
    return {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HERMES_ARGV_LOG": str(argv),
        "HERMES_JOBS_FILE": str(argv.with_name("jobs.log")),
        "STACK_HERMES_VERIFICATION_DIR": str(receipts),
    }


def test_enable_fails_closed_for_missing_stale_or_partial_manual_receipts(tmp_path):
    bin_dir, argv = _fake_hermes(tmp_path)
    receipts = _receipts(tmp_path / "receipts")
    env = _env(tmp_path, bin_dir, argv, receipts)
    assert subprocess.run([str(INSTALLER), "--install-wrappers"], cwd=ROOT, env=env, text=True, capture_output=True).returncode == 0
    for path in receipts.iterdir():
        path.unlink()
    receipts.rmdir()
    missing = subprocess.run([str(INSTALLER), "--enable", "--approval-token", "I_APPROVE_HERMES_STACK_CURATION"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert missing.returncode == 5
    _receipts(receipts, stale=True)
    stale = subprocess.run([str(INSTALLER), "--enable", "--approval-token", "I_APPROVE_HERMES_STACK_CURATION"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert stale.returncode == 5
    for path in receipts.iterdir(): path.unlink()
    _receipts(receipts, partial=True)
    partial = subprocess.run([str(INSTALLER), "--enable", "--approval-token", "I_APPROVE_HERMES_STACK_CURATION"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert partial.returncode == 5


def test_enable_requires_receipts_then_uses_exact_cron_argv(tmp_path):
    bin_dir, argv = _fake_hermes(tmp_path)
    receipts = _receipts(tmp_path / "receipts")
    env = _env(tmp_path, bin_dir, argv, receipts)
    installed = subprocess.run([str(INSTALLER), "--install-wrappers"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert installed.returncode == 0, installed.stderr
    result = subprocess.run([str(INSTALLER), "--enable", "--approval-token", "I_APPROVE_HERMES_STACK_CURATION"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    collection, curation = argv.read_text().splitlines()
    assert collection == "cron create 17 1 * * * --name stack-bookmark-collection --script stack-bookmark-collection.sh --no-agent"
    assert curation == "cron create 23 9 * * 1 --name stack-bookmark-curation --script stack-bookmark-curation.sh --no-agent"


def test_enable_accepts_operational_collection_with_an_inaccessible_link(tmp_path):
    bin_dir, argv = _fake_hermes(tmp_path)
    receipts = _receipts(tmp_path / "receipts")
    collection = receipts / "collection-proof.json"
    collection.write_text(
        json.dumps(
            {
                "receipt_type": "partial",
                "phase": "collection",
                "complete": False,
                "manual_run": True,
                "mode": "apply",
                "sources": [
                    {"source_id": "github-stars", "status": "ok"},
                    {"source_id": "github-linked", "status": "partial_repository_inaccessible"},
                ],
            }
        ),
        encoding="utf-8",
    )
    collection.chmod(0o600)
    env = _env(tmp_path, bin_dir, argv, receipts)

    installed = subprocess.run([str(INSTALLER), "--install-wrappers"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert installed.returncode == 0, installed.stderr
    result = subprocess.run([str(INSTALLER), "--enable", "--approval-token", "I_APPROVE_HERMES_STACK_CURATION"], cwd=ROOT, env=env, text=True, capture_output=True)

    assert result.returncode == 0, result.stderr


def test_installs_wrappers_under_explicit_hermes_home(tmp_path):
    bin_dir, argv = _fake_hermes(tmp_path)
    receipts = _receipts(tmp_path / "receipts")
    env = _env(tmp_path, bin_dir, argv, receipts)
    hermes_home = tmp_path / "running-hermes"
    env["HERMES_HOME"] = str(hermes_home)

    result = subprocess.run([str(INSTALLER), "--install-wrappers"], cwd=ROOT, env=env, text=True, capture_output=True)

    assert result.returncode == 0, result.stderr
    assert (hermes_home / "scripts/stack-bookmark-collection.sh").is_file()
    assert (hermes_home / "scripts/stack-bookmark-curation.sh").is_file()


def test_second_create_failure_compensates_first_job(tmp_path):
    bin_dir, argv = _fake_hermes(tmp_path)
    receipts = _receipts(tmp_path / "receipts")
    env = _env(tmp_path, bin_dir, argv, receipts)
    env["HERMES_FAIL_CREATE_NAME"] = "stack-bookmark-curation"
    installed = subprocess.run([str(INSTALLER), "--install-wrappers"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert installed.returncode == 0, installed.stderr

    result = subprocess.run(
        [str(INSTALLER), "--enable", "--approval-token", "I_APPROVE_HERMES_STACK_CURATION"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 8
    commands = argv.read_text().splitlines()
    assert commands[-1] == "cron remove job-stack-bookmark-collection"
    jobs = Path(env["HERMES_JOBS_FILE"])
    assert not jobs.read_text().strip()


class HermesCurationInstallerTests(unittest.TestCase):
    """Expose the fixture-style tests to the dependency-free unittest suite."""


def _unittest_case(test_function):
    def run(self):
        with tempfile.TemporaryDirectory() as temporary:
            test_function(Path(temporary))

    return run


for _name, _test in tuple(globals().items()):
    if _name.startswith("test_") and callable(_test):
        setattr(HermesCurationInstallerTests, _name, _unittest_case(_test))
