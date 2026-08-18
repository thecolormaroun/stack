from __future__ import annotations

import importlib.util
import hashlib
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


def test_source_audit_resolves_catalog_local_report_only_and_retired_rows(tmp_path: Path):
    maintenance = _module()
    policy = maintenance.load_policy(POLICY)
    sources = maintenance.load_sources(SOURCES)
    report = maintenance.audit_sources(ROOT, policy=policy, sources=sources)
    assert report["status"] == "passed"
    rows = {row["source_id"]: row for row in report["sources"]}
    assert rows["gstack"]["provider_id"] == "gstack"
    assert rows["impeccable"]["disposition"] == "repository-owned-capability"
    assert rows["illo-skill"]["plugin_commands_invoked"] == []
    assert rows["global-skill-roots"]["retired"] is True
    assert report["plugin_commands_invoked"] == []
    assert {row.get("provider_id") for row in rows.values() if row.get("provider_id")} == {
        "compound-engineering",
        "david",
        "emil",
        "gstack",
        "matt",
        "stack-codex",
    }
    assert all("/Users/" not in json.dumps(report) for _ in (0,))


def test_source_audit_rejects_mutable_pin_and_unregistered_target(tmp_path: Path):
    maintenance = _module()
    policy = maintenance.load_policy(POLICY)
    sources = maintenance.load_sources(SOURCES)
    registry, lock = maintenance.load_upstream_metadata()
    mutable = json.loads(json.dumps(registry))
    mutable["providers"][0]["pin"] = {"type": "branch", "value": "main"}
    with unittest.TestCase().assertRaisesRegex(maintenance.PolicyError, "mutable_upstream_pin"):
        maintenance.validate_source_catalog(ROOT, policy, sources, mutable, lock)
    incomplete = json.loads(json.dumps(sources))
    incomplete["sources"] = incomplete["sources"][:-1]
    with unittest.TestCase().assertRaisesRegex(maintenance.PolicyError, "source_inventory_incomplete"):
        maintenance.validate_policy(policy, incomplete)


def test_upstream_observation_reports_drift_without_trusting_mutable_head(tmp_path: Path):
    maintenance = _module()
    registry, _ = maintenance.load_upstream_metadata()
    refs = {
        provider["id"]: provider["pin"]["value"]
        for provider in registry["providers"]
        if provider["pin"]["type"] == "git-commit"
    }
    refs["gstack"] = "f" * 40
    report = maintenance.audit_sources(ROOT, observed_refs=refs)
    observation = report["upstream_observation"]
    assert observation["status"] == "updates_available"
    assert observation["updates_available"] == ["gstack"]
    gstack = next(item for item in observation["observations"] if item["provider_id"] == "gstack")
    assert gstack["pin"] != gstack["observed_head"]
    assert report["plugin_commands_invoked"] == []
    with unittest.TestCase().assertRaisesRegex(maintenance.PolicyError, "observed_provider_set_invalid"):
        maintenance.audit_sources(ROOT, observed_refs={"gstack": "f" * 40})


def _git_fixture(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "fixture"], check=True)
    return path


def test_dirty_protected_vendor_blocks_and_verified_hold_allows_unrelated_audit(tmp_path: Path):
    vendor = _git_fixture(tmp_path / "vendor")
    (vendor / "README.md").write_text("held user work\n", encoding="utf-8")
    blocked = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "audit",
            "--state-dir",
            str(tmp_path / "blocked-state"),
            "--policy",
            str(POLICY),
            "--sources",
            str(SOURCES),
            "--vendor-path",
            str(vendor),
            "--run-id",
            "vendor-blocked",
            "--now",
            "1000",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert blocked.returncode != 0
    assert json.loads(blocked.stdout)["result"] == "protected_vendor_ambiguous"
    maintenance = _module()
    status_digest, _ = maintenance._git_status(vendor)
    head = maintenance._git(vendor, "rev-parse", "HEAD")
    hold = {
        "verified": True,
        "vendor_identity_digest": maintenance._vendor_identity(vendor),
        "status_digest": status_digest,
        "head": head,
    }
    report = maintenance.audit_sources(ROOT, protected_vendor=vendor, vendor_hold=hold)
    assert report["protected_vendor"]["status"] == "held"


def _vendor_evidence_fixture(tmp_path: Path):
    maintenance = _module()
    vendor = _git_fixture(tmp_path / "protected/vendor/gstack")
    base = maintenance._git(vendor, "rev-parse", "HEAD")
    (vendor / "README.md").write_text("preserved upstream tree\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(vendor), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(vendor), "commit", "-qm", "matching tree"], check=True)
    matching = maintenance._git(vendor, "rev-parse", "HEAD")
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(mode=0o700)
    patch = evidence_dir / "worktree.patch"
    subprocess.run(["git", "-C", str(vendor), "diff", "--binary", base, matching, f"--output={patch}"], check=True)
    patch.chmod(0o600)
    subprocess.run(["git", "-C", str(vendor), "checkout", "-q", base], check=True)
    subprocess.run(["git", "-C", str(vendor), "apply", "--binary", str(patch)], check=True)
    status_digest, status_lines = maintenance._git_status(vendor)
    manifest = evidence_dir / "manifest.json"
    manifest_value = {
        "schema_version": 1,
        "source": {"checkout": str(vendor), "head": base},
        "classification": {"matching_commit": matching, "unique_uncommitted_content": False},
        "artifact": {"file": patch.name, "sha256": hashlib.sha256(patch.read_bytes()).hexdigest()},
        "reconstruction": {"verified": True, "expected_commit": matching},
    }
    manifest.write_text(json.dumps(manifest_value), encoding="utf-8")
    manifest.chmod(0o600)
    hold = evidence_dir / "current-hold.json"
    hold_value = {
        "schema_version": 1,
        "verified": True,
        "vendor_identity_digest": maintenance._vendor_identity(vendor),
        "head": base,
        "status_digest": status_digest,
        "changed_entry_count": len(status_lines),
        "preservation_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "preservation_patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
    }
    hold.write_text(json.dumps(hold_value), encoding="utf-8")
    hold.chmod(0o600)
    return maintenance, vendor, hold, manifest, patch


def test_vendor_preservation_is_owner_only_and_reconstructable(tmp_path: Path):
    maintenance, vendor, hold, manifest, _patch = _vendor_evidence_fixture(tmp_path)
    before = maintenance._git_status(vendor)
    evidence = maintenance.validate_vendor_preservation(vendor, hold_path=hold, manifest_path=manifest)
    proof = maintenance.verify_vendor_reconstruction(manifest, vendor)
    assert evidence["reconstruction_verified"] is True
    assert proof["status"] == "verified"
    assert maintenance._git_status(vendor) == before


def test_vendor_preservation_rejects_incomplete_or_changed_evidence(tmp_path: Path):
    maintenance, vendor, hold, manifest, patch = _vendor_evidence_fixture(tmp_path)
    patch.write_bytes(patch.read_bytes() + b"\n")
    patch.chmod(0o600)
    with unittest.TestCase().assertRaisesRegex(maintenance.MaintenanceError, "vendor_patch_digest_mismatch"):
        maintenance.validate_vendor_preservation(vendor, hold_path=hold, manifest_path=manifest)
    patch.chmod(0o644)
    with unittest.TestCase().assertRaisesRegex(maintenance.MaintenanceError, "vendor_evidence_permissions_unsafe"):
        maintenance.validate_vendor_preservation(vendor, hold_path=hold, manifest_path=manifest)


def test_vendor_restoration_plan_is_exact_target_and_approval_bound(tmp_path: Path):
    maintenance, vendor, hold, manifest, _patch = _vendor_evidence_fixture(tmp_path)
    evidence = maintenance.validate_vendor_preservation(vendor, hold_path=hold, manifest_path=manifest)
    token = maintenance.vendor_restoration_approval_token(evidence)
    with unittest.TestCase().assertRaisesRegex(maintenance.MaintenanceError, "vendor_restoration_approval_required"):
        maintenance.build_vendor_restoration_plan(vendor, hold_path=hold, manifest_path=manifest, approval_token="wrong")
    plan = maintenance.build_vendor_restoration_plan(vendor, hold_path=hold, manifest_path=manifest, approval_token=token)
    assert plan["status"] == "approved_plan"
    assert plan["target_identity_digest"] == evidence["vendor_identity_digest"]
    assert plan["scheduled_execution_allowed"] is False
    with unittest.TestCase().assertRaisesRegex(maintenance.MaintenanceError, "vendor_target_too_broad"):
        maintenance.build_vendor_restoration_plan(Path("/"), hold_path=hold, manifest_path=manifest, approval_token=token)


def test_disposable_candidate_is_clean_base_allowlisted_and_private_data_safe(tmp_path: Path):
    maintenance = _module()
    caller_before = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=ROOT, text=True, capture_output=True, check=True).stdout
    stage = tmp_path / "candidate"
    candidate = maintenance.stage_candidate(
        ROOT,
        stage,
        allowlist=["docs/stack-maintenance.md"],
        proposed_files={"docs/stack-maintenance.md": "# candidate\n"},
        run_readiness_checks=False,
    )
    assert candidate["status"] == "changed"
    assert candidate["base_sha"] == subprocess.run(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    assert candidate["changed_paths"] == ["docs/stack-maintenance.md"]
    caller_after = subprocess.run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=ROOT, text=True, capture_output=True, check=True).stdout
    assert caller_before == caller_after
    with unittest.TestCase().assertRaisesRegex(maintenance.MaintenanceError, "candidate_private_data"):
        maintenance.stage_candidate(
            ROOT,
            tmp_path / "private-candidate",
            allowlist=["docs/stack-maintenance.md"],
            proposed_files={"docs/stack-maintenance.md": "secret /Users/maroun/private\n"},
            run_readiness_checks=False,
        )
    with unittest.TestCase().assertRaisesRegex(maintenance.MaintenanceError, "candidate_path_not_allowlisted"):
        maintenance.stage_candidate(
            ROOT,
            tmp_path / "unallowlisted-candidate",
            allowlist=["docs/stack-maintenance.md"],
            proposed_files={"README.md": "unexpected\n"},
            run_readiness_checks=False,
        )


def test_semantic_json_digest_ignores_observation_only_provenance_fields(tmp_path: Path):
    maintenance = _module()
    first = b'{"checked_at":"2026-08-18T00:00:00Z","latest_commit":{"sha":"abc"}}\n'
    second = b'{"checked_at":"2026-08-19T00:00:00Z","latest_commit":{"sha":"abc"}}\n'
    assert maintenance.semantic_bytes_digest(first, Path("source.json")) == maintenance.semantic_bytes_digest(second, Path("source.json"))


def _candidate_fixture(tmp_path: Path):
    maintenance = _module()
    root = _git_fixture(tmp_path / "stack")
    (root / "docs").mkdir()
    (root / "docs" / "candidate.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "docs/candidate.md"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "base candidate"], check=True)
    base = maintenance._git(root, "rev-parse", "HEAD")
    stage = tmp_path / "stage"
    maintenance.stage_candidate(
        root,
        stage,
        base_sha=base,
        allowlist=["docs/candidate.md"],
        proposed_files={"docs/candidate.md": "candidate\n"},
        run_readiness_checks=False,
    )
    return maintenance, root, stage, base


class _FakeGitHub:
    def __init__(self, maintenance, *, records=None, push_error=None, create_error=None):
        self.maintenance = maintenance
        self.records = list(records or [])
        self.remote = None
        self.push_error = push_error
        self.create_error = create_error
        self.push_calls = 0
        self.create_calls = 0

    def list_open_candidates(self, repository, branch, marker):
        return list(self.records)

    def remote_branch(self, repository, branch):
        return self.remote

    def push_branch(self, repository, branch, stage_dir, *, expected_remote_head=None):
        self.push_calls += 1
        if self.push_error:
            raise self.maintenance.MaintenanceError(self.push_error, "transient")
        head = self.maintenance._git(stage_dir, "rev-parse", "HEAD")
        self.remote = {"sha": head}
        return {"branch": branch, "head_sha": head}

    def create_draft_pr(self, repository, branch, title, body, *, labels=None):
        self.create_calls += 1
        if self.create_error:
            raise self.maintenance.MaintenanceError(self.create_error, "transient")
        head = self.remote["sha"]
        self.records = [{
            "number": 41,
            "head_ref_name": branch,
            "base_ref_name": "main",
            "head_sha": head,
            "base_sha": self.maintenance._body_metadata(body, "base-sha"),
            "changed_paths_digest": self.maintenance._body_metadata(body, "changed-paths-digest"),
            "commit_count": 1,
            "commits": [head],
            "body": body,
            "url": "https://github.com/thecolormaroun/stack/pull/41",
        }]
        return {"number": 41, "url": self.records[0]["url"]}


def _lane(maintenance, root, stage, base, github, *, expected_digest=None):
    return maintenance.prepare_canonical_pr(
        root,
        stage,
        base_sha=base,
        allowlist=["docs/candidate.md"],
        input_fingerprint_value="a" * 64,
        github=github,
        readiness_runner=lambda _stage: {"status": "passed", "checks": ["fixture-gate"]},
        expected_changed_paths_digest=expected_digest,
    )


def test_canonical_lane_creates_one_draft_pr_from_clean_allowlisted_base(tmp_path: Path):
    maintenance, root, stage, base = _candidate_fixture(tmp_path)
    github = _FakeGitHub(maintenance)
    result = _lane(maintenance, root, stage, base, github)
    assert result["terminal_classification"] == "prepared"
    assert result["result"] == "draft_pr_created"
    assert result["pr_state"]["status"] == "created"
    assert result["pr_state"]["base_sha"] == base
    assert result["checks"]["changed_paths_digest_verified"] is True
    assert github.push_calls == 1
    assert github.create_calls == 1
    assert not maintenance._status_entries(stage)


def test_canonical_lane_reuses_safe_candidate_and_missing_labels_are_informational(tmp_path: Path):
    maintenance, root, stage, base = _candidate_fixture(tmp_path)
    github = _FakeGitHub(maintenance)
    created = _lane(maintenance, root, stage, base, github)
    digest_value = created["changed_paths_digest"]
    reused = _lane(maintenance, root, None, base, github, expected_digest=digest_value)
    assert reused["terminal_classification"] == "prepared"
    assert reused["result"] == "canonical_pr_reused"
    assert reused["checks"]["optional_labels_missing"] is True
    assert github.push_calls == 1
    assert github.create_calls == 1


def test_canonical_lane_blocks_duplicate_candidates_before_remote_mutation(tmp_path: Path):
    maintenance, root, stage, base = _candidate_fixture(tmp_path)
    records = [{"number": 1, "head_ref_name": "automation/stack-maintenance"}, {"number": 2, "head_ref_name": "automation/stack-maintenance"}]
    github = _FakeGitHub(maintenance, records=records)
    result = _lane(maintenance, root, stage, base, github)
    assert result["terminal_classification"] == "blocked"
    assert result["result"] == "canonical_pr_ambiguous"
    assert github.push_calls == 0
    assert github.create_calls == 0


def test_canonical_lane_rejects_unrelated_staged_path_before_commit_or_push(tmp_path: Path):
    maintenance, root, stage, base = _candidate_fixture(tmp_path)
    (stage / "README.md").write_text("unrelated\n", encoding="utf-8")
    github = _FakeGitHub(maintenance)
    result = _lane(maintenance, root, stage, base, github)
    assert result["result"] == "candidate_diff_not_allowlisted"
    assert github.push_calls == 0
    assert github.create_calls == 0
    assert any(entry["path"] == "README.md" for entry in maintenance._status_entries(stage))


def test_canonical_lane_push_failure_keeps_recoverable_stage_and_receipt_shape(tmp_path: Path):
    maintenance, root, stage, base = _candidate_fixture(tmp_path)
    github = _FakeGitHub(maintenance, push_error="github_push_failed")
    result = _lane(maintenance, root, stage, base, github)
    assert result["terminal_classification"] == "partial"
    assert result["result"] == "github_push_failed"
    assert result["stage_retained"] is True
    assert result["checks"]["remote_mutation_started"] is False
    assert stage.exists()


def test_canonical_lane_pr_create_failure_records_remote_branch_and_retains_stage(tmp_path: Path):
    maintenance, root, stage, base = _candidate_fixture(tmp_path)
    github = _FakeGitHub(maintenance, create_error="github_pr_create_failed")
    result = _lane(maintenance, root, stage, base, github)
    assert result["terminal_classification"] == "partial"
    assert result["result"] == "github_pr_create_failed"
    assert result["pr_state"]["status"] == "branch_pushed"
    assert result["checks"]["remote_mutation_started"] is True
    assert result["checks"]["recoverable_stage"] is True
    assert stage.exists()


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
