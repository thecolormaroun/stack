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


def _git_status(root: Path) -> tuple[str, list[str]]:
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
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
            proposed_files=None,
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
