from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "stack-maintenance.py"
POLICY = ROOT / "config" / "stack-maintenance.json"
SOURCES = ROOT / "registry" / "maintenance-sources.json"


def _module():
    spec = importlib.util.spec_from_file_location("stack_maintenance", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run(state: Path, *extra: str, now: float = 1000.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "audit",
            "--state-dir",
            str(state),
            "--policy",
            str(POLICY),
            "--sources",
            str(SOURCES),
            "--now",
            str(now),
            *extra,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_lease(state: Path, *, owner: str, fingerprint: str, expires_at: float) -> None:
    state.mkdir(parents=True, exist_ok=True)
    state.chmod(0o700)
    payload = {
        "schema_version": 1,
        "task_id": "stack-maintenance",
        "run_id": "held-run",
        "owner_id": owner,
        "input_fingerprint": fingerprint,
        "acquired_at": expires_at - 100,
        "expires_at": expires_at,
    }
    lease = state / "stack-maintenance.lease.json"
    lease.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    lease.chmod(0o600)


def test_policy_inventory_and_schema_are_valid(tmp_path: Path):
    maintenance = _module()
    policy = maintenance.load_policy(POLICY)
    sources = maintenance.load_sources(SOURCES)
    maintenance.validate_policy(policy, sources)
    schema = json.loads((ROOT / "registry/stack-maintenance-receipt.schema.json").read_text())
    assert schema["$schema"].endswith("2020-12/schema")
    assert {item["disposition"] for item in sources["sources"]} == {
        "catalog-managed-provider",
        "repository-owned-capability",
        "report-only-external-plugin",
        "retired-legacy-target",
    }


def test_audit_receipt_is_owner_only_and_fingerprint_ignores_observation_time(tmp_path: Path):
    first = _run(tmp_path / "state", "--run-id", "proof-one", now=1000.0)
    assert first.returncode == 0, first.stderr
    second = _run(tmp_path / "state", "--run-id", "proof-two", now=2000.0)
    assert second.returncode == 0, second.stderr
    receipts = sorted((tmp_path / "state" / "receipts").glob("*.json"))
    assert len(receipts) == 2
    first_receipt, second_receipt = (json.loads(path.read_text()) for path in receipts)
    maintenance = _module()
    maintenance.validate_receipt(first_receipt)
    maintenance.validate_receipt(second_receipt)
    assert first_receipt["terminal_classification"] == "no_action"
    assert first_receipt["input_fingerprint"] == second_receipt["input_fingerprint"]
    assert first_receipt["observed_at"] != second_receipt["observed_at"]
    assert all("/Users/" not in path.read_text() for path in receipts)
    assert stat.S_IMODE((tmp_path / "state").stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in receipts)


def test_malformed_policy_fails_closed_with_a_terminal_receipt(tmp_path: Path):
    policy = tmp_path / "malformed-policy.json"
    shutil.copyfile(POLICY, policy)
    data = json.loads(policy.read_text())
    data["allowed_modes"] = ["audit", "publish"]
    policy.write_text(json.dumps(data), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "audit",
            "--state-dir",
            str(tmp_path / "state"),
            "--policy",
            str(policy),
            "--sources",
            str(SOURCES),
            "--run-id",
            "malformed-policy",
            "--now",
            "1000",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    receipt = json.loads((tmp_path / "state/receipts/malformed-policy.json").read_text())
    assert receipt["terminal_classification"] == "failed"
    assert receipt["reason_code"] == "policy_modes_invalid"
    assert str(policy) not in result.stdout


def test_duplicate_active_lease_is_blocked_without_stage_write(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    state.chmod(0o700)
    maintenance = _module()
    policy = maintenance.load_policy(POLICY)
    sources = maintenance.load_sources(SOURCES)
    fingerprint = maintenance.input_fingerprint(policy, sources)
    _write_lease(state, owner="other-runner", fingerprint=fingerprint, expires_at=5000.0)
    stage = tmp_path / "stage"
    result = _run(state, "--stage-dir", str(stage), now=1000.0)
    assert result.returncode != 0
    assert "duplicate_active_run" in result.stdout
    assert not stage.exists()
    assert (state / "stack-maintenance.lease.json").exists()


def test_stale_lease_mismatch_requires_manual_audit_then_recovers(tmp_path: Path):
    state = tmp_path / "state"
    maintenance = _module()
    policy = maintenance.load_policy(POLICY)
    sources = maintenance.load_sources(SOURCES)
    fingerprint = maintenance.input_fingerprint(policy, sources)
    _write_lease(state, owner="different-owner", fingerprint=fingerprint, expires_at=900.0)
    blocked = _run(state, "--owner-id", "current-owner", now=1000.0)
    assert blocked.returncode != 0
    assert "stale_lease_mismatch" in blocked.stdout
    assert (state / "stack-maintenance.lease.json").exists()
    recovered = _run(state, "--owner-id", "current-owner", "--manual-audit", now=1000.0)
    assert recovered.returncode == 0, recovered.stderr
    assert json.loads(recovered.stdout)["manual_audit_cleared"] is True
    assert not (state / "stack-maintenance.lease.json").exists()


def test_three_identical_non_transient_blockers_open_circuit_and_manual_clear(tmp_path: Path):
    state = tmp_path / "state"
    for index in range(3):
        _write_lease(state, owner="different-owner", fingerprint="same-input", expires_at=900.0)
        result = _run(state, "--owner-id", "current-owner", now=1000.0 + index)
        assert result.returncode != 0
    circuit = json.loads((state / "stack-maintenance.circuit.json").read_text())
    assert circuit["open"] is True
    assert circuit["strike_count"] == 3
    cheap = _run(state, "--owner-id", "current-owner", now=2000.0)
    assert cheap.returncode != 0
    assert "circuit_open" in cheap.stdout
    cleared = _run(state, "--owner-id", "current-owner", "--manual-audit", now=3000.0)
    assert cleared.returncode == 0, cleared.stderr
    assert json.loads(cleared.stdout)["manual_audit_cleared"] is True
    assert json.loads((state / "stack-maintenance.circuit.json").read_text())["open"] is False


def test_unsafe_state_permissions_emit_only_redacted_terminal_record(tmp_path: Path):
    state = tmp_path / "unsafe-state"
    state.mkdir(mode=0o755)
    state.chmod(0o755)
    result = _run(state, "--run-id", "unsafe-proof")
    assert result.returncode != 0
    assert result.stdout == ""
    lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["terminal_classification"] == "failed"
    assert record["receipt_persisted"] is False
    assert "unsafe-state" not in result.stderr
    assert not (state / "receipts").exists()


class StackMaintenanceTests(unittest.TestCase):
    """Expose pytest-style scenario functions to the repository unittest gate."""


def _unittest_case(test_function):
    def run(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            test_function(Path(temporary))

    return run


for _name, _test in tuple(globals().items()):
    if _name.startswith("test_") and callable(_test):
        setattr(StackMaintenanceTests, _name, _unittest_case(_test))
