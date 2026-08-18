#!/usr/bin/env python3
"""Fail-closed Stack maintenance policy, source audit, and candidate runner.

The runner audits catalog and lock metadata read-only.  ``prepare`` may create
an isolated candidate clone and run dry-run readiness checks; it never mutates
the caller checkout, installs a runtime, invokes a plugin, or calls GitHub.
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
import subprocess
import sys
import time
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config" / "stack-maintenance.json"
DEFAULT_SOURCES = ROOT / "registry" / "maintenance-sources.json"
DEFAULT_CATALOG = ROOT / "registry" / "capabilities.json"
DEFAULT_UPSTREAMS = ROOT / "registry" / "upstreams.json"
DEFAULT_LOCK = ROOT / "upstreams.lock.json"
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
SHA1_PATTERN = re.compile(r"^[a-f0-9]{40}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
PRIVATE_DATA_PATTERNS = (
    re.compile(r"/Users/[^\s\"']+"),
    re.compile(r"/home/[^\s\"']+"),
    re.compile(r"(?:^|[^A-Za-z])CODEX_HOME(?:$|[^A-Za-z])"),
    re.compile(r"(?:^|[^A-Za-z])HOME=/"),
    re.compile(r"-----BEGIN (?:OPENSSH|RSA|EC|DSA|PRIVATE) KEY-----"),
    re.compile(r"(?:ghp|github_pat|sk)-[A-Za-z0-9_\-]{12,}"),
)
SAFE_REPOSITORY_PATH = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._/-]+$")
SOURCE_FIELDS = {
    "id",
    "target",
    "disposition",
    "provider_ref",
    "pin_source",
    "provider_id",
    "target_paths",
    "required_exports",
}

# Reconciliation is deliberately a pure, data-only lane.  These constants are
# kept separate from the source/update policy above because a cleanup packet is
# an approval-bound description of live state, not an instruction to mutate it.
RECONCILIATION_SCHEMA_VERSION = 1
RECONCILIATION_DISPOSITIONS = {
    "preserve",
    "replace",
    "no_change",
    "hold",
    "excluded",
}
RECONCILIATION_CONTENT_CLASSES = {"unique", "duplicate", "invalid", "unknown"}
RECONCILIATION_ITEM_TYPES = {"pr", "branch"}
CLEANUP_ACTIONS = {"close_pr", "delete_branch"}
RECONCILIATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


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
        if set(source) != SOURCE_FIELDS:
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
        provider_id = source.get("provider_id")
        if provider_id is not None and (
            not isinstance(provider_id, str)
            or not provider_id
            or any(char not in SAFE_ID_CHARS for char in provider_id)
        ):
            raise PolicyError("source_provider_id_invalid")
        target_paths = source.get("target_paths")
        exports = source.get("required_exports")
        if (
            not isinstance(target_paths, list)
            or len(target_paths) != len(set(target_paths))
            or not all(isinstance(path, str) and SAFE_REPOSITORY_PATH.fullmatch(path) for path in target_paths)
            or not isinstance(exports, list)
            or len(exports) != len(set(exports))
            or not all(isinstance(export, str) and export and all(char in SAFE_ID_CHARS for char in export) for export in exports)
        ):
            raise PolicyError("source_paths_or_exports_invalid")
        if source["disposition"] == "catalog-managed-provider" and not provider_id:
            raise PolicyError("catalog_provider_missing")
        if source["disposition"] != "catalog-managed-provider" and provider_id is not None:
            raise PolicyError("non_catalog_provider_declared")
        if source["disposition"] in {"report-only-external-plugin", "retired-legacy-target"} and (target_paths or exports):
            raise PolicyError("non_mutating_source_paths_invalid")
    if set(source_ids) != set(target_ids):
        raise PolicyError("source_inventory_incomplete")


def _load_object(path: Path, kind: str) -> Dict[str, Any]:
    """Read a repository metadata object without exposing its path in errors."""
    return _read_json(Path(path), kind)


def _repository_relative(path: str) -> Path:
    if not isinstance(path, str) or not SAFE_REPOSITORY_PATH.fullmatch(path):
        raise PolicyError("unsafe_repository_path")
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise PolicyError("unsafe_repository_path")
    return candidate


def _origin_identity(value: str) -> str:
    """Normalize public Git remotes to owner/repository identity."""
    remote = value.strip()
    if remote.startswith("git@") and ":" in remote:
        remote = remote.split(":", 1)[1]
    elif remote.startswith(("https://", "http://", "ssh://")):
        parsed = urlparse(remote)
        remote = parsed.path.lstrip("/")
    remote = remote.rstrip("/")
    if remote.endswith(".git"):
        remote = remote[:-4]
    return remote


def _git(root: Path, *arguments: str) -> str:
    """Run a read-only Git query and return normalized stdout."""
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise MaintenanceError("git_query_failed", "transient")
    return result.stdout.strip()


def _git_mutate(root: Path, *arguments: str, error_code: str = "git_mutation_failed") -> str:
    """Run one explicitly-scoped Git mutation and redact command failures."""
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise MaintenanceError(error_code, "transient")
    return result.stdout.strip()


def _git_status(root: Path) -> tuple[str, list[str]]:
    # Do not use ``_git`` here: its normalizing ``strip`` would remove the
    # leading porcelain status column and turn `` M docs/x`` into ``M docs/x``.
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise MaintenanceError("git_query_failed", "transient")
    status = result.stdout.rstrip("\n")
    lines = [line for line in status.splitlines() if line.strip()]
    return digest(lines), lines


def _assert_no_symlinks(root: Path, relative: Path, *, allow_missing: bool = False) -> None:
    """Reject symlinks in an owned path, including intermediate components."""
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise MaintenanceError("unexpected_symlink", "non_transient")
        if not current.exists():
            if allow_missing:
                return
            raise MaintenanceError("missing_declared_path", "non_transient")


def _assert_tree_no_symlinks(root: Path) -> None:
    for child in sorted(root.rglob("*")):
        relative = child.relative_to(root)
        if relative.parts and relative.parts[0] == ".git":
            continue
        if child.is_symlink():
            raise MaintenanceError("unexpected_symlink", "non_transient")


def _path_digest(root: Path, relative: Path) -> str:
    target = root / relative
    _assert_no_symlinks(root, relative)
    if target.is_file():
        return sha256_bytes(target.read_bytes())
    if not target.is_dir():
        raise MaintenanceError("declared_path_not_file_or_directory", "non_transient")
    entries: list[dict[str, str]] = []
    for child in sorted(target.rglob("*")):
        child_relative = child.relative_to(root)
        _assert_no_symlinks(root, child_relative)
        if child.is_file():
            entries.append({"path": child_relative.as_posix(), "digest": sha256_bytes(child.read_bytes())})
        elif not child.is_dir():
            raise MaintenanceError("declared_path_not_file_or_directory", "non_transient")
    return digest(entries)


def _validate_pin(provider: Mapping[str, Any], lock_value: Any) -> tuple[str, str]:
    pin = provider.get("pin")
    provider_id = provider.get("id")
    if not isinstance(provider_id, str) or not provider_id:
        raise PolicyError("upstream_provider_id_invalid")
    if not isinstance(pin, Mapping) or pin.get("type") not in {"git-commit", "sha256"}:
        raise PolicyError("mutable_upstream_pin")
    pin_type = str(pin["type"])
    pin_value = pin.get("value")
    expected = SHA1_PATTERN if pin_type == "git-commit" else SHA256_PATTERN
    if not isinstance(pin_value, str) or expected.fullmatch(pin_value) is None:
        raise PolicyError("upstream_pin_invalid")
    if lock_value != pin_value:
        raise PolicyError("upstream_lock_mismatch")
    last_known_good = provider.get("last_known_good")
    if not isinstance(last_known_good, Mapping) or last_known_good.get("pin") != pin_value:
        raise PolicyError("upstream_last_known_good_mismatch")
    return pin_type, pin_value


def load_upstream_metadata(
    registry_path: Path = DEFAULT_UPSTREAMS,
    lock_path: Path = DEFAULT_LOCK,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    registry = _load_object(Path(registry_path), "upstream_registry")
    lock = _load_object(Path(lock_path), "upstream_lock")
    if registry.get("schema_version") != SCHEMA_VERSION or not isinstance(registry.get("providers"), list):
        raise PolicyError("upstream_registry_invalid")
    if lock.get("schema_version") != SCHEMA_VERSION or not isinstance(lock.get("providers"), Mapping):
        raise PolicyError("upstream_lock_invalid")
    return registry, lock


def validate_upstream_metadata(
    registry: Mapping[str, Any],
    lock: Mapping[str, Any],
) -> Dict[str, Mapping[str, Any]]:
    """Validate the catalog/lock pair and return providers by immutable ID."""
    providers: Dict[str, Mapping[str, Any]] = {}
    for provider in registry.get("providers", []):
        if not isinstance(provider, Mapping):
            raise PolicyError("upstream_provider_invalid")
        provider_id = provider.get("id")
        if not isinstance(provider_id, str) or not provider_id or provider_id in providers:
            raise PolicyError("duplicate_upstream_provider")
        source = provider.get("canonical_source")
        if not isinstance(source, str) or not source.startswith("https://"):
            raise PolicyError("upstream_origin_invalid")
        pin_type, _ = _validate_pin(provider, lock.get("providers", {}).get(provider_id))
        exports = provider.get("exports")
        if not isinstance(exports, list) or not exports or len(exports) != len(set(exports)) or not all(isinstance(item, str) and item for item in exports):
            raise PolicyError("upstream_exports_missing")
        if provider.get("install") == "pinned-git-checkout":
            paths = provider.get("export_paths")
            if not isinstance(paths, Mapping) or set(paths) != set(exports):
                raise PolicyError("upstream_export_paths_missing")
            for export_path in paths.values():
                _repository_relative(str(export_path))
                if not str(export_path).endswith("/SKILL.md"):
                    raise PolicyError("upstream_export_path_invalid")
        if not isinstance(provider.get("license"), str) or not provider["license"].strip():
            raise PolicyError("upstream_license_missing")
        providers[provider_id] = provider
    if set(lock.get("providers", {})) != set(providers):
        raise PolicyError("upstream_lock_provider_set_invalid")
    return providers


def _provider_ref_matches(provider_ref: str, canonical_source: str) -> bool:
    if not isinstance(provider_ref, str):
        return False
    return _origin_identity(provider_ref).lower() == _origin_identity(canonical_source).lower()


def _check_source_metadata(root: Path, target_paths: list[Path], pin_value: str) -> None:
    """Verify checked-in source manifests never claim a different immutable ref."""
    for target in target_paths:
        if not target.is_dir():
            continue
        for metadata in sorted(target.rglob("references/source.json")):
            _assert_no_symlinks(root, metadata.relative_to(root))
            try:
                value = json.loads(metadata.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                raise PolicyError("source_metadata_invalid")
            latest = value.get("latest_commit") if isinstance(value, Mapping) else None
            if isinstance(latest, Mapping) and latest.get("sha") != pin_value:
                raise PolicyError("source_metadata_pin_mismatch")


def _package_for_provider(root: Path, provider_id: str) -> Optional[Path]:
    direct = root / "packages" / provider_id
    if direct.is_dir():
        return direct
    packages_root = root / "packages"
    if not packages_root.is_dir():
        return None
    for manifest_path in sorted(packages_root.glob("*/package.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        providers = manifest.get("providers", [])
        if manifest.get("provider") == provider_id or provider_id in providers:
            return manifest_path.parent
    return None


def validate_source_catalog(
    root: Path,
    policy: Mapping[str, Any],
    sources: Mapping[str, Any],
    registry: Mapping[str, Any],
    lock: Mapping[str, Any],
) -> Dict[str, Mapping[str, Any]]:
    """Cross-check legacy targets against the immutable source catalog."""
    providers = validate_upstream_metadata(registry, lock)
    rows: Dict[str, Mapping[str, Any]] = {}
    referenced_provider_ids: set[str] = set()
    for source in sorted(sources.get("sources", []), key=lambda item: item["id"]):
        source_id = str(source["id"])
        disposition = source["disposition"]
        provider_id = source.get("provider_id")
        target_paths = [_repository_relative(path) for path in source.get("target_paths", [])]
        if disposition == "catalog-managed-provider":
            provider = providers.get(provider_id)
            if provider is None:
                raise PolicyError("unregistered_catalog_provider")
            if not _provider_ref_matches(source["provider_ref"], str(provider["canonical_source"])):
                raise PolicyError("provider_origin_mismatch")
            if source["pin_source"] != f"registry/upstreams.json:{provider_id}":
                raise PolicyError("provider_pin_source_invalid")
            pin_type, pin_value = _validate_pin(provider, lock["providers"].get(provider_id))
            referenced_provider_ids.add(str(provider_id))
            required_exports = source.get("required_exports", [])
            exports = provider.get("exports", [])
            if not set(required_exports).issubset(set(exports)):
                raise PolicyError("required_export_missing")
            package_path = _package_for_provider(root, str(provider_id))
            if package_path is None or package_path.is_symlink():
                raise PolicyError("provider_package_missing")
            for target in target_paths:
                _assert_no_symlinks(root, target)
            _check_source_metadata(root, [root / target for target in target_paths], pin_value)
            rows[source_id] = {
                "source_id": source_id,
                "disposition": disposition,
                "provider_id": provider_id,
                "pin_type": pin_type,
                "pin": pin_value,
                "exports": sorted(required_exports),
                "target_paths": [target.as_posix() for target in target_paths],
            }
        elif disposition == "repository-owned-capability":
            if provider_id is not None:
                raise PolicyError("repository_source_provider_invalid")
            if not target_paths:
                raise PolicyError("repository_source_path_missing")
            for target in target_paths:
                _assert_no_symlinks(root, target)
            rows[source_id] = {
                "source_id": source_id,
                "disposition": disposition,
                "provider_id": None,
                "target_paths": [target.as_posix() for target in target_paths],
                "content_digest": digest([_path_digest(root, target) for target in target_paths]),
            }
        elif disposition == "report-only-external-plugin":
            # Deliberately do not resolve or execute a plugin command.  The
            # receipt records the report-only target so it cannot be confused
            # with a catalog source later.
            rows[source_id] = {
                "source_id": source_id,
                "disposition": disposition,
                "provider_id": None,
                "plugin_commands_invoked": [],
            }
        elif disposition == "retired-legacy-target":
            rows[source_id] = {
                "source_id": source_id,
                "disposition": disposition,
                "provider_id": None,
                "retired": True,
            }
        else:
            raise PolicyError("source_disposition_invalid")
    if set(rows) != set(policy.get("legacy_target_ids", [])):
        raise PolicyError("unregistered_legacy_target")
    if referenced_provider_ids != set(providers):
        raise PolicyError("unrepresented_catalog_provider")
    return rows


def _verify_origin_and_base(root: Path, expected_project: str) -> Dict[str, Any]:
    if not (root / ".git").exists():
        raise MaintenanceError("caller_not_repository", "non_transient")
    origin = _git(root, "remote", "get-url", "origin")
    if _origin_identity(origin).lower() != _origin_identity(expected_project).lower():
        raise MaintenanceError("origin_mismatch", "non_transient")
    try:
        base_sha = _git(root, "rev-parse", "--verify", "origin/main^{commit}")
    except MaintenanceError:
        raise MaintenanceError("origin_main_missing", "non_transient")
    if SHA1_PATTERN.fullmatch(base_sha) is None:
        raise MaintenanceError("origin_main_invalid", "non_transient")
    status_digest, status_lines = _git_status(root)
    return {
        "status": "dirty" if status_lines else "clean",
        "digest": status_digest,
        "changed_entry_count": len(status_lines),
        "base_sha": base_sha,
    }


def _verify_provider_checkout(provider: Mapping[str, Any], checkout: Path) -> Dict[str, Any]:
    """Read a provider checkout without trusting its mutable state."""
    if checkout.is_symlink() or not checkout.is_dir():
        raise MaintenanceError("provider_checkout_missing", "non_transient")
    origin = _git(checkout, "remote", "get-url", "origin")
    head = _git(checkout, "rev-parse", "HEAD")
    status_digest, status_lines = _git_status(checkout)
    expected_pin = str(provider["pin"]["value"])
    if _origin_identity(origin).lower() != _origin_identity(str(provider["canonical_source"])).lower():
        raise MaintenanceError("provider_checkout_origin_mismatch", "non_transient")
    if head != expected_pin:
        raise MaintenanceError("provider_checkout_pin_mismatch", "non_transient")
    if status_lines:
        raise MaintenanceError("provider_checkout_dirty", "non_transient")
    _assert_tree_no_symlinks(checkout)
    return {"status": "clean", "head": head, "digest": status_digest}


def observe_upstream_heads(
    providers: Mapping[str, Mapping[str, Any]],
    *,
    observed_refs: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Observe public Git HEADs without treating mutable refs as trusted pins."""
    supplied = dict(observed_refs or {})
    git_provider_ids = {
        provider_id
        for provider_id, provider in providers.items()
        if provider.get("pin", {}).get("type") == "git-commit"
    }
    if supplied and set(supplied) != git_provider_ids:
        raise PolicyError("observed_provider_set_invalid")
    observations: list[dict[str, Any]] = []
    for provider_id, provider in sorted(providers.items()):
        pin = provider.get("pin", {})
        pin_type = pin.get("type")
        pin_value = str(pin.get("value", ""))
        if pin_type != "git-commit":
            observations.append(
                {
                    "provider_id": provider_id,
                    "pin": pin_value,
                    "observed_head": None,
                    "status": "repository_owned",
                }
            )
            continue
        observed = supplied.get(provider_id)
        if observed is None:
            try:
                result = subprocess.run(
                    ["git", "ls-remote", str(provider["canonical_source"]), "HEAD"],
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=30,
                )
            except (OSError, subprocess.TimeoutExpired):
                raise MaintenanceError("upstream_observation_failed", "transient")
            if result.returncode:
                raise MaintenanceError("upstream_observation_failed", "transient")
            first_line = next((line for line in result.stdout.splitlines() if line.strip()), "")
            observed = first_line.split("\t", 1)[0]
        if not isinstance(observed, str) or SHA1_PATTERN.fullmatch(observed) is None:
            raise MaintenanceError("upstream_observation_invalid", "non_transient")
        observations.append(
            {
                "provider_id": provider_id,
                "pin": pin_value,
                "observed_head": observed,
                "status": "current" if observed == pin_value else "update_available",
            }
        )
    updates = [item["provider_id"] for item in observations if item["status"] == "update_available"]
    return {
        "status": "updates_available" if updates else "current",
        "observations": observations,
        "updates_available": updates,
        "digest": digest(observations),
    }


def _vendor_identity(path: Path) -> str:
    return sha256_bytes(str(path.resolve()).encode("utf-8"))


def _verify_vendor_hold(vendor: Path, hold: Optional[Mapping[str, Any]], status_digest: str, head: str) -> bool:
    if not isinstance(hold, Mapping) or hold.get("verified") is not True:
        return False
    return (
        hold.get("vendor_identity_digest") == _vendor_identity(vendor)
        and hold.get("status_digest") == status_digest
        and hold.get("head") == head
    )


def inspect_protected_vendor(vendor: Optional[Path], hold: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Fingerprint a protected vendor checkout; never repair or write it."""
    if vendor is None:
        return {"status": "not_configured", "digest": digest("not-configured")}
    vendor = Path(vendor)
    if vendor.is_symlink() or not vendor.exists():
        raise MaintenanceError("protected_vendor_missing", "non_transient")
    try:
        head = _git(vendor, "rev-parse", "HEAD")
        status_digest, status_lines = _git_status(vendor)
    except MaintenanceError:
        raise MaintenanceError("protected_vendor_unreadable", "non_transient")
    if status_lines and not _verify_vendor_hold(vendor, hold, status_digest, head):
        raise MaintenanceError("protected_vendor_ambiguous", "non_transient")
    return {
        "status": "held" if status_lines else "clean",
        "digest": status_digest,
        "head": head,
        "changed_entry_count": len(status_lines),
        "hold_verified": bool(status_lines),
    }


def _owner_only_evidence_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise MaintenanceError("vendor_evidence_missing", "non_transient")
    try:
        info = path.stat()
    except OSError:
        raise MaintenanceError("vendor_evidence_unreadable", "non_transient")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise MaintenanceError("vendor_evidence_permissions_unsafe", "non_transient")


def validate_vendor_preservation(
    vendor: Path,
    *,
    hold_path: Path,
    manifest_path: Path,
) -> Dict[str, Any]:
    """Bind a protected hold to immutable, reconstructable owner-local evidence."""
    vendor = Path(vendor).resolve()
    hold_path = Path(hold_path)
    manifest_path = Path(manifest_path)
    _owner_only_evidence_file(hold_path)
    _owner_only_evidence_file(manifest_path)
    hold = _load_object(hold_path, "vendor_hold")
    manifest = _load_object(manifest_path, "vendor_preservation")
    if hold.get("verified") is not True or manifest.get("schema_version") != SCHEMA_VERSION:
        raise MaintenanceError("vendor_evidence_incomplete", "non_transient")
    manifest_digest = _file_digest(manifest_path)
    if hold.get("preservation_manifest_sha256") != manifest_digest:
        raise MaintenanceError("vendor_manifest_digest_mismatch", "non_transient")
    source = manifest.get("source")
    classification = manifest.get("classification")
    artifact = manifest.get("artifact")
    reconstruction = manifest.get("reconstruction")
    if not all(isinstance(value, Mapping) for value in (source, classification, artifact, reconstruction)):
        raise MaintenanceError("vendor_evidence_incomplete", "non_transient")
    try:
        recorded_vendor = Path(str(source["checkout"])).resolve()
    except (KeyError, OSError):
        raise MaintenanceError("vendor_target_invalid", "non_transient")
    if recorded_vendor != vendor:
        raise MaintenanceError("vendor_target_mismatch", "non_transient")
    patch_name = artifact.get("file")
    if not isinstance(patch_name, str) or Path(patch_name).name != patch_name:
        raise MaintenanceError("vendor_patch_invalid", "non_transient")
    patch_path = manifest_path.parent / patch_name
    _owner_only_evidence_file(patch_path)
    patch_digest = _file_digest(patch_path)
    if artifact.get("sha256") != patch_digest or hold.get("preservation_patch_sha256") != patch_digest:
        raise MaintenanceError("vendor_patch_digest_mismatch", "non_transient")
    if classification.get("unique_uncommitted_content") is not False or reconstruction.get("verified") is not True:
        raise MaintenanceError("vendor_reconstruction_unverified", "non_transient")
    matching_commit = classification.get("matching_commit")
    if not isinstance(matching_commit, str) or SHA1_PATTERN.fullmatch(matching_commit) is None:
        raise MaintenanceError("vendor_matching_commit_invalid", "non_transient")
    head = _git(vendor, "rev-parse", "HEAD")
    status_digest, status_lines = _git_status(vendor)
    if (
        head != hold.get("head")
        or status_digest != hold.get("status_digest")
        or len(status_lines) != hold.get("changed_entry_count")
        or source.get("head") != head
    ):
        raise MaintenanceError("vendor_hold_state_changed", "non_transient")
    return {
        "status": "held",
        "vendor_identity_digest": _vendor_identity(vendor),
        "head": head,
        "status_digest": status_digest,
        "changed_entry_count": len(status_lines),
        "manifest_digest": manifest_digest,
        "patch_digest": patch_digest,
        "matching_commit": matching_commit,
        "reconstruction_verified": True,
    }


def verify_vendor_reconstruction(manifest_path: Path, proof_checkout: Path) -> Dict[str, Any]:
    """Prove the preserved tree matches its recorded upstream commit."""
    manifest_path = Path(manifest_path)
    proof_checkout = Path(proof_checkout).resolve()
    _owner_only_evidence_file(manifest_path)
    manifest = _load_object(manifest_path, "vendor_preservation")
    classification = manifest.get("classification", {})
    expected = classification.get("matching_commit") if isinstance(classification, Mapping) else None
    if not isinstance(expected, str) or SHA1_PATTERN.fullmatch(expected) is None:
        raise MaintenanceError("vendor_matching_commit_invalid", "non_transient")
    if proof_checkout.is_symlink() or not (proof_checkout / ".git").exists():
        raise MaintenanceError("vendor_reconstruction_missing", "non_transient")
    comparison = subprocess.run(
        ["git", "-C", str(proof_checkout), "diff", "--quiet", expected, "--"],
        capture_output=True,
        check=False,
    )
    if comparison.returncode or _git(proof_checkout, "ls-files", "--others", "--exclude-standard"):
        raise MaintenanceError("vendor_reconstruction_mismatch", "non_transient")
    return {"status": "verified", "matching_commit": expected, "tree_diff_exit": 0, "untracked_paths": 0}


def vendor_restoration_approval_token(evidence: Mapping[str, Any]) -> str:
    return "restore-vendor-" + digest(
        {
            "vendor_identity_digest": evidence.get("vendor_identity_digest"),
            "head": evidence.get("head"),
            "status_digest": evidence.get("status_digest"),
            "manifest_digest": evidence.get("manifest_digest"),
            "patch_digest": evidence.get("patch_digest"),
        }
    )[:24]


def build_vendor_restoration_plan(
    vendor: Path,
    *,
    hold_path: Path,
    manifest_path: Path,
    approval_token: Optional[str],
) -> Dict[str, Any]:
    """Return an exact, approval-bound plan; scheduled code never executes it."""
    vendor = Path(vendor).resolve()
    if vendor == Path(vendor.anchor) or vendor == Path.home().resolve() or len(vendor.parts) < 4:
        raise MaintenanceError("vendor_target_too_broad", "non_transient")
    evidence = validate_vendor_preservation(vendor, hold_path=hold_path, manifest_path=manifest_path)
    expected_token = vendor_restoration_approval_token(evidence)
    if approval_token != expected_token:
        raise MaintenanceError("vendor_restoration_approval_required", "non_transient")
    return {
        "status": "approved_plan",
        "target_identity_digest": evidence["vendor_identity_digest"],
        "expected_head": evidence["head"],
        "expected_status_digest": evidence["status_digest"],
        "preservation_manifest_digest": evidence["manifest_digest"],
        "actions": ["restore_recorded_worktree_to_head", "fast_forward_recorded_checkout_only"],
        "scheduled_execution_allowed": False,
    }


def _reconciliation_item(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MaintenanceError("reconciliation_item_invalid", "non_transient")
    item = dict(value)
    required = {"item_id", "item_type", "base_sha", "head_sha", "content_class", "disposition"}
    if not required.issubset(item):
        raise MaintenanceError("reconciliation_item_incomplete", "non_transient")
    if not isinstance(item["item_id"], str) or RECONCILIATION_ID_PATTERN.fullmatch(item["item_id"]) is None:
        raise MaintenanceError("reconciliation_item_id_invalid", "non_transient")
    if item["item_type"] not in RECONCILIATION_ITEM_TYPES:
        raise MaintenanceError("reconciliation_item_type_invalid", "non_transient")
    for field in ("base_sha", "head_sha"):
        if not isinstance(item[field], str) or SHA1_PATTERN.fullmatch(item[field]) is None:
            raise MaintenanceError("reconciliation_sha_invalid", "non_transient")
    if item["content_class"] not in RECONCILIATION_CONTENT_CLASSES:
        raise MaintenanceError("reconciliation_content_class_invalid", "non_transient")
    if item["disposition"] not in RECONCILIATION_DISPOSITIONS:
        raise MaintenanceError("reconciliation_disposition_invalid", "non_transient")
    actions = item.get("actions", [])
    if not isinstance(actions, list) or any(action not in CLEANUP_ACTIONS for action in actions):
        raise MaintenanceError("reconciliation_actions_invalid", "non_transient")
    preservation = item.get("preservation", [])
    if not isinstance(preservation, list) or not all(
        isinstance(entry, Mapping)
        and isinstance(entry.get("kind"), str)
        and isinstance(entry.get("reference"), str)
        and bool(entry["reference"])
        for entry in preservation
    ):
        raise MaintenanceError("reconciliation_preservation_invalid", "non_transient")
    content_groups = item.get("content_groups", [])
    if not isinstance(content_groups, list) or not all(
        isinstance(group, Mapping)
        and group.get("class") in RECONCILIATION_CONTENT_CLASSES
        and isinstance(group.get("paths"), list)
        and all(isinstance(path, str) and path for path in group["paths"])
        for group in content_groups
    ):
        raise MaintenanceError("reconciliation_content_groups_invalid", "non_transient")
    protected = item.get("protected", False)
    if not isinstance(protected, bool):
        raise MaintenanceError("reconciliation_protection_invalid", "non_transient")
    if protected and (item["disposition"] != "excluded" or actions):
        raise MaintenanceError("protected_cleanup_target", "non_transient")
    if item["content_class"] == "unique" and actions and not preservation:
        raise MaintenanceError("unique_content_not_preserved", "non_transient")
    item["actions"] = sorted(set(actions))
    item["preservation"] = sorted(
        (dict(entry) for entry in preservation),
        key=lambda entry: (entry["kind"], entry["reference"]),
    )
    item["content_groups"] = sorted(
        (dict(group) for group in content_groups),
        key=lambda group: (group["class"], tuple(group["paths"])),
    )
    item["protected"] = protected
    return item


def build_reconciliation_packet(items: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return a deterministic, non-mutating inventory and cleanup proposal."""
    normalized = [_reconciliation_item(item) for item in items]
    normalized.sort(key=lambda item: (item["item_type"], item["item_id"]))
    identifiers = [item["item_id"] for item in normalized]
    if len(identifiers) != len(set(identifiers)):
        raise MaintenanceError("duplicate_reconciliation_item", "non_transient")
    packet = {
        "schema_version": RECONCILIATION_SCHEMA_VERSION,
        "items": normalized,
        "cleanup_targets": [
            {"item_id": item["item_id"], "head_sha": item["head_sha"], "actions": item["actions"]}
            for item in normalized
            if item["actions"]
        ],
        "protected_exclusions": [item["item_id"] for item in normalized if item["protected"]],
    }
    packet["packet_digest"] = digest(packet)
    return packet


def cleanup_approval_token(packet: Mapping[str, Any]) -> str:
    packet_digest = packet.get("packet_digest")
    if not isinstance(packet_digest, str) or DIGEST_PATTERN.fullmatch(packet_digest) is None:
        raise MaintenanceError("reconciliation_packet_invalid", "non_transient")
    expected = digest({key: packet[key] for key in packet if key != "packet_digest"})
    if packet_digest != expected:
        raise MaintenanceError("reconciliation_packet_changed", "non_transient")
    return "approve-cleanup-" + packet_digest[:24]


def build_cleanup_plan(
    packet: Mapping[str, Any],
    *,
    live_heads: Mapping[str, str],
    approval_token: Optional[str],
) -> Dict[str, Any]:
    """Bind an approved cleanup batch to the exact revalidated remote heads."""
    expected_token = cleanup_approval_token(packet)
    if approval_token != expected_token:
        raise MaintenanceError("cleanup_approval_required", "non_transient")
    targets = packet.get("cleanup_targets")
    if not isinstance(targets, list):
        raise MaintenanceError("reconciliation_packet_invalid", "non_transient")
    actions: list[Dict[str, Any]] = []
    for target in targets:
        if not isinstance(target, Mapping):
            raise MaintenanceError("reconciliation_packet_invalid", "non_transient")
        item_id = target.get("item_id")
        expected_head = target.get("head_sha")
        if live_heads.get(item_id) != expected_head:
            raise MaintenanceError("cleanup_target_changed", "non_transient")
        actions.append({
            "item_id": item_id,
            "head_sha": expected_head,
            "actions": list(target.get("actions", [])),
        })
    protected = packet.get("protected_exclusions", [])
    if any(item_id in live_heads and item_id in {action["item_id"] for action in actions} for item_id in protected):
        raise MaintenanceError("protected_cleanup_target", "non_transient")
    return {
        "status": "approved_plan",
        "packet_digest": packet["packet_digest"],
        "actions": actions,
        "protected_exclusions": list(protected),
        "scheduled_execution_allowed": False,
    }


def classify_cleanup_result(plan: Mapping[str, Any], completed_item_ids: Iterable[str]) -> Dict[str, Any]:
    """Classify remote cleanup without ever upgrading a partial result."""
    actions = plan.get("actions")
    if not isinstance(actions, list):
        raise MaintenanceError("cleanup_plan_invalid", "non_transient")
    expected = [item.get("item_id") for item in actions if isinstance(item, Mapping)]
    completed = sorted(set(completed_item_ids))
    if any(item_id not in expected for item_id in completed):
        raise MaintenanceError("cleanup_result_invalid", "non_transient")
    remaining = [item_id for item_id in expected if item_id not in completed]
    return {
        "terminal_classification": "no_action" if not expected else ("prepared" if not remaining else "partial"),
        "result": "cleanup_not_needed" if not expected else ("cleanup_completed" if not remaining else "cleanup_partial"),
        "completed_item_ids": completed,
        "remaining_item_ids": remaining,
    }


def _private_data_in_bytes(data: bytes) -> bool:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return any(pattern.search(text) for pattern in PRIVATE_DATA_PATTERNS)


def semantic_bytes_digest(data: bytes, path: Optional[Path] = None) -> str:
    """Hash JSON semantically, excluding observation-only metadata."""
    if path is not None and path.suffix.lower() == ".json":
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        else:
            return digest(_without_volatile(value))
    return sha256_bytes(data)


def _allowlisted_path(relative: Path, allowlist: Iterable[str]) -> bool:
    value = relative.as_posix()
    for entry in allowlist:
        if not isinstance(entry, str):
            continue
        if entry.endswith("/") and value.startswith(entry):
            return True
        if value == entry:
            return True
    return False


def _candidate_path(relative: str) -> Path:
    path = _repository_relative(relative)
    if path.parts[0] in {".git", ".github"} or any(part.startswith(".") for part in path.parts):
        raise MaintenanceError("unexpected_candidate_path", "non_transient")
    return path


def _candidate_bytes(value: Any) -> bytes:
    if isinstance(value, Path):
        if value.is_symlink() or not value.is_file():
            raise MaintenanceError("candidate_source_invalid", "non_transient")
        try:
            return value.read_bytes()
        except (OSError, IOError):
            raise MaintenanceError("candidate_source_unreadable", "non_transient")
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, Mapping) or isinstance(value, list):
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    raise MaintenanceError("candidate_content_invalid", "non_transient")


def stage_candidate(
    root: Path,
    stage_dir: Path,
    *,
    base_sha: Optional[str] = None,
    allowlist: Optional[Iterable[str]] = None,
    proposed_files: Optional[Mapping[str, Any]] = None,
    run_readiness_checks: bool = True,
) -> Dict[str, Any]:
    """Clone a clean base and write only deterministic, allowlisted proposals."""
    root = Path(root).resolve()
    stage_dir = Path(stage_dir).resolve()
    if stage_dir == root or root in stage_dir.parents:
        raise MaintenanceError("candidate_stage_inside_caller", "non_transient")
    if stage_dir.is_symlink() or stage_dir.exists() and not stage_dir.is_dir():
        raise MaintenanceError("candidate_stage_unsafe", "non_transient")
    if stage_dir.exists() and any(stage_dir.iterdir()):
        raise MaintenanceError("candidate_stage_not_empty", "non_transient")
    base_sha = base_sha or _git(root, "rev-parse", "--verify", "origin/main^{commit}")
    if SHA1_PATTERN.fullmatch(base_sha) is None:
        raise MaintenanceError("candidate_base_invalid", "non_transient")
    stage_dir.parent.mkdir(parents=True, exist_ok=True)
    clone = subprocess.run(
        ["git", "clone", "--no-local", "--no-checkout", str(root), str(stage_dir)],
        text=True,
        capture_output=True,
        check=False,
    )
    if clone.returncode:
        raise MaintenanceError("candidate_clone_failed", "transient")
    checkout = subprocess.run(
        ["git", "-C", str(stage_dir), "checkout", "--detach", base_sha],
        text=True,
        capture_output=True,
        check=False,
    )
    if checkout.returncode:
        raise MaintenanceError("candidate_base_unavailable", "non_transient")
    status_digest, status_lines = _git_status(stage_dir)
    if status_lines:
        raise MaintenanceError("candidate_base_dirty", "non_transient")
    if _git(stage_dir, "rev-parse", "HEAD") != base_sha:
        raise MaintenanceError("candidate_base_mismatch", "non_transient")
    _assert_tree_no_symlinks(stage_dir)

    allowed = list(allowlist or [])
    changed: list[dict[str, str]] = []
    for raw_path, raw_content in sorted((proposed_files or {}).items()):
        relative = _candidate_path(raw_path)
        if not _allowlisted_path(relative, allowed):
            raise MaintenanceError("candidate_path_not_allowlisted", "non_transient")
        data = _candidate_bytes(raw_content)
        if _private_data_in_bytes(data):
            raise MaintenanceError("candidate_private_data", "non_transient")
        destination = stage_dir / relative
        _assert_no_symlinks(stage_dir, relative, allow_missing=True)
        current = destination.read_bytes() if destination.is_file() and not destination.is_symlink() else None
        if current is not None and semantic_bytes_digest(current, relative) == semantic_bytes_digest(data, relative):
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and not destination.is_file():
            raise MaintenanceError("candidate_destination_invalid", "non_transient")
        destination.write_bytes(data)
        changed.append({"path": relative.as_posix(), "digest": semantic_bytes_digest(data, relative)})

    final_status_digest, final_status_lines = _git_status(stage_dir)
    _assert_tree_no_symlinks(stage_dir)
    final_paths = sorted(
        line[3:] if len(line) > 3 else line
        for line in final_status_lines
        if line and len(line) >= 3
    )
    final_relative = [_candidate_path(path) for path in final_paths]
    if any(not _allowlisted_path(path, allowed) for path in final_relative):
        raise MaintenanceError("candidate_diff_not_allowlisted", "non_transient")
    readiness = {"status": "not_run", "checks": []}
    if run_readiness_checks:
        readiness = run_candidate_readiness(stage_dir)
    changed_digest = digest(sorted(item["path"] for item in changed))
    return {
        "status": "changed" if final_relative else "no_action",
        "base_sha": base_sha,
        "changed_paths": sorted(path.as_posix() for path in final_relative),
        "changed_paths_digest": digest(sorted(path.as_posix() for path in final_relative)),
        "semantic_outputs_digest": digest(changed),
        "status_digest": final_status_digest,
        "readiness": readiness,
        "no_op": not final_relative,
    }


def run_candidate_readiness(stage_dir: Path) -> Dict[str, Any]:
    """Run read-only catalog and bootstrap checks inside the disposable clone."""
    checks: list[str] = []
    build = stage_dir / "scripts" / "build-capability-registry.py"
    bootstrap = stage_dir / "scripts" / "bootstrap-stack.py"
    if not build.is_file() or not bootstrap.is_file():
        raise MaintenanceError("candidate_readiness_scripts_missing", "non_transient")
    for script, arguments, name in (
        (build, ["--root", str(stage_dir), "--check"], "catalog"),
        (bootstrap, ["--root", str(stage_dir)], "bootstrap"),
    ):
        result = subprocess.run(
            [sys.executable, str(script), *arguments],
            cwd=stage_dir,
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode:
            raise MaintenanceError(f"candidate_{name}_check_failed", "non_transient")
        checks.append(name)
    return {"status": "passed", "checks": checks}


CANONICAL_PR_MARKER = "stack-maintenance/v1"
CANONICAL_PR_COMMIT_MESSAGE = "chore(stack-maintenance): prepare candidate"


def _status_entries(root: Path) -> list[dict[str, str]]:
    """Return porcelain status entries without exposing their absolute root."""
    _, raw_lines = _git_status(root)
    entries: list[dict[str, str]] = []
    for line in raw_lines:
        if not line.strip():
            continue
        if len(line) < 4:
            raise MaintenanceError("candidate_status_invalid", "non_transient")
        path = line[3:]
        # A rename contains two paths.  It is not a generated candidate shape,
        # so fail closed instead of guessing which side is safe to stage.
        if " -> " in path:
            raise MaintenanceError("candidate_rename_not_allowed", "non_transient")
        try:
            relative = _candidate_path(path)
        except MaintenanceError:
            raise
        entries.append({"code": line[:2], "path": relative.as_posix()})
    return entries


def _candidate_changed_paths(root: Path, base_sha: str) -> list[str]:
    """Return the tracked diff plus untracked paths in a candidate checkout."""
    tracked = _git(root, "diff", "--name-only", f"{base_sha}...HEAD")
    tracked_paths = [
        _candidate_path(line).as_posix()
        for line in tracked.splitlines()
        if line.strip()
    ]
    untracked_paths = [
        entry["path"]
        for entry in _status_entries(root)
        if entry["code"] == "??"
    ]
    return sorted(set(tracked_paths + untracked_paths))


def _validate_candidate_allowlist(root: Path, allowlist: Iterable[str]) -> list[str]:
    entries = _status_entries(root)
    paths = sorted({entry["path"] for entry in entries})
    if any(not _allowlisted_path(Path(path), allowlist) for path in paths):
        raise MaintenanceError("candidate_diff_not_allowlisted", "non_transient")
    return paths


def _assert_expected_commit_ancestry(
    stage_dir: Path,
    *,
    base_sha: str,
    expected_commit_count: int = 1,
    expected_commits: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    if SHA1_PATTERN.fullmatch(base_sha) is None:
        raise MaintenanceError("candidate_base_invalid", "non_transient")
    head_sha = _git(stage_dir, "rev-parse", "HEAD")
    if SHA1_PATTERN.fullmatch(head_sha) is None:
        raise MaintenanceError("candidate_head_invalid", "non_transient")
    ancestry = subprocess.run(
        ["git", "-C", str(stage_dir), "merge-base", "--is-ancestor", base_sha, head_sha],
        text=True,
        capture_output=True,
        check=False,
    )
    if ancestry.returncode:
        raise MaintenanceError("candidate_ancestry_invalid", "non_transient")
    commits = [
        item
        for item in _git(stage_dir, "rev-list", "--reverse", f"{base_sha}..{head_sha}").splitlines()
        if item.strip()
    ]
    if len(commits) != expected_commit_count:
        raise MaintenanceError("candidate_commit_count_invalid", "non_transient")
    if expected_commits is not None:
        expected = list(expected_commits)
        if expected != commits:
            raise MaintenanceError("candidate_commit_set_invalid", "non_transient")
    status = _status_entries(stage_dir)
    if status:
        raise MaintenanceError("candidate_not_clean", "non_transient")
    return {"head_sha": head_sha, "commits": commits, "commit_count": len(commits)}


def _run_pr_readiness(
    stage_dir: Path,
    *,
    readiness_runner: Optional[Any] = None,
) -> Dict[str, Any]:
    """Run local gates through an injectable boundary before remote mutation.

    The default keeps the U3 catalog/bootstrap checks as the minimum local
    gate.  The scheduler supplies a checked-in full-gate runner when it is
    enabled; tests inject a deterministic runner and never contact GitHub.
    """
    if readiness_runner is not None:
        try:
            result = readiness_runner(Path(stage_dir))
        except MaintenanceError:
            raise
        except Exception:
            raise MaintenanceError("candidate_readiness_failed", "non_transient")
        if result is False:
            raise MaintenanceError("candidate_readiness_failed", "non_transient")
        if result is None or result is True:
            return {"status": "passed", "checks": ["injected"]}
        if not isinstance(result, Mapping) or result.get("status") != "passed":
            raise MaintenanceError("candidate_readiness_failed", "non_transient")
        return dict(result)
    result = run_candidate_readiness(stage_dir)
    if result.get("status") != "passed":
        raise MaintenanceError("candidate_readiness_failed", "non_transient")
    # This check is intentionally local and deterministic; no network or
    # GitHub authority is required to prove whitespace safety.
    _git_mutate(stage_dir, "diff", "--check", error_code="candidate_diff_check_failed")
    return {**result, "checks": [*result.get("checks", []), "git-diff-check"]}


def _commit_candidate(
    stage_dir: Path,
    *,
    base_sha: str,
    branch: str,
    allowlist: Iterable[str],
    expected_changed_paths_digest: Optional[str] = None,
) -> Dict[str, Any]:
    """Create one explicit allowlisted commit in the disposable checkout."""
    if not BRANCH_PATTERN.fullmatch(branch) or branch in {"main", "master"}:
        raise MaintenanceError("canonical_branch_invalid", "non_transient")
    if _git(stage_dir, "rev-parse", "HEAD") != base_sha:
        raise MaintenanceError("candidate_base_mismatch", "non_transient")
    paths = _validate_candidate_allowlist(stage_dir, allowlist)
    if not paths:
        return {
            "status": "no_action",
            "base_sha": base_sha,
            "head_sha": _git(stage_dir, "rev-parse", "HEAD"),
            "commits": [],
            "commit_count": 0,
            "changed_paths": [],
            "changed_paths_digest": digest([]),
        }
    changed_digest = digest(paths)
    if expected_changed_paths_digest is not None and changed_digest != expected_changed_paths_digest:
        raise MaintenanceError("changed_paths_digest_mismatch", "non_transient")
    # A new branch is created only in the disposable clone.  The explicit
    # path list is the allowlist boundary; whole-tree staging is forbidden.
    _git_mutate(stage_dir, "switch", "--create", branch, error_code="candidate_branch_create_failed")
    _git_mutate(stage_dir, "add", "--", *paths, error_code="candidate_stage_failed")
    staged = [
        _candidate_path(line).as_posix()
        for line in _git(stage_dir, "diff", "--cached", "--name-only").splitlines()
        if line.strip()
    ]
    if staged != paths:
        raise MaintenanceError("candidate_staged_paths_invalid", "non_transient")
    _git_mutate(stage_dir, "diff", "--cached", "--check", error_code="candidate_diff_check_failed")
    # Disposable clones do not inherit repository-local identity settings.
    # Keep the generated commit deterministic without changing the caller.
    _git_mutate(stage_dir, "config", "user.name", "Stack Maintenance", error_code="candidate_identity_failed")
    _git_mutate(stage_dir, "config", "user.email", "stack-maintenance@localhost", error_code="candidate_identity_failed")
    _git_mutate(
        stage_dir,
        "commit",
        "--no-verify",
        "-m",
        f"{CANONICAL_PR_COMMIT_MESSAGE} [{CANONICAL_PR_MARKER}]",
        error_code="candidate_commit_failed",
    )
    metadata = _assert_expected_commit_ancestry(stage_dir, base_sha=base_sha)
    actual_paths = _candidate_changed_paths(stage_dir, base_sha)
    if actual_paths != paths:
        raise MaintenanceError("candidate_changed_paths_invalid", "non_transient")
    actual_digest = digest(actual_paths)
    if actual_digest != changed_digest:
        raise MaintenanceError("changed_paths_digest_mismatch", "non_transient")
    return {
        "status": "changed",
        "base_sha": base_sha,
        "head_sha": metadata["head_sha"],
        "commits": metadata["commits"],
        "commit_count": metadata["commit_count"],
        "changed_paths": actual_paths,
        "changed_paths_digest": actual_digest,
    }


def _pr_marker_body(
    *,
    marker: str,
    base_sha: str,
    input_fingerprint_value: Optional[str],
    changed_paths_digest: str,
    commits: Iterable[str],
) -> str:
    values = [
        f"<!-- {marker} -->",
        f"<!-- stack-maintenance/base-sha: {base_sha} -->",
        f"<!-- stack-maintenance/changed-paths-digest: {changed_paths_digest} -->",
        f"<!-- stack-maintenance/input-fingerprint: {input_fingerprint_value or 'unknown'} -->",
        f"<!-- stack-maintenance/commits: {','.join(commits)} -->",
    ]
    return "\n".join(
        [
            "## Stack maintenance candidate",
            "",
            "This draft was prepared from a disposable clean `origin/main` base.",
            "The scheduled lane does not merge, install, or publish this change.",
            "",
            *values,
            "",
        ]
    )


def _body_metadata(body: Any, key: str) -> Optional[str]:
    if not isinstance(body, str):
        return None
    match = re.search(rf"<!--\s*stack-maintenance/{re.escape(key)}:\s*([^ >]+)\s*-->", body)
    return match.group(1) if match else None


def _record_value(record: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in record and record[name] is not None:
            return record[name]
    return None


def _normalise_pr_records(value: Any) -> list[Mapping[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        value = value.get("pull_requests", value.get("prs", []))
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise MaintenanceError("github_candidates_invalid", "non_transient")
    return list(value)


def _candidate_pr_identity(record: Mapping[str, Any]) -> str:
    number = _record_value(record, "number", "id")
    if number is not None:
        return str(number)
    return digest({key: record[key] for key in sorted(record) if key not in {"body", "title"}})[:16]


def _verify_existing_candidate(
    record: Mapping[str, Any],
    *,
    branch: str,
    marker: str,
    base_sha: str,
    changed_paths_digest: Optional[str],
    remote_branch: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Validate an existing PR before allowing reuse."""
    head_ref = _record_value(record, "head_ref_name", "headRefName", "head")
    base_ref = _record_value(record, "base_ref_name", "baseRefName", "base")
    if head_ref not in {branch, f"refs/heads/{branch}"}:
        raise MaintenanceError("canonical_branch_mismatch", "non_transient")
    if base_ref not in {None, "main", "refs/heads/main"}:
        raise MaintenanceError("canonical_base_branch_mismatch", "non_transient")
    draft_value = _record_value(record, "is_draft", "isDraft", "draft")
    if draft_value is False:
        raise MaintenanceError("canonical_pr_not_draft", "non_transient")
    body = _record_value(record, "body", "description")
    if marker not in body if isinstance(body, str) else True:
        raise MaintenanceError("canonical_marker_missing", "non_transient")
    recorded_base = _body_metadata(body, "base-sha")
    recorded_base = recorded_base or _record_value(record, "base_sha", "baseSha", "base_ref_oid", "baseRefOid")
    if recorded_base != base_sha:
        raise MaintenanceError("canonical_base_sha_mismatch", "non_transient")
    recorded_digest = _record_value(record, "changed_paths_digest", "changedPathsDigest")
    recorded_digest = recorded_digest or _body_metadata(body, "changed-paths-digest")
    if not isinstance(recorded_digest, str) or not DIGEST_PATTERN.fullmatch(recorded_digest):
        raise MaintenanceError("canonical_changed_paths_digest_missing", "non_transient")
    if changed_paths_digest is not None and recorded_digest != changed_paths_digest:
        raise MaintenanceError("canonical_changed_paths_digest_mismatch", "non_transient")
    head_sha = _record_value(record, "head_sha", "headSha", "head_ref_oid", "headRefOid", "sha")
    if not isinstance(head_sha, str) or SHA1_PATTERN.fullmatch(head_sha) is None:
        raise MaintenanceError("canonical_head_sha_missing", "non_transient")
    remote_sha = _record_value(remote_branch or {}, "head_sha", "headSha", "sha", "object_sha", "objectSha")
    if not isinstance(remote_sha, str) or remote_sha != head_sha:
        raise MaintenanceError("canonical_remote_head_changed", "non_transient")
    commit_count = _record_value(record, "commit_count", "commitCount")
    commits = _record_value(record, "commits", "commit_shas", "commitShas")
    if commits is None:
        recorded_commits = _body_metadata(body, "commits")
        commits = recorded_commits.split(",") if recorded_commits else None
    if isinstance(commits, list):
        normalized_commits = [
            item
            if isinstance(item, str)
            else _record_value(item, "sha", "oid", "commit_sha", "commitSha")
            if isinstance(item, Mapping)
            else None
            for item in commits
        ]
        if not all(isinstance(item, str) and SHA1_PATTERN.fullmatch(item) for item in normalized_commits):
            raise MaintenanceError("canonical_commit_set_invalid", "non_transient")
        commits = normalized_commits
        if commit_count is None:
            commit_count = len(commits)
    if commit_count != 1:
        raise MaintenanceError("canonical_commit_count_invalid", "non_transient")
    labels = _record_value(record, "labels")
    return {
        "number": _record_value(record, "number", "id"),
        "url": _record_value(record, "url", "html_url", "htmlUrl"),
        "branch": branch,
        "marker": marker,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "changed_paths_digest": recorded_digest,
        "commit_count": commit_count,
        "labels": labels if isinstance(labels, list) else [],
        "labels_missing": not bool(labels),
    }


class GitHubCommandBoundary:
    """Small production adapter; tests inject an in-memory equivalent.

    Only this adapter knows how to invoke ``gh`` or ``git push``.  The lane
    above it reasons over structured records and therefore cannot accidentally
    use ``git add -A``, force-push, or push ``main``.
    """

    def __init__(self, repository: str, *, root: Optional[Path] = None, command_runner: Any = subprocess.run) -> None:
        self.repository = repository
        self.root = Path(root or ROOT)
        self.command_runner = command_runner

    def _run(self, command: list[str], *, cwd: Optional[Path] = None, error_code: str) -> str:
        try:
            result = self.command_runner(command, cwd=str(cwd) if cwd is not None else None, text=True, capture_output=True, check=False)
        except (OSError, TypeError):
            raise MaintenanceError(error_code, "transient")
        if result.returncode:
            raise MaintenanceError(error_code, "transient")
        return str(result.stdout or "").strip()

    def list_open_candidates(self, repository: str, branch: str, marker: str) -> list[Mapping[str, Any]]:
        output = self._run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                repository,
                "--state",
                "open",
                "--head",
                branch,
                "--json",
                "number,headRefName,baseRefName,headRefOid,baseRefOid,isDraft,body,labels,url,commits",
            ],
            error_code="github_list_failed",
        )
        try:
            value = json.loads(output or "[]")
        except json.JSONDecodeError:
            raise MaintenanceError("github_candidates_invalid", "transient")
        return _normalise_pr_records(value)

    def remote_branch(self, repository: str, branch: str) -> Optional[Mapping[str, Any]]:
        command = ["gh", "api", f"repos/{repository}/git/ref/heads/{branch}"]
        try:
            result = self.command_runner(command, text=True, capture_output=True, check=False)
        except (OSError, TypeError):
            raise MaintenanceError("github_branch_query_failed", "transient")
        if result.returncode:
            # ``gh api`` uses a non-zero status for a missing ref.  Treat only
            # an explicit 404 as an absent branch; every other error blocks.
            if "404" in str(result.stderr or ""):
                return None
            raise MaintenanceError("github_branch_query_failed", "transient")
        output = str(result.stdout or "").strip()
        try:
            value = json.loads(output or "{}")
        except json.JSONDecodeError:
            raise MaintenanceError("github_branch_invalid", "transient")
        if not value:
            return None
        obj = value.get("object", {}) if isinstance(value, Mapping) else {}
        return {"sha": obj.get("sha")} if isinstance(obj, Mapping) else None

    def push_branch(
        self,
        repository: str,
        branch: str,
        stage_dir: Path,
        *,
        expected_remote_head: Optional[str] = None,
    ) -> Mapping[str, Any]:
        if branch in {"main", "master"} or not BRANCH_PATTERN.fullmatch(branch):
            raise MaintenanceError("push_protected_branch", "non_transient")
        remote_url = _git(self.root, "remote", "get-url", "origin")
        _git_mutate(stage_dir, "remote", "set-url", "origin", remote_url, error_code="candidate_remote_config_failed")
        if expected_remote_head is None:
            arguments = ["push", "--set-upstream", "origin", f"refs/heads/{branch}:refs/heads/{branch}"]
        else:
            # A non-force push is the only permitted update shape.  The
            # expected remote SHA is checked by the caller before this call;
            # ``--force`` and ref deletion are intentionally impossible here.
            arguments = ["push", "--set-upstream", "origin", f"refs/heads/{branch}:refs/heads/{branch}"]
        _git_mutate(stage_dir, *arguments, error_code="github_push_failed")
        head = _git(stage_dir, "rev-parse", "HEAD")
        return {"branch": branch, "head_sha": head, "expected_remote_head": expected_remote_head}

    def create_draft_pr(self, repository: str, branch: str, title: str, body: str, *, labels: Optional[list[str]] = None) -> Mapping[str, Any]:
        command = ["gh", "pr", "create", "--repo", repository, "--draft", "--base", "main", "--head", branch, "--title", title, "--body", body]
        if labels:
            command.extend(["--label", ",".join(labels)])
        output = self._run(command, error_code="github_pr_create_failed")
        return {"url": output, "head_ref_name": branch, "is_draft": True}

    def update_draft_pr(self, repository: str, number: Any, title: str, body: str, *, labels: Optional[list[str]] = None) -> Mapping[str, Any]:
        command = ["gh", "pr", "edit", str(number), "--repo", repository, "--title", title, "--body", body]
        if labels:
            command.extend(["--add-label", ",".join(labels)])
        self._run(command, error_code="github_pr_update_failed")
        return {"number": number, "updated": True}


def _gateway_call(gateway: Any, method: str, *arguments: Any, **keywords: Any) -> Any:
    function = getattr(gateway, method, None)
    if not callable(function):
        raise MaintenanceError("github_boundary_invalid", "non_transient")
    try:
        return function(*arguments, **keywords)
    except MaintenanceError:
        raise
    except Exception:
        raise MaintenanceError(f"github_{method}_failed", "transient")


def _lane_result(
    *,
    classification: str,
    result: str,
    reason: Optional[str],
    pr_state: Mapping[str, Any],
    checks: Mapping[str, Any],
    changed_paths_digest: str,
    stage_retained: bool = False,
) -> Dict[str, Any]:
    state = dict(pr_state)
    state.setdefault("status", result)
    state["digest"] = digest({key: value for key, value in state.items() if key != "digest"})
    payload: Dict[str, Any] = {
        "terminal_classification": classification,
        "result": result,
        "pr_state": state,
        "checks": dict(checks),
        "changed_paths_digest": changed_paths_digest,
        "stage_retained": stage_retained,
    }
    if reason:
        payload["reason_code"] = reason
    return payload


def prepare_canonical_pr(
    root: Path = ROOT,
    stage_dir: Optional[Path] = None,
    *,
    base_sha: Optional[str] = None,
    allowlist: Optional[Iterable[str]] = None,
    input_fingerprint_value: Optional[str] = None,
    policy: Optional[Mapping[str, Any]] = None,
    github: Any,
    readiness_runner: Optional[Any] = None,
    expected_changed_paths_digest: Optional[str] = None,
    marker: Optional[str] = None,
    branch: Optional[str] = None,
    labels: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """Prepare or reuse the one safe canonical draft PR.

    All remote actions are delegated to ``github``.  Passing an in-memory
    boundary is sufficient for the complete focused test suite; no test needs
    credentials or a live repository.
    """
    policy = dict(policy or load_policy())
    candidate_policy = policy.get("canonical_candidate", {})
    branch = branch or str(candidate_policy.get("branch", "automation/stack-maintenance"))
    marker = marker or str(candidate_policy.get("marker", CANONICAL_PR_MARKER))
    repository = str(policy.get("authority", {}).get("project_identity", "thecolormaroun/stack"))
    allowlist = list(allowlist or policy.get("diff_allowlist", []))
    base_sha = base_sha or _git(Path(root), "rev-parse", "--verify", "origin/main^{commit}")
    if SHA1_PATTERN.fullmatch(base_sha) is None:
        return _lane_result(
            classification="blocked",
            result="candidate_base_invalid",
            reason="candidate_base_invalid",
            pr_state={"status": "blocked"},
            checks={"remote_mutation_started": False},
            changed_paths_digest=digest([]),
        )
    if stage_dir is not None and (Path(stage_dir).is_symlink() or not Path(stage_dir).is_dir()):
        return _lane_result(
            classification="blocked",
            result="candidate_stage_missing",
            reason="candidate_stage_missing",
            pr_state={"status": "blocked"},
            checks={"remote_mutation_started": False},
            changed_paths_digest=digest([]),
        )

    try:
        records = _normalise_pr_records(_gateway_call(github, "list_open_candidates", repository, branch, marker))
        # ``list_open_candidates`` is expected to scope by branch, but retain a
        # second marker/lineage check so a permissive test or adapter cannot
        # turn an unrelated PR into the canonical candidate.
        records = [
            item
            for item in records
            if (
                _record_value(item, "head_ref_name", "headRefName", "head") is None
                or _record_value(item, "head_ref_name", "headRefName", "head") in {branch, f"refs/heads/{branch}"}
                or marker in str(_record_value(item, "body", "description") or "")
            )
        ]
        if len(records) > 1:
            return _lane_result(
                classification="blocked",
                result="canonical_pr_ambiguous",
                reason="canonical_pr_ambiguous",
                pr_state={"status": "ambiguous", "candidate_count": len(records)},
                checks={"remote_mutation_started": False, "candidate_ids": [_candidate_pr_identity(item) for item in records]},
                changed_paths_digest=expected_changed_paths_digest or digest([]),
            )
        remote = _gateway_call(github, "remote_branch", repository, branch)
        if remote is not None and not isinstance(remote, Mapping):
            raise MaintenanceError("github_branch_invalid", "non_transient")
        if records:
            try:
                safe = _verify_existing_candidate(
                    records[0],
                    branch=branch,
                    marker=marker,
                    base_sha=base_sha,
                    changed_paths_digest=expected_changed_paths_digest,
                    remote_branch=remote,
                )
            except MaintenanceError as error:
                return _lane_result(
                    classification="blocked",
                    result=error.code,
                    reason=error.code,
                    pr_state={"status": "blocked", "candidate_id": _candidate_pr_identity(records[0])},
                    checks={"remote_mutation_started": False},
                    changed_paths_digest=expected_changed_paths_digest or digest([]),
                )
            return _lane_result(
                classification="prepared",
                result="canonical_pr_reused",
                reason=None,
                pr_state={"status": "reused", **safe},
                checks={
                    "canonical_candidate_count": 1,
                    "lineage_verified": True,
                    "base_sha_verified": True,
                    "remote_head_verified": True,
                    "expected_commit_count": 1,
                    "allowlist_verified": True,
                    "optional_labels_missing": safe["labels_missing"],
                    "remote_mutation_started": False,
                },
                changed_paths_digest=safe["changed_paths_digest"],
            )
        if remote is not None:
            return _lane_result(
                classification="blocked",
                result="canonical_branch_without_pr",
                reason="canonical_branch_without_pr",
                pr_state={"status": "blocked"},
                checks={"remote_mutation_started": False, "remote_branch_present": True},
                changed_paths_digest=expected_changed_paths_digest or digest([]),
            )
        if stage_dir is None:
            return _lane_result(
                classification="blocked",
                result="candidate_stage_missing",
                reason="candidate_stage_missing",
                pr_state={"status": "blocked"},
                checks={"remote_mutation_started": False},
                changed_paths_digest=digest([]),
            )
        local = _commit_candidate(
            Path(stage_dir),
            base_sha=base_sha,
            branch=branch,
            allowlist=allowlist,
            expected_changed_paths_digest=expected_changed_paths_digest,
        )
        if local["status"] == "no_action":
            return _lane_result(
                classification="no_action",
                result="candidate_no_action",
                reason=None,
                pr_state={"status": "not_created"},
                checks={"remote_mutation_started": False, "local_candidate_no_action": True},
                changed_paths_digest=local["changed_paths_digest"],
                stage_retained=True,
            )
        readiness = _run_pr_readiness(Path(stage_dir), readiness_runner=readiness_runner)
        body = _pr_marker_body(
            marker=marker,
            base_sha=base_sha,
            input_fingerprint_value=input_fingerprint_value,
            changed_paths_digest=local["changed_paths_digest"],
            commits=local["commits"],
        )
        if _private_data_in_bytes(body.encode("utf-8")):
            raise MaintenanceError("candidate_private_data", "non_transient")
        pushed = _gateway_call(
            github,
            "push_branch",
            repository,
            branch,
            Path(stage_dir),
            expected_remote_head=None,
        )
        if not isinstance(pushed, Mapping):
            raise MaintenanceError("github_push_result_invalid", "transient")
        pushed_head = pushed.get("head_sha")
        if pushed_head != local["head_sha"]:
            raise MaintenanceError("github_push_head_mismatch", "non_transient")
        try:
            created = _gateway_call(
                github,
                "create_draft_pr",
                repository,
                branch,
                "chore: prepare Stack maintenance candidate",
                body,
                labels=labels,
            )
        except MaintenanceError as error:
            return _lane_result(
                classification="partial",
                result="github_pr_create_failed",
                reason=error.code,
                pr_state={"status": "branch_pushed", "head_sha": local["head_sha"], "base_sha": base_sha},
                checks={
                    "readiness": readiness,
                    "remote_mutation_started": True,
                    "branch_pushed": True,
                    "pr_created": False,
                    "recoverable_stage": True,
                },
                changed_paths_digest=local["changed_paths_digest"],
                stage_retained=True,
            )
        if not isinstance(created, Mapping):
            raise MaintenanceError("github_pr_create_result_invalid", "transient")
        return _lane_result(
            classification="prepared",
            result="draft_pr_created",
            reason=None,
            pr_state={
                "status": "created",
                "number": _record_value(created, "number", "id"),
                "url": _record_value(created, "url", "html_url", "htmlUrl"),
                "branch": branch,
                "marker": marker,
                "base_sha": base_sha,
                "head_sha": local["head_sha"],
                "changed_paths_digest": local["changed_paths_digest"],
                "commit_count": local["commit_count"],
            },
            checks={
                "readiness": readiness,
                "canonical_candidate_count": 0,
                "lineage_verified": True,
                "base_sha_verified": True,
                "expected_commit_count": 1,
                "allowlist_verified": True,
                "changed_paths_digest_verified": True,
                "remote_mutation_started": True,
                "branch_pushed": True,
                "pr_created": True,
                "optional_labels_missing": not bool(_record_value(created, "labels")),
            },
            changed_paths_digest=local["changed_paths_digest"],
            stage_retained=True,
        )
    except MaintenanceError as error:
        classification = "blocked" if error.retry_class == "non_transient" else ("partial" if stage_dir is not None and Path(stage_dir).exists() else "failed")
        return _lane_result(
            classification=classification,
            result=error.code,
            reason=error.code,
            pr_state={"status": "failed"},
            checks={"remote_mutation_started": False, "recoverable_stage": bool(stage_dir and Path(stage_dir).exists())},
            changed_paths_digest=expected_changed_paths_digest or digest([]),
            stage_retained=bool(stage_dir and Path(stage_dir).exists()),
        )


def audit_sources(
    root: Path = ROOT,
    *,
    policy: Optional[Mapping[str, Any]] = None,
    sources: Optional[Mapping[str, Any]] = None,
    registry_path: Optional[Path] = None,
    lock_path: Optional[Path] = None,
    protected_vendor: Optional[Path] = None,
    vendor_hold: Optional[Mapping[str, Any]] = None,
    provider_checkouts: Optional[Mapping[str, Path]] = None,
    observe_remotes: bool = False,
    observed_refs: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Audit all declared sources with no writes outside caller-provided stage."""
    root = Path(root).resolve()
    policy = dict(policy or load_policy())
    sources = dict(sources or load_sources())
    validate_policy(policy, sources)
    registry_path = Path(registry_path) if registry_path is not None else root / "registry" / "upstreams.json"
    lock_path = Path(lock_path) if lock_path is not None else root / "upstreams.lock.json"
    registry, lock = load_upstream_metadata(registry_path, lock_path)
    providers = validate_upstream_metadata(registry, lock)
    source_rows = validate_source_catalog(root, policy, sources, registry, lock)
    checkout_state = _verify_origin_and_base(root, str(policy["authority"]["project_identity"]))
    vendor_state = inspect_protected_vendor(protected_vendor, vendor_hold)
    checkout_map = provider_checkouts or {}
    verified_checkouts: Dict[str, Any] = {}
    for provider_id, checkout in sorted(checkout_map.items()):
        provider = providers.get(provider_id)
        if provider is None:
            raise PolicyError("unregistered_provider_checkout")
        verified_checkouts[provider_id] = _verify_provider_checkout(provider, Path(checkout))
    rows = []
    for source_id in sorted(source_rows):
        row = dict(source_rows[source_id])
        provider_id = row.get("provider_id")
        if provider_id in verified_checkouts:
            row["checkout"] = verified_checkouts[provider_id]
        rows.append(row)
    upstream_observation: Dict[str, Any] = {
        "status": "not_requested",
        "observations": [],
        "updates_available": [],
        "digest": digest([]),
    }
    if observe_remotes or observed_refs is not None:
        upstream_observation = observe_upstream_heads(providers, observed_refs=observed_refs)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "checkout": checkout_state,
        "protected_vendor": vendor_state,
        "sources": rows,
        "source_digest": digest(rows),
        "provider_lock_digest": digest(lock),
        "upstream_observation": upstream_observation,
        "plugin_commands_invoked": [],
        "candidate_writes": [],
    }


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


def _preflight(
    policy: Mapping[str, Any],
    sources: Mapping[str, Any],
    mode: str,
    stage_dir: Optional[Path],
    *,
    root: Path = ROOT,
    registry_path: Optional[Path] = None,
    lock_path: Optional[Path] = None,
    protected_vendor: Optional[Path] = None,
    vendor_hold: Optional[Mapping[str, Any]] = None,
    observe_remotes: bool = False,
    proposed_files: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    if mode not in policy.get("allowed_modes", []):
        raise PolicyError("mode_not_allowed")
    audit = audit_sources(
        Path(root),
        policy=policy,
        sources=sources,
        registry_path=registry_path,
        lock_path=lock_path,
        protected_vendor=protected_vendor,
        vendor_hold=vendor_hold,
        observe_remotes=observe_remotes,
    )
    candidate: Dict[str, Any] = {
        "status": "not_requested" if mode == "audit" or stage_dir is None else "not_started",
        "no_op": True,
        "changed_paths": [],
        "changed_paths_digest": digest([]),
    }
    if mode == "prepare" and stage_dir is not None:
        candidate = stage_candidate(
            Path(root),
            Path(stage_dir),
            base_sha=audit["checkout"]["base_sha"],
            allowlist=policy.get("diff_allowlist", []),
            proposed_files=proposed_files,
        )
    return {
        "policy_valid": True,
        "source_inventory_complete": True,
        "authority_recorded": True,
        "protected_surfaces_declared": True,
        "terminal_classification_declared": True,
        "disposable_stage_not_created": stage_dir is None or not stage_dir.exists(),
        "network_not_started": True,
        "github_not_contacted": True,
        "source_audit": audit,
        "source_audit_digest": digest(audit),
        "provider_refs_verified": True,
        "protected_vendor_status": audit["protected_vendor"],
        "caller_checkout": audit["checkout"],
        "candidate": candidate,
        "source_updates_available": audit["upstream_observation"]["updates_available"],
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
    root: Path = ROOT,
    registry_path: Optional[Path] = None,
    lock_path: Optional[Path] = None,
    protected_vendor: Optional[Path] = None,
    vendor_hold_path: Optional[Path] = None,
    observe_remotes: bool = False,
    proposed_files: Optional[Mapping[str, Any]] = None,
    github: Any = None,
    readiness_runner: Optional[Any] = None,
) -> Dict[str, Any]:
    """Run deterministic source audit/prepare and return the public receipt."""
    run_id_safe = _safe_id(run_id, "run")
    owner_safe = _safe_owner(owner_id or TASK_ID)
    observed_now = time.time() if now is None else float(now)
    state_root = Path(state_dir) if state_dir is not None else Path(os.environ.get("STACK_MAINTENANCE_STATE_DIR", str(Path.home() / ".local/state/stack/maintenance")))
    # State initialization intentionally precedes policy reads so an unsafe
    # state location cannot cause a partial receipt or a fallback write.
    initial_paths = initialize_state_dir(state_root)
    raw_policy_digest = _file_digest(Path(policy_path))
    raw_sources_digest = _file_digest(Path(sources_path))
    catalog_digest = _file_digest(Path(root) / "registry" / "capabilities.json")
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
    resolved_registry_path = Path(registry_path) if registry_path is not None else Path(root) / "registry" / "upstreams.json"
    resolved_lock_path = Path(lock_path) if lock_path is not None else Path(root) / "upstreams.lock.json"
    try:
        upstream_registry, upstream_lock = load_upstream_metadata(resolved_registry_path, resolved_lock_path)
        upstream_inputs: Mapping[str, Any] = {
            "registry": _without_volatile(upstream_registry),
            "lock": _without_volatile(upstream_lock),
        }
    except MaintenanceError:
        upstream_inputs = {
            "registry_digest": _file_digest(resolved_registry_path),
            "lock_digest": _file_digest(resolved_lock_path),
        }
    input_fp = input_fingerprint(policy, sources, extra={"upstream": upstream_inputs})
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
            vendor_hold: Optional[Mapping[str, Any]] = None
            if vendor_hold_path is not None:
                vendor_hold = _load_object(Path(vendor_hold_path), "vendor_hold")
            checks = _preflight(
                policy,
                sources,
                mode,
                stage_dir,
                root=Path(root),
                registry_path=registry_path,
                lock_path=lock_path,
                protected_vendor=protected_vendor,
                vendor_hold=vendor_hold,
                observe_remotes=observe_remotes,
                proposed_files=proposed_files,
            )
        except MaintenanceError as error:
            receipt = _base_receipt(run_id=run_id_safe, mode=mode, manual_audit=manual_audit, now=observed_now, input_fp=input_fp, provider_refs=refs, policy_digest=policy_digest, catalog_digest=catalog_digest)
            if error.code in {
                "protected_vendor_ambiguous",
                "protected_vendor_missing",
                "protected_vendor_unreadable",
                "origin_mismatch",
                "origin_main_missing",
                "origin_main_invalid",
                "caller_not_repository",
            }:
                receipt = _record_blocker(
                    paths,
                    policy=policy,
                    receipt=receipt,
                    code=error.code,
                    input_fp=input_fp,
                    run_id=run_id_safe,
                    now=observed_now,
                )
            else:
                receipt["terminal_classification"] = "failed"
                receipt["result"] = error.code
                receipt["reason_code"] = error.code
                receipt["checks"] = {"preflight_complete": False, "disposable_stage_not_created": True}
            return _safe_append(paths, receipt)
        receipt = _base_receipt(run_id=run_id_safe, mode=mode, manual_audit=manual_audit, now=observed_now, input_fp=input_fp, provider_refs=refs, policy_digest=policy_digest, catalog_digest=catalog_digest)
        candidate = checks.get("candidate", {}) if isinstance(checks, Mapping) else {}
        candidate_changed = candidate.get("status") == "changed"
        updates_available = bool(checks.get("source_updates_available"))
        receipt["terminal_classification"] = "prepared" if candidate_changed else ("awaiting_approval" if updates_available else "no_action")
        receipt["result"] = (
            "candidate_prepared"
            if candidate_changed
            else ("upstream_updates_detected" if updates_available else ("manual_audit_cleared" if manual_cleared else "preflight_only"))
        )
        receipt["checks"] = checks
        if isinstance(candidate.get("changed_paths_digest"), str) and DIGEST_PATTERN.fullmatch(candidate["changed_paths_digest"]):
            receipt["changed_paths_digest"] = candidate["changed_paths_digest"]
        if github is not None and mode == "prepare" and candidate_changed:
            lane = prepare_canonical_pr(
                Path(root),
                Path(stage_dir) if stage_dir is not None else None,
                base_sha=checks["source_audit"]["checkout"]["base_sha"],
                allowlist=policy.get("diff_allowlist", []),
                input_fingerprint_value=input_fp,
                policy=policy,
                github=github,
                readiness_runner=readiness_runner,
                expected_changed_paths_digest=candidate.get("changed_paths_digest"),
            )
            receipt["terminal_classification"] = lane["terminal_classification"]
            receipt["result"] = lane["result"]
            if lane.get("reason_code"):
                receipt["reason_code"] = lane["reason_code"]
            receipt["pr_state"] = lane["pr_state"]
            receipt["checks"]["pr_lane"] = lane["checks"]
            receipt["checks"]["candidate_stage_retained"] = lane.get("stage_retained", False)
            receipt["changed_paths_digest"] = lane["changed_paths_digest"]
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
    parser.add_argument("--root", type=Path, default=ROOT, help="caller repository root; never mutated")
    parser.add_argument("--upstreams", type=Path)
    parser.add_argument("--upstreams-lock", type=Path)
    parser.add_argument("--vendor-path", type=Path, help="optional protected vendor checkout to audit read-only")
    parser.add_argument("--vendor-hold", type=Path, help="owner-approved vendor hold evidence")
    parser.add_argument("--observe-upstreams", action="store_true", help="read public provider HEADs without trusting them")
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
            root=args.root,
            registry_path=args.upstreams,
            lock_path=args.upstreams_lock,
            protected_vendor=args.vendor_path,
            vendor_hold_path=args.vendor_hold,
            observe_remotes=args.observe_upstreams,
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
