#!/usr/bin/env python3
"""Fail-closed Stack maintenance policy, lease, receipt, and circuit runner.

U2 deliberately stops at deterministic preflight.  It does not fetch sources,
create worktrees, write a candidate, install a runtime, or call GitHub.  Later
units can consume the receipt and add isolated audit/prepare behavior without
changing this state contract.
"""
from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config" / "stack-maintenance.json"
DEFAULT_SOURCES = ROOT / "registry" / "maintenance-sources.json"
DEFAULT_CATALOG = ROOT / "registry" / "capabilities.json"
DEFAULT_RECEIPT_SCHEMA = ROOT / "registry" / "stack-maintenance-receipt.schema.json"

TASK_ID = "stack-maintenance"
SCHEMA_VERSION = 1
TERMINAL_CLASSIFICATIONS = {
    "no_action",
    "prepared",
    "awaiting_approval",
    "blocked",
    "partial",
    "failed",
    "published",
}
DISPOSITIONS = {
    "catalog-managed-provider",
    "repository-owned-capability",
    "report-only-external-plugin",
    "retired-legacy-target",
}
VOLATILE_KEYS = {
    "observed_at",
    "observation_time",
    "timestamp",
    "checked_at",
    "updated_at",
    "created_at",
    "acquired_at",
    "expires_at",
    "cleared_at",
    "opened_at",
}
SAFE_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
DIGEST_PATTERN = re.compile(r"^[a-f0-9]{64}$")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class MaintenanceError(Exception):
    """A redacted, user-safe maintenance failure."""

    def __init__(self, code: str, retry_class: str = "non_transient") -> None:
        super().__init__(code)
        self.code = code
        self.retry_class = retry_class


class PolicyError(MaintenanceError):
    pass


class StateInitializationError(MaintenanceError):
    pass


def canonical_json(value: Any) -> str:
    """Return the stable JSON representation used for policy fingerprints."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def _without_volatile(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _without_volatile(item)
            for key, item in value.items()
            if str(key).lower() not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_without_volatile(item) for item in value]
    return value


def _file_digest(path: Path, missing_marker: str = "MISSING") -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except (OSError, IOError):
        return sha256_bytes(missing_marker.encode("utf-8"))


def _safe_id(value: Optional[str], prefix: str) -> str:
    if value and 1 <= len(value) <= 128 and all(char in SAFE_ID_CHARS for char in value):
        return value
    token = secrets.token_hex(12)
    return f"{prefix}-{token}"


def _safe_owner(value: Optional[str]) -> str:
    return _safe_id(value, "owner")


def _observed_at(now: float) -> str:
    return _datetime.datetime.fromtimestamp(now, tz=_datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path, kind: str) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise PolicyError(f"{kind}_unreadable")
    if not isinstance(value, dict):
        raise PolicyError(f"{kind}_not_object")
    return value


def load_policy(path: Path = DEFAULT_POLICY) -> Dict[str, Any]:
    policy = _read_json(Path(path), "policy")
    required = {
        "schema_version",
        "policy_id",
        "revision",
        "allowed_modes",
        "legacy_target_ids",
        "source_dispositions",
        "protected_surfaces",
        "terminal_classifications",
        "retry_classes",
        "canonical_candidate",
        "diff_allowlist",
        "authority",
        "state",
    }
    if set(policy) != required:
        raise PolicyError("policy_fields_invalid")
    return policy


def load_sources(path: Path = DEFAULT_SOURCES) -> Dict[str, Any]:
    sources = _read_json(Path(path), "source_inventory")
    if set(sources) != {"schema_version", "sources"}:
        raise PolicyError("source_inventory_fields_invalid")
    return sources


def validate_policy(policy: Mapping[str, Any], sources: Mapping[str, Any]) -> None:
    if policy.get("schema_version") != SCHEMA_VERSION or policy.get("policy_id") != TASK_ID:
        raise PolicyError("policy_identity_invalid")
    allowed_modes = policy.get("allowed_modes")
    if not isinstance(allowed_modes, list) or set(allowed_modes) != {"audit", "prepare"}:
        raise PolicyError("policy_modes_invalid")
    target_ids = policy.get("legacy_target_ids")
    if not isinstance(target_ids, list) or len(target_ids) != len(set(target_ids)) or any(not isinstance(item, str) or not item or any(char not in SAFE_ID_CHARS for char in item) for item in target_ids):
        raise PolicyError("legacy_target_ids_invalid")
    declared_dispositions = policy.get("source_dispositions")
    if not isinstance(declared_dispositions, list) or set(declared_dispositions) != DISPOSITIONS:
        raise PolicyError("source_dispositions_invalid")
    terminal = policy.get("terminal_classifications")
    if not isinstance(terminal, list) or set(terminal) != TERMINAL_CLASSIFICATIONS:
        raise PolicyError("terminal_classifications_invalid")
    protected = policy.get("protected_surfaces")
    if not isinstance(protected, list) or "secrets-and-private-configuration" not in protected:
        raise PolicyError("protected_surfaces_invalid")
    retries = policy.get("retry_classes")
    if not isinstance(retries, dict) or not isinstance(retries.get("transient"), list) or not isinstance(retries.get("non_transient"), list):
        raise PolicyError("retry_classes_invalid")
    candidate = policy.get("canonical_candidate")
    if not isinstance(candidate, dict) or candidate.get("identity") != TASK_ID or candidate.get("max_open") != 1:
        raise PolicyError("canonical_candidate_invalid")
    allowlist = policy.get("diff_allowlist")
    if not isinstance(allowlist, list) or not allowlist or any(not isinstance(item, str) or item.startswith("/") or ".." in Path(item).parts for item in allowlist):
        raise PolicyError("diff_allowlist_invalid")
    authority = policy.get("authority")
    if not isinstance(authority, dict) or authority.get("source_of_truth") != "stack" or authority.get("base_ref") != "origin/main":
        raise PolicyError("authority_invalid")
    state = policy.get("state")
    if not isinstance(state, dict) or state.get("directory_mode") != "0700" or state.get("receipt_mode") != "0600":
        raise PolicyError("state_policy_invalid")
    if not isinstance(state.get("circuit_threshold"), int) or state["circuit_threshold"] < 1:
        raise PolicyError("circuit_threshold_invalid")
    for state_name in ("lease_file", "circuit_file", "receipts_directory"):
        value = state.get(state_name)
        if not isinstance(value, str) or not value or Path(value).name != value or value in {".", ".."}:
            raise PolicyError("state_path_invalid")

    if sources.get("schema_version") != SCHEMA_VERSION or not isinstance(sources.get("sources"), list):
        raise PolicyError("source_inventory_schema_invalid")
    source_ids: List[str] = []
    for source in sources["sources"]:
        if not isinstance(source, dict):
            raise PolicyError("source_entry_invalid")
        if set(source) != {"id", "target", "disposition", "provider_ref", "pin_source"}:
            raise PolicyError("source_entry_fields_invalid")
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id or any(char not in SAFE_ID_CHARS for char in source_id):
            raise PolicyError("source_id_invalid")
        if source_id in source_ids:
            raise PolicyError("duplicate_source_id")
        source_ids.append(source_id)
        if source.get("disposition") not in DISPOSITIONS:
            raise PolicyError("source_disposition_invalid")
        if not all(isinstance(source.get(field), str) and source[field].strip() for field in ("target", "provider_ref", "pin_source")):
            raise PolicyError("source_metadata_invalid")
    if set(source_ids) != set(target_ids):
        raise PolicyError("source_inventory_incomplete")


def input_fingerprint(policy: Mapping[str, Any], sources: Mapping[str, Any], extra: Optional[Mapping[str, Any]] = None) -> str:
    """Hash semantic inputs only; observation times are excluded."""
    source_rows = sources.get("sources", []) if isinstance(sources, Mapping) else []
    if isinstance(source_rows, list):
        source_rows = sorted(source_rows, key=lambda item: str(item.get("id", "")) if isinstance(item, Mapping) else "")
    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "policy": _without_volatile(policy),
        "sources": _without_volatile({"schema_version": sources.get("schema_version"), "sources": source_rows}),
    }
    if extra is not None:
        payload["extra"] = _without_volatile(extra)
    return digest(payload)


# Stable descriptive aliases make the state contract convenient for callers
# that embed the runner instead of invoking its CLI.
load_config = load_policy
load_source_inventory = load_sources
fingerprint_inputs = input_fingerprint


def _provider_refs(sources: Mapping[str, Any]) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    for source in sorted(sources.get("sources", []), key=lambda item: item.get("id", "")):
        result.append({
            "source_id": source["id"],
            "ref_digest": digest({"provider_ref": source["provider_ref"], "pin_source": source["pin_source"]}),
        })
    return result


def _state_paths(state_dir: Path, policy: Optional[Mapping[str, Any]] = None) -> Dict[str, Path]:
    state = policy.get("state", {}) if policy else {}
    receipts_name = state.get("receipts_directory", "receipts")
    lease_name = state.get("lease_file", "stack-maintenance.lease.json")
    circuit_name = state.get("circuit_file", "stack-maintenance.circuit.json")
    return {
        "root": state_dir,
        "receipts": state_dir / str(receipts_name),
        "lease": state_dir / str(lease_name),
        "circuit": state_dir / str(circuit_name),
    }


def _owner_only_directory(path: Path, *, create: bool) -> None:
    if path.is_symlink():
        raise StateInitializationError("state_symlink")
    if not path.exists():
        if not create:
            return
        try:
            path.mkdir(parents=True, mode=0o700, exist_ok=False)
        except FileExistsError:
            pass
        except OSError:
            raise StateInitializationError("state_init_failed")
    try:
        info = path.stat()
    except OSError:
        raise StateInitializationError("state_stat_failed")
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise StateInitializationError("state_permissions_unsafe")
    try:
        os.chmod(path, 0o700)
    except OSError:
        raise StateInitializationError("state_permissions_unsafe")


def initialize_state_dir(state_dir: Path, policy: Optional[Mapping[str, Any]] = None) -> Dict[str, Path]:
    """Create/check owner-only state without ever selecting a fallback path."""
    paths = _state_paths(Path(state_dir), policy)
    _owner_only_directory(paths["root"], create=True)
    _owner_only_directory(paths["receipts"], create=True)
    return paths


def _assert_secure_state_file(path: Path) -> None:
    if path.is_symlink():
        raise StateInitializationError("state_file_symlink")
    try:
        info = path.stat()
    except OSError:
        raise StateInitializationError("state_file_stat_failed")
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise StateInitializationError("state_file_permissions_unsafe")


def _read_state(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    _assert_secure_state_file(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise MaintenanceError("state_record_invalid", "non_transient")
    if not isinstance(value, dict):
        raise MaintenanceError("state_record_invalid", "non_transient")
    return value


def _write_new_json(path: Path, value: Mapping[str, Any], mode: int) -> bool:
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(str(path), flags, mode)
    except FileExistsError:
        return False
    except OSError:
        raise StateInitializationError("state_write_failed")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise StateInitializationError("state_write_failed")
    try:
        os.chmod(path, mode)
    except OSError:
        raise StateInitializationError("state_write_failed")
    return True


def _replace_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        _assert_secure_state_file(path)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    _write_new_json(temporary, value, 0o600)
    try:
        os.replace(str(temporary), str(path))
        os.chmod(path, 0o600)
    except OSError:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise StateInitializationError("state_write_failed")


def _append_receipt(paths: Mapping[str, Path], record: Mapping[str, Any]) -> Path:
    receipts = paths["receipts"]
    _owner_only_directory(receipts, create=False)
    run_id = str(record["run_id"])
    for suffix in range(0, 1000):
        name = f"{run_id}.json" if suffix == 0 else f"{run_id}-{suffix + 1}.json"
        target = receipts / name
        if _write_new_json(target, record, 0o600):
            return target
    raise StateInitializationError("receipt_name_exhausted")


def _lease_payload(run_id: str, owner_id: str, fingerprint: str, now: float, seconds: int) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "run_id": run_id,
        "owner_id": owner_id,
        "input_fingerprint": fingerprint,
        "acquired_at": now,
        "expires_at": now + seconds,
    }


def acquire_lease(paths: Mapping[str, Path], *, run_id: str, owner_id: str, input_fp: str, now: float, lease_seconds: int, manual_audit: bool = False) -> Dict[str, Any]:
    """Acquire one task lease, recovering only a proven stale owner/input."""
    lease_path = paths["lease"]
    candidate = _lease_payload(run_id, owner_id, input_fp, now, lease_seconds)
    if _write_new_json(lease_path, candidate, 0o600):
        return {"status": "acquired", "recovered": False, "manual_validated": False}
    existing = _read_state(lease_path)
    if not existing or existing.get("task_id") != TASK_ID:
        raise MaintenanceError("lease_record_invalid", "non_transient")
    try:
        expires_at = float(existing["expires_at"])
    except (KeyError, TypeError, ValueError):
        raise MaintenanceError("lease_record_invalid", "non_transient")
    if expires_at > now:
        return {"status": "active", "lease": existing, "recovered": False, "manual_validated": False}
    owner_matches = existing.get("owner_id") == owner_id
    input_matches = existing.get("input_fingerprint") == input_fp
    if not (owner_matches and input_matches) and not manual_audit:
        return {"status": "stale_mismatch", "lease": existing, "recovered": False, "manual_validated": False}
    try:
        _assert_secure_state_file(lease_path)
        lease_path.unlink()
    except OSError:
        raise StateInitializationError("stale_lease_recovery_failed")
    if not _write_new_json(lease_path, candidate, 0o600):
        return {"status": "active", "lease": _read_state(lease_path), "recovered": False, "manual_validated": False}
    return {"status": "acquired", "recovered": True, "manual_validated": not (owner_matches and input_matches)}


def release_lease(paths: Mapping[str, Path], *, run_id: str, owner_id: str) -> None:
    lease_path = paths["lease"]
    if not lease_path.exists():
        return
    try:
        lease = _read_state(lease_path)
        if lease and lease.get("task_id") == TASK_ID and lease.get("run_id") == run_id and lease.get("owner_id") == owner_id:
            _assert_secure_state_file(lease_path)
            lease_path.unlink()
    except FileNotFoundError:
        return


def _default_circuit() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "open": False,
        "strike_count": 0,
        "blocker_fingerprint": None,
        "last_run_id": None,
    }


def read_circuit(paths: Mapping[str, Path]) -> Dict[str, Any]:
    current = _read_state(paths["circuit"])
    if current is None:
        return _default_circuit()
    if current.get("task_id") != TASK_ID or not isinstance(current.get("open"), bool) or not isinstance(current.get("strike_count"), int):
        raise MaintenanceError("circuit_record_invalid", "non_transient")
    return current


def blocker_fingerprint(code: str, input_fp: str) -> str:
    return digest({"task_id": TASK_ID, "code": code, "input_fingerprint": input_fp})


def update_circuit(paths: Mapping[str, Path], *, policy: Mapping[str, Any], blocker_fp: str, run_id: str, now: float, retry_class: str = "non_transient") -> Dict[str, Any]:
    if retry_class in set(policy.get("retry_classes", {}).get("transient", [])):
        return read_circuit(paths)
    current = read_circuit(paths)
    strikes = current.get("strike_count", 0) + 1 if current.get("blocker_fingerprint") == blocker_fp else 1
    threshold = int(policy.get("state", {}).get("circuit_threshold", 3))
    updated = {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "open": strikes >= threshold,
        "strike_count": strikes,
        "blocker_fingerprint": blocker_fp,
        "last_run_id": run_id,
        "updated_at": now,
    }
    if updated["open"]:
        updated["opened_at"] = current.get("opened_at", now)
    _replace_json(paths["circuit"], updated)
    return updated


def clear_circuit(paths: Mapping[str, Path], *, run_id: str, now: float) -> bool:
    current = read_circuit(paths)
    if not current.get("open"):
        return False
    _replace_json(
        paths["circuit"],
        {
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
            "open": False,
            "strike_count": 0,
            "blocker_fingerprint": None,
            "last_run_id": run_id,
            "cleared_at": now,
            "cleared_by": "manual-audit",
        },
    )
    return True


def _base_receipt(*, run_id: str, mode: str, manual_audit: bool, now: float, input_fp: Optional[str], provider_refs: List[Dict[str, str]], policy_digest: str, catalog_digest: str) -> Dict[str, Any]:
    empty_digest = digest([])
    state = {"status": "not_observed_in_u2", "digest": digest("not-observed")}
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": mode if mode in {"audit", "prepare"} else "audit",
        "manual_audit": manual_audit,
        "observed_at": _observed_at(now),
        "input_fingerprint": input_fp,
        "provider_refs": provider_refs,
        "catalog_digest": catalog_digest,
        "policy_digest": policy_digest,
        "checkout_state": state.copy(),
        "changed_paths_digest": empty_digest,
        "checks": {},
        "pr_state": state.copy(),
        "approval_state": state.copy(),
        "cleanup_state": state.copy(),
        "thread_state": state.copy(),
        "terminal_classification": "failed",
        "receipt_persisted": True,
    }


def _record_blocker(paths: Mapping[str, Path], *, policy: Mapping[str, Any], receipt: Dict[str, Any], code: str, input_fp: str, run_id: str, now: float, retry_class: str = "non_transient") -> Dict[str, Any]:
    circuit = update_circuit(paths, policy=policy, blocker_fp=blocker_fingerprint(code, input_fp), run_id=run_id, now=now, retry_class=retry_class)
    receipt["terminal_classification"] = "blocked"
    receipt["result"] = code
    receipt["reason_code"] = code
    receipt["circuit"] = {"status": "open" if circuit.get("open") else "closed", "strike_count": circuit.get("strike_count", 0), "digest": digest(circuit)}
    receipt["checks"] = {"preflight_complete": False, "blocker_recorded": True, "disposable_stage_not_created": True}
    return receipt


def validate_receipt(receipt: Mapping[str, Any], schema_path: Path = DEFAULT_RECEIPT_SCHEMA) -> None:
    """Validate the receipt contract without adding a third-party dependency."""
    schema = _read_json(Path(schema_path), "receipt_schema")
    required = schema.get("required")
    properties = schema.get("properties")
    if not isinstance(required, list) or not isinstance(properties, dict):
        raise PolicyError("receipt_schema_invalid")
    if set(receipt) - set(properties) or any(field not in receipt for field in required):
        raise MaintenanceError("receipt_fields_invalid")
    if receipt.get("schema_version") != SCHEMA_VERSION or receipt.get("task_id") != TASK_ID:
        raise MaintenanceError("receipt_identity_invalid")
    if not isinstance(receipt.get("run_id"), str) or not RUN_ID_PATTERN.fullmatch(receipt["run_id"]):
        raise MaintenanceError("receipt_run_id_invalid")
    if receipt.get("mode") not in {"audit", "prepare"} or not isinstance(receipt.get("manual_audit"), bool):
        raise MaintenanceError("receipt_mode_invalid")
    if receipt.get("terminal_classification") not in TERMINAL_CLASSIFICATIONS or receipt.get("receipt_persisted") is not True:
        raise MaintenanceError("receipt_terminal_invalid")
    for field in ("catalog_digest", "policy_digest", "changed_paths_digest"):
        if not isinstance(receipt.get(field), str) or not DIGEST_PATTERN.fullmatch(receipt[field]):
            raise MaintenanceError("receipt_digest_invalid")
    input_fp = receipt.get("input_fingerprint")
    if input_fp is not None and (not isinstance(input_fp, str) or not DIGEST_PATTERN.fullmatch(input_fp)):
        raise MaintenanceError("receipt_digest_invalid")
    if not isinstance(receipt.get("provider_refs"), list):
        raise MaintenanceError("receipt_provider_refs_invalid")
    for provider in receipt["provider_refs"]:
        if (
            not isinstance(provider, dict)
            or set(provider) != {"source_id", "ref_digest"}
            or not isinstance(provider.get("source_id"), str)
            or not isinstance(provider.get("ref_digest"), str)
            or not DIGEST_PATTERN.fullmatch(provider["ref_digest"])
        ):
            raise MaintenanceError("receipt_provider_refs_invalid")
    for field in ("checkout_state", "pr_state", "approval_state", "cleanup_state", "thread_state"):
        value = receipt.get(field)
        if not isinstance(value, dict) or not isinstance(value.get("status"), str) or not value["status"]:
            raise MaintenanceError("receipt_state_invalid")
        state_digest = value.get("digest")
        if state_digest is not None and (not isinstance(state_digest, str) or not DIGEST_PATTERN.fullmatch(state_digest)):
            raise MaintenanceError("receipt_state_invalid")
    if not isinstance(receipt.get("checks"), dict):
        raise MaintenanceError("receipt_checks_invalid")


def _safe_append(paths: Mapping[str, Path], receipt: Dict[str, Any]) -> Dict[str, Any]:
    validate_receipt(receipt)
    _append_receipt(paths, receipt)
    return receipt


def _preflight(policy: Mapping[str, Any], sources: Mapping[str, Any], mode: str, stage_dir: Optional[Path]) -> Dict[str, Any]:
    if mode not in policy.get("allowed_modes", []):
        raise PolicyError("mode_not_allowed")
    # This unit intentionally does not inspect or create the disposable stage.
    return {
        "policy_valid": True,
        "source_inventory_complete": True,
        "authority_recorded": True,
        "protected_surfaces_declared": True,
        "terminal_classification_declared": True,
        "disposable_stage_not_created": stage_dir is None or not stage_dir.exists(),
        "network_not_started": True,
        "github_not_contacted": True,
    }


def run(
    mode: str = "audit",
    state_dir: Optional[Path] = None,
    policy_path: Path = DEFAULT_POLICY,
    sources_path: Path = DEFAULT_SOURCES,
    run_id: Optional[str] = None,
    owner_id: Optional[str] = None,
    manual_audit: bool = False,
    now: Optional[float] = None,
    lease_seconds: Optional[int] = None,
    stage_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run deterministic U2 preflight and return the public receipt record."""
    run_id_safe = _safe_id(run_id, "run")
    owner_safe = _safe_owner(owner_id or TASK_ID)
    observed_now = time.time() if now is None else float(now)
    state_root = Path(state_dir) if state_dir is not None else Path(os.environ.get("STACK_MAINTENANCE_STATE_DIR", str(Path.home() / ".local/state/stack/maintenance")))
    # State initialization intentionally precedes policy reads so an unsafe
    # state location cannot cause a partial receipt or a fallback write.
    initial_paths = initialize_state_dir(state_root)
    raw_policy_digest = _file_digest(Path(policy_path))
    raw_sources_digest = _file_digest(Path(sources_path))
    catalog_digest = _file_digest(DEFAULT_CATALOG)
    try:
        policy = load_policy(Path(policy_path))
        sources = load_sources(Path(sources_path))
        validate_policy(policy, sources)
    except MaintenanceError as error:
        raw_input_fp = digest({"policy_digest": raw_policy_digest, "sources_digest": raw_sources_digest})
        fallback_policy = {
            "retry_classes": {"transient": [], "non_transient": ["policy"]},
            "state": {"circuit_threshold": 3},
        }
        receipt = _base_receipt(run_id=run_id_safe, mode=mode, manual_audit=manual_audit, now=observed_now, input_fp=raw_input_fp, provider_refs=[], policy_digest=raw_policy_digest, catalog_digest=catalog_digest)
        receipt["checks"] = {"policy_valid": False, "source_inventory_complete": False, "disposable_stage_not_created": True}
        receipt["terminal_classification"] = "failed"
        receipt["result"] = error.code
        receipt["reason_code"] = error.code
        update_circuit(initial_paths, policy=fallback_policy, blocker_fp=blocker_fingerprint(error.code, raw_input_fp), run_id=run_id_safe, now=observed_now)
        return _safe_append(initial_paths, receipt)

    paths = _state_paths(state_root, policy)
    # `initialize_state_dir` above used the safe built-in names.  Re-check the
    # policy-selected names before any lease, circuit, or receipt mutation.
    initialize_state_dir(state_root, policy)
    input_fp = input_fingerprint(policy, sources)
    refs = _provider_refs(sources)
    policy_digest = digest(_without_volatile(policy))
    lease_duration = int(lease_seconds if lease_seconds is not None else policy["state"]["lease_seconds"])
    if lease_duration <= 0:
        receipt = _base_receipt(run_id=run_id_safe, mode=mode, manual_audit=manual_audit, now=observed_now, input_fp=input_fp, provider_refs=refs, policy_digest=policy_digest, catalog_digest=catalog_digest)
        receipt["checks"] = {"policy_valid": False, "disposable_stage_not_created": True}
        receipt["result"] = "lease_duration_invalid"
        receipt["reason_code"] = "lease_duration_invalid"
        return _safe_append(paths, receipt)

    manual_cleared = False
    try:
        circuit = read_circuit(paths)
    except MaintenanceError as error:
        receipt = _base_receipt(run_id=run_id_safe, mode=mode, manual_audit=manual_audit, now=observed_now, input_fp=input_fp, provider_refs=refs, policy_digest=policy_digest, catalog_digest=catalog_digest)
        receipt["terminal_classification"] = "failed"
        receipt["result"] = error.code
        receipt["reason_code"] = error.code
        receipt["checks"] = {"circuit_record_valid": False, "disposable_stage_not_created": True}
        return _safe_append(paths, receipt)
    if circuit.get("open"):
        if not manual_audit:
            receipt = _base_receipt(run_id=run_id_safe, mode=mode, manual_audit=False, now=observed_now, input_fp=input_fp, provider_refs=refs, policy_digest=policy_digest, catalog_digest=catalog_digest)
            receipt["result"] = "circuit_open"
            receipt["reason_code"] = "circuit_open"
            receipt["terminal_classification"] = "blocked"
            receipt["circuit"] = {"status": "open", "strike_count": circuit.get("strike_count", 0), "digest": digest(circuit)}
            receipt["checks"] = {"circuit_checked_before_work": True, "network_not_started": True, "disposable_stage_not_created": True}
            return _safe_append(paths, receipt)
        manual_cleared = clear_circuit(paths, run_id=run_id_safe, now=observed_now)

    try:
        lease = acquire_lease(paths, run_id=run_id_safe, owner_id=owner_safe, input_fp=input_fp, now=observed_now, lease_seconds=lease_duration, manual_audit=manual_audit)
    except MaintenanceError as error:
        receipt = _base_receipt(run_id=run_id_safe, mode=mode, manual_audit=manual_audit, now=observed_now, input_fp=input_fp, provider_refs=refs, policy_digest=policy_digest, catalog_digest=catalog_digest)
        receipt["terminal_classification"] = "failed"
        receipt["result"] = error.code
        receipt["reason_code"] = error.code
        receipt["checks"] = {"lease_record_valid": False, "disposable_stage_not_created": True}
        return _safe_append(paths, receipt)
    if lease["status"] == "active":
        receipt = _base_receipt(run_id=run_id_safe, mode=mode, manual_audit=manual_audit, now=observed_now, input_fp=input_fp, provider_refs=refs, policy_digest=policy_digest, catalog_digest=catalog_digest)
        receipt["terminal_classification"] = "blocked"
        receipt["result"] = "duplicate_active_run"
        receipt["reason_code"] = "duplicate_active_run"
        receipt["checks"] = {"lease_checked_before_work": True, "network_not_started": True, "disposable_stage_not_created": True}
        receipt["circuit"] = {"status": "closed", "strike_count": circuit.get("strike_count", 0), "digest": digest(circuit)}
        return _safe_append(paths, receipt)
    if lease["status"] == "stale_mismatch":
        receipt = _base_receipt(run_id=run_id_safe, mode=mode, manual_audit=manual_audit, now=observed_now, input_fp=input_fp, provider_refs=refs, policy_digest=policy_digest, catalog_digest=catalog_digest)
        receipt = _record_blocker(paths, policy=policy, receipt=receipt, code="stale_lease_mismatch", input_fp=input_fp, run_id=run_id_safe, now=observed_now)
        receipt["checks"]["stale_lease_requires_manual_audit"] = True
        return _safe_append(paths, receipt)

    try:
        try:
            checks = _preflight(policy, sources, mode, stage_dir)
        except MaintenanceError as error:
            receipt = _base_receipt(run_id=run_id_safe, mode=mode, manual_audit=manual_audit, now=observed_now, input_fp=input_fp, provider_refs=refs, policy_digest=policy_digest, catalog_digest=catalog_digest)
            receipt["terminal_classification"] = "failed"
            receipt["result"] = error.code
            receipt["reason_code"] = error.code
            receipt["checks"] = {"preflight_complete": False, "disposable_stage_not_created": True}
            return _safe_append(paths, receipt)
        receipt = _base_receipt(run_id=run_id_safe, mode=mode, manual_audit=manual_audit, now=observed_now, input_fp=input_fp, provider_refs=refs, policy_digest=policy_digest, catalog_digest=catalog_digest)
        receipt["terminal_classification"] = "no_action"
        receipt["result"] = "manual_audit_cleared" if manual_cleared else "preflight_only"
        receipt["checks"] = checks
        receipt["circuit"] = {"status": "closed", "strike_count": 0, "digest": digest(_default_circuit())}
        if lease.get("manual_validated"):
            receipt["result"] = "manual_audit_validated_stale_lease"
        if manual_cleared or lease.get("manual_validated"):
            receipt["manual_audit_cleared"] = True
        return _safe_append(paths, receipt)
    finally:
        release_lease(paths, run_id=run_id_safe, owner_id=owner_safe)


def _failure_record(run_id: str, code: str) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "run_id": run_id,
        "terminal_classification": "failed",
        "result": code,
        "error_code": code,
        "receipt_persisted": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run fail-closed Stack maintenance preflight")
    parser.add_argument("mode", nargs="?", choices=("audit", "prepare"), default="audit")
    parser.add_argument("--mode", dest="mode_option", choices=("audit", "prepare"))
    parser.add_argument("--state-dir", "--state-root", dest="state_dir", type=Path)
    parser.add_argument("--policy", "--policy-path", dest="policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--sources", "--source-inventory", dest="sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--run-id")
    parser.add_argument("--owner-id")
    parser.add_argument("--manual-audit", action="store_true")
    parser.add_argument("--clear-circuit", action="store_true", help="clear an open circuit as an explicit manual audit")
    parser.add_argument("--now", type=float)
    parser.add_argument("--lease-seconds", type=int)
    parser.add_argument("--stage-dir", type=Path)
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    run_id = _safe_id(args.run_id, "run")
    mode = args.mode_option or args.mode
    try:
        result = run(
            mode=mode,
            state_dir=args.state_dir,
            policy_path=args.policy,
            sources_path=args.sources,
            run_id=run_id,
            owner_id=args.owner_id,
            manual_audit=args.manual_audit or args.clear_circuit,
            now=args.now,
            lease_seconds=args.lease_seconds,
            stage_dir=args.stage_dir,
        )
    except StateInitializationError:
        print(canonical_json(_failure_record(run_id, "state_init_failed")), file=sys.stderr)
        return 1
    except MaintenanceError as error:
        # A safe state directory exists, but an unexpected state record or
        # receipt write failed.  Do not disclose paths or raw exception text.
        print(canonical_json(_failure_record(run_id, error.code)), file=sys.stderr)
        return 1
    print(canonical_json(result))
    return 0 if result.get("terminal_classification") in {"no_action", "prepared", "awaiting_approval", "published"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
