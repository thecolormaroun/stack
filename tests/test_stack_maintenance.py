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
from unittest import mock
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


def test_stack_verification_fetches_origin_main_for_maintenance_tests(tmp_path: Path):
    workflow = (ROOT / ".github/workflows/security-scan.yml").read_text(encoding="utf-8")
    stack_verification = workflow.split("  gitleaks:", maxsplit=1)[0]
    assert (
        "      - name: Checkout\n"
        "        uses: actions/checkout@v6\n"
        "        with:\n"
        "          fetch-depth: 0\n"
    ) in stack_verification


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
    assert first_receipt["checks"]["semantic_output_digest"] == second_receipt["checks"]["semantic_output_digest"]
    assert first_receipt["thread_state"]["status"] == "archive_eligible"
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


def test_missing_or_nonpositive_policy_lease_fails_into_receipt(tmp_path: Path):
    for index, lease_value in enumerate((None, 0, -1, 300)):
        policy = tmp_path / f"lease-policy-{index}.json"
        data = json.loads(POLICY.read_text())
        if lease_value is None:
            data["state"].pop("lease_seconds")
        else:
            data["state"]["lease_seconds"] = lease_value
        policy.write_text(json.dumps(data), encoding="utf-8")
        state = tmp_path / f"state-{index}"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "audit",
                "--state-dir",
                str(state),
                "--policy",
                str(policy),
                "--sources",
                str(SOURCES),
                "--run-id",
                f"bad-lease-{index}",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0
        receipt = json.loads((state / "receipts" / f"bad-lease-{index}.json").read_text())
        assert receipt["terminal_classification"] == "failed"
        assert receipt["reason_code"] == "lease_seconds_invalid"


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


def test_live_execution_lock_blocks_recovery_after_lease_expiry(tmp_path: Path):
    maintenance = _module()
    paths = maintenance.initialize_state_dir(tmp_path / "state")
    first = maintenance.acquire_lease(
        paths,
        run_id="first-run",
        owner_id="same-owner",
        input_fp="same-input",
        now=1000.0,
        lease_seconds=600,
    )
    try:
        second = maintenance.acquire_lease(
            paths,
            run_id="second-run",
            owner_id="same-owner",
            input_fp="same-input",
            now=2000.0,
            lease_seconds=600,
        )
        assert second["status"] == "active"
        assert second["liveness"] == "locked"
    finally:
        maintenance.release_lease(
            paths,
            run_id="first-run",
            owner_id="same-owner",
            lock_fd=first.get("lock_fd"),
        )
    assert paths["lock"].is_file()
    assert stat.S_IMODE(paths["lock"].stat().st_mode) == 0o600


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


def test_failed_manual_audit_does_not_clear_open_circuit(tmp_path: Path):
    state = tmp_path / "state"
    for index in range(3):
        _write_lease(state, owner="different-owner", fingerprint="same-input", expires_at=900.0)
        result = _run(state, "--owner-id", "current-owner", now=1000.0 + index)
        assert result.returncode != 0
    failed = _run(
        state,
        "--owner-id",
        "current-owner",
        "--manual-audit",
        "--vendor-path",
        str(tmp_path / "missing-vendor"),
        now=2000.0,
    )
    assert failed.returncode != 0
    assert json.loads((state / "stack-maintenance.circuit.json").read_text())["open"] is True


def test_non_transient_proposal_failures_open_circuit(tmp_path: Path):
    maintenance = _module()
    base_sha = maintenance._git(ROOT, "rev-parse", "origin/main")
    state = tmp_path / "state"
    checks = {
        "source_audit": {"checkout": {"base_sha": base_sha}},
        "source_updates_available": True,
        "caller_checkout": {"status": "clean", "base_sha": base_sha, "head_sha": base_sha},
    }
    with (
        mock.patch.object(maintenance, "_preflight", return_value=checks),
        mock.patch.object(
            maintenance,
            "materialize_proposal_from_receipt",
            side_effect=maintenance.MaintenanceError("mapped_skill_missing", "non_transient"),
        ),
    ):
        for index in range(3):
            receipt = maintenance.run(
                mode="prepare",
                state_dir=state,
                run_id=f"proposal-failure-{index}",
                owner_id="test-owner",
                now=1000.0 + index,
                stage_dir=tmp_path / f"stage-{index}",
                root=ROOT,
                audit_receipt_path=tmp_path / "audit-receipt.json",
                proposal_dir=tmp_path / f"proposal-{index}",
            )
            assert receipt["terminal_classification"] == "blocked"
            assert receipt["result"] == "mapped_skill_missing"
    circuit = json.loads((state / "stack-maintenance.circuit.json").read_text())
    assert circuit["open"] is True
    assert circuit["strike_count"] == 3


def test_materializer_network_failure_remains_retryable(tmp_path: Path):
    maintenance = _module()
    assert maintenance._materializer_failure_retry_class("upstream_fetch_failed") == "transient"
    assert maintenance._materializer_failure_retry_class("mapped_skill_missing") == "non_transient"


def test_success_resets_closed_circuit_strikes(tmp_path: Path):
    state = tmp_path / "state"
    _write_lease(state, owner="different-owner", fingerprint="same-input", expires_at=900.0)
    blocked = _run(state, "--owner-id", "current-owner", now=1000.0)
    assert blocked.returncode != 0
    assert json.loads((state / "stack-maintenance.circuit.json").read_text())["strike_count"] == 1
    (state / "stack-maintenance.lease.json").unlink()
    succeeded = _run(state, "--owner-id", "current-owner", now=1100.0)
    assert succeeded.returncode == 0, succeeded.stderr
    circuit = json.loads((state / "stack-maintenance.circuit.json").read_text())
    assert circuit["open"] is False
    assert circuit["strike_count"] == 0
    assert circuit["blocker_fingerprint"] is None


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


def test_caller_origin_identity_is_bound_to_github_host(tmp_path: Path):
    maintenance = _module()
    repository = _git_fixture(tmp_path / "repository")
    subprocess.run(
        ["git", "-C", str(repository), "remote", "add", "origin", "https://evil.example/thecolormaroun/stack.git"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "update-ref", "refs/remotes/origin/main", "HEAD"],
        check=True,
    )

    with unittest.TestCase().assertRaisesRegex(maintenance.MaintenanceError, "origin_mismatch"):
        maintenance._verify_origin_and_base(repository, "thecolormaroun/stack")

    assert maintenance._origin_identity("git@github.com:thecolormaroun/stack.git") == (
        "github.com/thecolormaroun/stack"
    )


def test_caller_preflight_fingerprints_every_linked_worktree(tmp_path: Path):
    maintenance = _module()
    repository = _git_fixture(tmp_path / "repository")
    subprocess.run(
        ["git", "-C", str(repository), "remote", "add", "origin", "https://github.com/thecolormaroun/stack.git"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "update-ref", "refs/remotes/origin/main", "HEAD"],
        check=True,
    )
    secondary = tmp_path / "secondary"
    subprocess.run(
        ["git", "-C", str(repository), "worktree", "add", "-qb", "secondary", str(secondary)],
        check=True,
    )
    (secondary / "README.md").write_text("dirty secondary worktree\n", encoding="utf-8")

    checkout = maintenance._verify_origin_and_base(repository, "thecolormaroun/stack")

    assert checkout["worktrees"]["count"] == 2
    assert checkout["worktrees"]["dirty_count"] == 1
    assert all("path" not in item for item in checkout["worktrees"]["entries"])
    assert all(len(item["identity_digest"]) == 64 for item in checkout["worktrees"]["entries"])


def test_dirty_protected_vendor_blocks_without_complete_preservation_evidence(tmp_path: Path):
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
    report = maintenance.audit_sources(
        ROOT,
        protected_vendor=vendor,
        vendor_hold_path=hold,
        vendor_manifest_path=manifest,
    )
    assert report["protected_vendor"]["status"] == "held"
    assert report["protected_vendor"]["reconstruction_verified"] is True


def test_vendor_preservation_rejects_incomplete_or_changed_evidence(tmp_path: Path):
    maintenance, vendor, hold, manifest, patch = _vendor_evidence_fixture(tmp_path)
    hold_value = json.loads(hold.read_text())
    hold_value["vendor_identity_digest"] = "0" * 64
    hold.write_text(json.dumps(hold_value), encoding="utf-8")
    hold.chmod(0o600)
    with unittest.TestCase().assertRaisesRegex(maintenance.MaintenanceError, "vendor_target_mismatch"):
        maintenance.validate_vendor_preservation(vendor, hold_path=hold, manifest_path=manifest)
    hold_value["vendor_identity_digest"] = maintenance._vendor_identity(vendor)
    hold.write_text(json.dumps(hold_value), encoding="utf-8")
    hold.chmod(0o600)
    patch.write_bytes(patch.read_bytes() + b"\n")
    patch.chmod(0o600)
    with unittest.TestCase().assertRaisesRegex(maintenance.MaintenanceError, "vendor_patch_digest_mismatch"):
        maintenance.validate_vendor_preservation(vendor, hold_path=hold, manifest_path=manifest)
    patch.chmod(0o644)
    with unittest.TestCase().assertRaisesRegex(maintenance.MaintenanceError, "vendor_evidence_permissions_unsafe"):
        maintenance.validate_vendor_preservation(vendor, hold_path=hold, manifest_path=manifest)


def test_vendor_audit_rejects_hold_without_manifest(tmp_path: Path):
    maintenance, vendor, hold, _manifest, _patch = _vendor_evidence_fixture(tmp_path)
    with unittest.TestCase().assertRaisesRegex(maintenance.MaintenanceError, "vendor_evidence_missing"):
        maintenance.audit_sources(
            ROOT,
            protected_vendor=vendor,
            vendor_hold_path=hold,
            vendor_manifest_path=tmp_path / "missing-manifest.json",
        )


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


def _reconciliation_fixture():
    return [
        {
            "item_id": "pr-23",
            "item_type": "pr",
            "base_sha": "1" * 40,
            "head_sha": "2" * 40,
            "content_class": "unique",
            "disposition": "excluded",
            "protected": True,
            "actions": [],
            "preservation": [{"kind": "active-branch", "reference": "codex/sol-high-default-routing"}],
        },
        {
            "item_id": "pr-25",
            "item_type": "pr",
            "base_sha": "1" * 40,
            "head_sha": "3" * 40,
            "content_class": "unique",
            "disposition": "replace",
            "actions": ["close_pr", "delete_branch"],
            "preservation": [
                {"kind": "git-bundle", "reference": "sha256:" + "4" * 64},
                {"kind": "active-branch", "reference": "codex/cost-effective-model-routing"},
            ],
            "content_groups": [
                {"class": "duplicate", "paths": ["skills/imported/emil/emil-design-eng/SKILL.md"]},
                {"class": "unique", "paths": ["scripts/codex-quota-preflight.sh"]},
            ],
        },
    ]


def test_reconciliation_splits_mixed_pr_and_protects_unrelated_pr(tmp_path: Path):
    maintenance = _module()
    packet = maintenance.build_reconciliation_packet(_reconciliation_fixture())
    assert packet["protected_exclusions"] == ["pr-23"]
    pr25 = next(item for item in packet["items"] if item["item_id"] == "pr-25")
    assert {group["class"] for group in pr25["content_groups"]} == {"duplicate", "unique"}
    assert packet["cleanup_targets"] == [{"item_id": "pr-25", "head_sha": "3" * 40, "actions": ["close_pr", "delete_branch"]}]


def test_reconciliation_refuses_unique_cleanup_without_preservation(tmp_path: Path):
    maintenance = _module()
    item = _reconciliation_fixture()[1]
    item["preservation"] = []
    with unittest.TestCase().assertRaisesRegex(maintenance.MaintenanceError, "unique_content_not_preserved"):
        maintenance.build_reconciliation_packet([item])


def test_cleanup_approval_is_bound_to_exact_live_sha(tmp_path: Path):
    maintenance = _module()
    packet = maintenance.build_reconciliation_packet(_reconciliation_fixture())
    token = maintenance.cleanup_approval_token(packet)
    with unittest.TestCase().assertRaisesRegex(maintenance.MaintenanceError, "cleanup_target_changed"):
        maintenance.build_cleanup_plan(packet, live_heads={"pr-25": "9" * 40}, approval_token=token)
    plan = maintenance.build_cleanup_plan(packet, live_heads={"pr-25": "3" * 40, "pr-23": "2" * 40}, approval_token=token)
    assert plan["protected_exclusions"] == ["pr-23"]
    assert plan["scheduled_execution_allowed"] is False


def test_partial_cleanup_result_never_claims_success(tmp_path: Path):
    maintenance = _module()
    packet = maintenance.build_reconciliation_packet(_reconciliation_fixture())
    plan = maintenance.build_cleanup_plan(
        packet,
        live_heads={"pr-25": "3" * 40},
        approval_token=maintenance.cleanup_approval_token(packet),
    )
    result = maintenance.classify_cleanup_result(plan, [])
    assert result["terminal_classification"] == "partial"
    assert result["remaining_item_ids"] == ["pr-25"]


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
            proposed_files={"docs/stack-maintenance.md": "secret /Users/" + "maroun/private\n"},
            run_readiness_checks=False,
        )


def test_candidate_secret_scan_covers_standard_github_token_prefixes(tmp_path: Path):
    maintenance = _module()
    for index, token in enumerate(("ghp_" + "a" * 36, "github_pat_" + "a" * 40)):
        with unittest.TestCase().assertRaisesRegex(maintenance.MaintenanceError, "candidate_private_data"):
            maintenance.stage_candidate(
                ROOT,
                tmp_path / f"secret-{index}",
                allowlist=["docs/stack-maintenance.md"],
                proposed_files={"docs/stack-maintenance.md": token + "\n"},
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


def test_proposal_manifest_is_confined_and_bound_to_origin_main(tmp_path: Path):
    maintenance = _module()
    proposal = tmp_path / "proposal"
    payload = proposal / "payload"
    payload.mkdir(parents=True)
    (payload / "runbook.md").write_text("# proposed\n", encoding="utf-8")
    registry_payload = payload / "registry.json"
    lock_payload = payload / "lock.json"
    registry_payload.write_bytes((ROOT / "registry/upstreams.json").read_bytes())
    lock_payload.write_bytes((ROOT / "upstreams.lock.json").read_bytes())
    gstack = next(row for row in json.loads(registry_payload.read_text())["providers"] if row["id"] == "gstack")
    base = subprocess.run(
        ["git", "rev-parse", "origin/main"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    receipt_digest = "e" * 64
    manifest = proposal / "manifest.json"
    manifest.write_text(
        json.dumps({
            "schema_version": 2,
            "generator": "scripts/materialize-maintenance-proposal.py",
            "base_sha": base,
            "audit_receipt_sha256": receipt_digest,
            "observation_digest": "a" * 64,
            "providers": [{
                "id": "gstack",
                "source": "https://github.com/garrytan/gstack.git",
                "pin": gstack["pin"]["value"],
                "license": gstack["license"],
                "content_digest": gstack["last_known_good"]["metadata_digest"],
            }],
            "files": [
                {
                    "path": "docs/stack-maintenance.md",
                    "source": "payload/runbook.md",
                    "sha256": hashlib.sha256(b"# proposed\n").hexdigest(),
                },
                {
                    "path": "registry/upstreams.json",
                    "source": "payload/registry.json",
                    "sha256": hashlib.sha256(registry_payload.read_bytes()).hexdigest(),
                },
                {
                    "path": "upstreams.lock.json",
                    "source": "payload/lock.json",
                    "sha256": hashlib.sha256(lock_payload.read_bytes()).hexdigest(),
                },
            ],
        }),
        encoding="utf-8",
    )
    loaded = maintenance._load_generated_proposal_manifest(
        manifest,
        expected_receipt_digest=receipt_digest,
    )
    assert loaded["docs/stack-maintenance.md"] == (payload / "runbook.md").resolve()
    assert set(loaded) == {"docs/stack-maintenance.md", "registry/upstreams.json", "upstreams.lock.json"}
    value = json.loads(manifest.read_text())
    value["base_sha"] = "f" * 40
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with unittest.TestCase().assertRaisesRegex(maintenance.MaintenanceError, "proposal_base_changed"):
        maintenance._load_generated_proposal_manifest(
            manifest,
            expected_receipt_digest=receipt_digest,
        )


def test_proposal_manifest_rejects_payload_digest_mismatch(tmp_path: Path):
    maintenance = _module()
    proposal = tmp_path / "proposal"
    payload = proposal / "payload"
    payload.mkdir(parents=True)
    source = payload / "runbook.md"
    source.write_text("# proposed\n", encoding="utf-8")
    base = maintenance._git(ROOT, "rev-parse", "origin/main")
    manifest = proposal / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": 2,
        "generator": "scripts/materialize-maintenance-proposal.py",
        "base_sha": base,
        "audit_receipt_sha256": "e" * 64,
        "observation_digest": "a" * 64,
        "providers": [{
            "id": "gstack",
            "source": "https://github.com/garrytan/gstack.git",
            "pin": "b" * 40,
            "license": "MIT",
            "content_digest": "c" * 64,
        }],
        "files": [{"path": "docs/stack-maintenance.md", "source": "payload/runbook.md", "sha256": "d" * 64}],
    }), encoding="utf-8")
    with unittest.TestCase().assertRaisesRegex(maintenance.MaintenanceError, "proposal_source_digest_mismatch"):
        maintenance._load_generated_proposal_manifest(
            manifest,
            expected_receipt_digest="e" * 64,
        )


def test_generated_proposal_rejects_audit_receipt_digest_mismatch(tmp_path: Path):
    maintenance = _module()
    proposal = tmp_path / "proposal"
    proposal.mkdir()
    manifest = proposal / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": 2,
        "generator": "scripts/materialize-maintenance-proposal.py",
        "base_sha": maintenance._git(ROOT, "rev-parse", "origin/main"),
        "audit_receipt_sha256": "a" * 64,
        "observation_digest": "b" * 64,
        "providers": [{
            "id": "gstack",
            "source": "https://github.com/garrytan/gstack.git",
            "pin": "c" * 40,
            "license": "MIT",
            "content_digest": "d" * 64,
        }],
        "files": [],
    }), encoding="utf-8")
    with unittest.TestCase().assertRaisesRegex(
        maintenance.MaintenanceError,
        "proposal_receipt_digest_mismatch",
    ):
        maintenance._load_generated_proposal_manifest(
            manifest,
            expected_receipt_digest="f" * 64,
        )


def test_cli_rejects_external_proposal_manifest_before_any_write(tmp_path: Path):
    forged = tmp_path / "forged-manifest.json"
    forged.write_text("{}\n", encoding="utf-8")
    state = tmp_path / "state"
    stage = tmp_path / "stage"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "prepare",
            "--state-dir",
            str(state),
            "--stage-dir",
            str(stage),
            "--proposal-manifest",
            str(forged),
            "--github",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unrecognized arguments: --proposal-manifest" in result.stderr
    assert not state.exists()
    assert not stage.exists()


def test_manual_recovery_flags_are_rejected_for_prepare(tmp_path: Path):
    for flag in ("--manual-audit", "--clear-circuit"):
        state = tmp_path / flag.removeprefix("--")
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "prepare",
                "--state-dir",
                str(state),
                "--audit-receipt",
                str(tmp_path / "audit-receipt.json"),
                "--proposal-dir",
                str(tmp_path / "proposal"),
                "--stage-dir",
                str(tmp_path / "stage"),
                flag,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0
        assert json.loads(result.stderr)["error_code"] == "manual_recovery_requires_audit"
        assert not state.exists()


def test_embedded_prepare_rejects_manual_recovery_before_state_write(tmp_path: Path):
    maintenance = _module()
    state = tmp_path / "state"
    with unittest.TestCase().assertRaisesRegex(maintenance.PolicyError, "manual_recovery_requires_audit"):
        maintenance.run(mode="prepare", state_dir=state, manual_audit=True)
    assert not state.exists()


def test_blocked_receipt_stays_visible(tmp_path: Path):
    state = tmp_path / "state"
    _write_lease(state, owner="different-owner", fingerprint="same-input", expires_at=900.0)
    result = _run(state, "--owner-id", "current-owner", now=1000.0)
    assert result.returncode != 0
    receipt = json.loads(result.stdout)
    assert receipt["thread_state"]["status"] == "keep_visible"
    assert receipt["thread_state"]["archive_eligible"] is False


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
    def __init__(
        self,
        maintenance,
        *,
        records=None,
        automation_records=None,
        push_error=None,
        create_error=None,
        advance_remote_on_query=None,
        created_head_override=None,
    ):
        self.maintenance = maintenance
        self.records = list(records or [])
        self.automation_records = None if automation_records is None else list(automation_records)
        self.remote = None
        self.push_error = push_error
        self.create_error = create_error
        self.advance_remote_on_query = advance_remote_on_query
        self.created_head_override = created_head_override
        self.push_calls = 0
        self.create_calls = 0
        self.remote_query_calls = 0
        self.remote_content_digest = None

    def list_automation_inventory(self, repository, branch_prefix, marker):
        records = self.records if self.automation_records is None else self.automation_records
        return {
            "pull_requests": list(records),
            "local_branches": [],
            "remote_branches": [],
        }

    def list_open_candidates(self, repository, branch, marker):
        return list(self.records)

    def remote_branch(self, repository, branch):
        self.remote_query_calls += 1
        if self.remote_query_calls == self.advance_remote_on_query:
            self.remote = {"sha": "e" * 40}
        return self.remote

    def compare_candidate(self, repository, base_sha, head_sha):
        return {
            "merge_base_sha": base_sha,
            "ahead_by": 1,
            "changed_paths": ["docs/candidate.md"],
            "changed_content_digest": self.remote_content_digest,
        }

    def push_branch(self, repository, branch, stage_dir):
        self.push_calls += 1
        if self.push_error:
            raise self.maintenance.MaintenanceError(self.push_error, "transient")
        head = self.maintenance._git(stage_dir, "rev-parse", "HEAD")
        self.remote = {"sha": head}
        self.remote_content_digest = self.maintenance._candidate_content_digest(
            stage_dir,
            ["docs/candidate.md"],
        )
        return {"branch": branch, "head_sha": head}

    def create_draft_pr(self, repository, branch, title, body, *, labels=None):
        self.create_calls += 1
        if self.create_error:
            raise self.maintenance.MaintenanceError(self.create_error, "transient")
        head = self.created_head_override or self.remote["sha"]
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
        return {**self.records[0], "is_draft": True}


def _lane(
    maintenance,
    root,
    stage,
    base,
    github,
    *,
    expected_digest=None,
    expected_content_digest=None,
):
    if stage is not None and expected_content_digest is None:
        expected_content_digest = maintenance._candidate_content_digest(
            stage,
            ["docs/candidate.md"],
        )
    return maintenance.prepare_canonical_pr(
        root,
        stage,
        base_sha=base,
        allowlist=["docs/candidate.md"],
        input_fingerprint_value="a" * 64,
        github=github,
        readiness_runner=lambda _stage: {"status": "passed", "checks": ["fixture-gate"]},
        expected_changed_paths_digest=expected_digest,
        expected_candidate_content_digest=expected_content_digest,
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
    reused = _lane(
        maintenance,
        root,
        None,
        base,
        github,
        expected_digest=digest_value,
        expected_content_digest=created["pr_state"]["candidate_content_digest"],
    )
    assert reused["terminal_classification"] == "prepared"
    assert reused["result"] == "canonical_pr_reused"
    assert reused["checks"]["optional_labels_missing"] is True
    assert github.push_calls == 1
    assert github.create_calls == 1


def test_canonical_lane_recomputes_remote_diff_before_reuse(tmp_path: Path):
    maintenance, root, stage, base = _candidate_fixture(tmp_path)
    github = _FakeGitHub(maintenance)
    created = _lane(maintenance, root, stage, base, github)
    github.compare_candidate = lambda _repository, _base, _head: {
        "merge_base_sha": base,
        "ahead_by": 1,
        "changed_paths": ["README.md"],
    }
    reused = _lane(
        maintenance,
        root,
        None,
        base,
        github,
        expected_digest=created["changed_paths_digest"],
        expected_content_digest=created["pr_state"]["candidate_content_digest"],
    )
    assert reused["terminal_classification"] == "blocked"
    assert reused["result"] == "canonical_changed_paths_digest_mismatch"


def test_canonical_lane_rejects_stale_same_path_content(tmp_path: Path):
    maintenance, root, stage, base = _candidate_fixture(tmp_path)
    github = _FakeGitHub(maintenance)
    created = _lane(maintenance, root, stage, base, github)
    stale_stage = tmp_path / "stale-stage"
    maintenance.stage_candidate(
        root,
        stale_stage,
        base_sha=base,
        allowlist=["docs/candidate.md"],
        proposed_files={"docs/candidate.md": "new candidate bytes\n"},
        run_readiness_checks=False,
    )
    result = _lane(
        maintenance,
        root,
        stale_stage,
        base,
        github,
        expected_digest=created["changed_paths_digest"],
    )
    assert result["terminal_classification"] == "blocked"
    assert result["result"] == "canonical_content_digest_mismatch"
    assert github.push_calls == 1
    assert github.create_calls == 1


def test_canonical_lane_recomputes_remote_content_before_reuse(tmp_path: Path):
    maintenance, root, stage, base = _candidate_fixture(tmp_path)
    github = _FakeGitHub(maintenance)
    created = _lane(maintenance, root, stage, base, github)
    github.remote_content_digest = "f" * 64
    result = _lane(
        maintenance,
        root,
        None,
        base,
        github,
        expected_digest=created["changed_paths_digest"],
        expected_content_digest=created["pr_state"]["candidate_content_digest"],
    )
    assert result["terminal_classification"] == "blocked"
    assert result["result"] == "canonical_remote_content_mismatch"
    assert github.push_calls == 1
    assert github.create_calls == 1


def test_conflicting_cli_modes_are_rejected_before_a_run(tmp_path: Path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "audit", "--mode", "prepare", "--state-dir", str(tmp_path / "state")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "conflicting_mode_arguments" in result.stderr
    assert not (tmp_path / "state").exists()


def test_canonical_lane_blocks_duplicate_candidates_before_remote_mutation(tmp_path: Path):
    maintenance, root, stage, base = _candidate_fixture(tmp_path)
    records = [{"number": 1, "head_ref_name": "automation/stack-maintenance"}, {"number": 2, "head_ref_name": "automation/stack-maintenance"}]
    github = _FakeGitHub(maintenance, records=records)
    result = _lane(maintenance, root, stage, base, github)
    assert result["terminal_classification"] == "blocked"
    assert result["result"] == "canonical_pr_ambiguous"
    assert github.push_calls == 0
    assert github.create_calls == 0


def test_canonical_lane_blocks_noncanonical_automation_pr_before_remote_mutation(tmp_path: Path):
    maintenance, root, stage, base = _candidate_fixture(tmp_path)
    github = _FakeGitHub(
        maintenance,
        automation_records=[{
            "number": 9,
            "head_ref_name": "automation/legacy-stack-update",
            "body": "legacy automation candidate",
        }],
    )

    result = _lane(maintenance, root, stage, base, github)

    assert result["terminal_classification"] == "blocked"
    assert result["result"] == "automation_pr_inventory_conflict"
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


def test_canonical_lane_resumes_pr_creation_for_verified_remote_branch(tmp_path: Path):
    maintenance, root, stage, base = _candidate_fixture(tmp_path)
    github = _FakeGitHub(maintenance, create_error="github_pr_create_failed")
    failed = _lane(maintenance, root, stage, base, github)
    assert failed["terminal_classification"] == "partial"

    retry_stage = tmp_path / "retry-stage"
    maintenance.stage_candidate(
        root,
        retry_stage,
        base_sha=base,
        allowlist=["docs/candidate.md"],
        proposed_files={"docs/candidate.md": "candidate\n"},
        run_readiness_checks=False,
    )
    github.create_error = None
    resumed = _lane(maintenance, root, retry_stage, base, github)

    assert resumed["terminal_classification"] == "prepared"
    assert resumed["result"] == "draft_pr_resumed"
    assert resumed["checks"]["remote_candidate_verified"] is True
    assert github.push_calls == 1
    assert github.create_calls == 2


def test_canonical_lane_revalidates_orphan_branch_immediately_before_pr_creation(tmp_path: Path):
    maintenance, root, stage, base = _candidate_fixture(tmp_path)
    github = _FakeGitHub(maintenance, create_error="github_pr_create_failed")
    failed = _lane(maintenance, root, stage, base, github)
    assert failed["terminal_classification"] == "partial"

    retry_stage = tmp_path / "retry-stage-race"
    maintenance.stage_candidate(
        root,
        retry_stage,
        base_sha=base,
        allowlist=["docs/candidate.md"],
        proposed_files={"docs/candidate.md": "candidate\n"},
        run_readiness_checks=False,
    )
    github.create_error = None
    github.advance_remote_on_query = github.remote_query_calls + 2

    raced = _lane(maintenance, root, retry_stage, base, github)

    assert raced["terminal_classification"] == "blocked"
    assert raced["result"] == "canonical_remote_head_changed"
    assert github.create_calls == 1


def test_canonical_lane_rejects_created_pr_with_unverified_head(tmp_path: Path):
    maintenance, root, stage, base = _candidate_fixture(tmp_path)
    github = _FakeGitHub(maintenance, created_head_override="e" * 40)

    result = _lane(maintenance, root, stage, base, github)

    assert result["terminal_classification"] == "partial"
    assert result["result"] == "created_pr_head_mismatch"
    assert result["checks"]["pr_created"] is True


def test_canonical_lane_resumes_pr_creation_from_retained_candidate_stage(tmp_path: Path):
    maintenance, root, stage, base = _candidate_fixture(tmp_path)
    github = _FakeGitHub(maintenance, create_error="github_pr_create_failed")
    failed = _lane(maintenance, root, stage, base, github)
    assert failed["terminal_classification"] == "partial"

    github.create_error = None
    resumed = _lane(maintenance, root, stage, base, github)

    assert resumed["terminal_classification"] == "prepared"
    assert resumed["result"] == "draft_pr_resumed"
    assert resumed["checks"]["remote_candidate_verified"] is True
    assert github.push_calls == 1
    assert github.create_calls == 2


def test_canonical_lane_blocks_unverified_remote_branch_without_pr(tmp_path: Path):
    maintenance, root, stage, base = _candidate_fixture(tmp_path)
    github = _FakeGitHub(maintenance, create_error="github_pr_create_failed")
    failed = _lane(maintenance, root, stage, base, github)
    assert failed["terminal_classification"] == "partial"

    retry_stage = tmp_path / "retry-stage"
    maintenance.stage_candidate(
        root,
        retry_stage,
        base_sha=base,
        allowlist=["docs/candidate.md"],
        proposed_files={"docs/candidate.md": "candidate\n"},
        run_readiness_checks=False,
    )
    github.remote_content_digest = "f" * 64
    github.create_error = None
    blocked = _lane(maintenance, root, retry_stage, base, github)

    assert blocked["terminal_classification"] == "blocked"
    assert blocked["result"] == "canonical_remote_content_mismatch"
    assert github.push_calls == 1
    assert github.create_calls == 1


def test_unverified_orphan_branch_increments_circuit(tmp_path: Path):
    maintenance = _module()
    github = _FakeGitHub(maintenance)
    github.remote = {"sha": "e" * 40}
    state = tmp_path / "state"
    maintenance.run(
        mode="audit",
        state_dir=state,
        run_id="source-audit",
        owner_id="test-owner",
        now=900.0,
        root=ROOT,
    )
    audit_receipt = state / "receipts/source-audit.json"
    with mock.patch.object(
        maintenance,
        "materialize_proposal_from_receipt",
        return_value={"docs/stack-maintenance.md": "# candidate\n"},
    ):
        receipt = maintenance.run(
            mode="prepare",
            state_dir=state,
            run_id="blocked-pr-lane",
            owner_id="test-owner",
            now=1000.0,
            stage_dir=tmp_path / "stage",
            root=ROOT,
            audit_receipt_path=audit_receipt,
            proposal_dir=tmp_path / "proposal",
            github=github,
            readiness_runner=lambda _stage: {"status": "passed", "checks": ["fixture-gate"]},
        )
    assert receipt["terminal_classification"] == "blocked"
    assert receipt["result"] == "canonical_changed_paths_digest_mismatch"
    circuit = json.loads((tmp_path / "state/stack-maintenance.circuit.json").read_text())
    assert circuit["strike_count"] == 1
    assert circuit["blocker_fingerprint"] is not None


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
