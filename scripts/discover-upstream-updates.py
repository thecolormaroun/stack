#!/usr/bin/env python3
"""Discover one immutable upstream update without materializing or publishing it.

Discovery is deliberately narrower than the Stack maintenance runner.  It
selects exactly one catalog provider, reuses ``observe_upstream_heads`` for an
explicit bounded live observation (or accepts a synthetic observation for
tests), and emits a provider-scoped packet.  The packet can be bound to the
existing maintenance receipt when ``--state-dir`` is supplied; no provider
registry, lock, runtime, branch, PR, or materializer state is changed here.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import parse_qsl, unquote_plus, urlparse


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "stack-maintenance.json"
SOURCES = ROOT / "registry" / "maintenance-sources.json"
UPSTREAMS = ROOT / "registry" / "upstreams.json"
LOCK = ROOT / "upstreams.lock.json"
SHA1 = re.compile(r"^[a-f0-9]{40}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
DIGEST = SHA256
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PROVIDER_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
RISK_CLASSES = {
    "none",
    "compatible",
    "major",
    "deprecation",
    "security",
    "license-or-terms",
    "cost-or-scope",
    "unknown",
}
UNSAFE_KEYS = {
    "multiple_candidates",
    "duplicate_pr",
    "duplicate_pr_lane",
    "unsafe_lineage",
    "dirty_vendor",
    "unexpected_paths",
    "deleted_paths",
    "deletions",
    "deleted_exports",
    "deleted",
    "unexpected",
    "dirty_protected_vendor",
}
ABSOLUTE_POSIX_PATH_FRAGMENT = re.compile(r"(?<![A-Za-z0-9_/])/[^\s\"'<>]*")
ABSOLUTE_WINDOWS_PATH_FRAGMENT = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\)[^\s\"'<>]+")
HTTPS_URL_FRAGMENT = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
MACHINE_LOCAL_POSIX_PATH = re.compile(
    r"(?<![A-Za-z0-9:/])/(?:Users|home|root|workspace|workspaces|tmp|private|var|opt|etc|usr|mnt|Volumes|app|srv|run|code|src)(?:/|$)",
    re.IGNORECASE,
)
MAX_EVIDENCE_NESTING = 64
MAX_PERCENT_DECODE_PASSES = 16


class DiscoveryError(ValueError):
    """A redacted, deterministic discovery failure."""

    def __init__(self, code: str, retry_class: str = "non_transient") -> None:
        super().__init__(code)
        self.code = code
        self.retry_class = retry_class


class DiscoveryPolicyError(DiscoveryError):
    pass


def _maintenance_module(root: Path):
    path = Path(root) / "scripts" / "stack-maintenance.py"
    spec = importlib.util.spec_from_file_location("stack_maintenance_discovery", path)
    if spec is None or spec.loader is None:
        raise DiscoveryError("maintenance_module_missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DiscoveryError(code) from error
    if not isinstance(value, dict):
        raise DiscoveryError(code)
    return value


def _json_safe(value: Any, maintenance: Any) -> Any:
    """Copy evidence while rejecting machine paths, secrets, and non-JSON data."""
    if _contains_machine_path(value):
        raise DiscoveryPolicyError("evidence_private_data")
    try:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise DiscoveryPolicyError("evidence_not_json") from error
    if len(encoded.encode("utf-8")) > 16384:
        raise DiscoveryPolicyError("evidence_too_large")
    if maintenance._private_data_in_bytes(encoded.encode("utf-8")):
        raise DiscoveryPolicyError("evidence_private_data")
    for item in _iter_evidence_strings(value):
        decoded = _repeatedly_unquote(item)
        if maintenance._private_data_in_bytes(decoded.encode("utf-8")):
            raise DiscoveryPolicyError("evidence_private_data")
    return json.loads(encoded)


def _contains_machine_path(value: Any) -> bool:
    """Reject absolute filesystem locations without mistaking web URLs for paths."""
    return any(_string_contains_machine_path(item) for item in _iter_evidence_strings(value))


def _iter_evidence_strings(value: Any) -> Iterable[str]:
    """Walk evidence without recursion and fail closed on pathological depth."""
    pending: list[tuple[Any, int]] = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > MAX_EVIDENCE_NESTING:
            raise DiscoveryPolicyError("evidence_too_deep")
        if isinstance(item, Mapping):
            for key, nested in item.items():
                pending.append((key, depth + 1))
                pending.append((nested, depth + 1))
            continue
        if isinstance(item, (list, tuple)):
            pending.extend((nested, depth + 1) for nested in item)
            continue
        if isinstance(item, str):
            yield item


def _string_contains_machine_path(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError as error:
        raise DiscoveryPolicyError("evidence_url_invalid") from error
    if parsed.scheme == "file" or Path(value).is_absolute():
        return True
    home = str(Path.home().resolve())
    scrubbed = value
    for match in HTTPS_URL_FRAGMENT.finditer(value):
        token = match.group(0).rstrip(".,;:!?)]}")
        try:
            url = urlparse(token)
            _ = url.port
        except ValueError as error:
            raise DiscoveryPolicyError("evidence_url_invalid") from error
        if url.scheme.lower() not in {"http", "https"} or not url.netloc:
            continue
        if url.username is not None or url.password is not None:
            return True
        decoded_path = _repeatedly_unquote(url.path)
        introduced_path_separator = (
            decoded_path.count("/") + decoded_path.count("\\")
            > url.path.count("/") + url.path.count("\\")
        )
        if introduced_path_separator and (
            "//" in decoded_path
            or "\\\\" in decoded_path
            or MACHINE_LOCAL_POSIX_PATH.search(decoded_path)
            or ABSOLUTE_WINDOWS_PATH_FRAGMENT.search(decoded_path)
        ):
            return True
        query_values = [item for pair in parse_qsl(url.query, keep_blank_values=True) for item in pair]
        query_values.append(url.fragment)
        for raw in query_values:
            decoded = _repeatedly_unquote(raw)
            if (
                (home != "/" and home in decoded)
                or MACHINE_LOCAL_POSIX_PATH.search(decoded)
                or ABSOLUTE_WINDOWS_PATH_FRAGMENT.search(decoded)
                or re.search(r"(?:^|[\s=])//", decoded)
                or decoded.lower().startswith("file:")
            ):
                return True
        scrubbed = scrubbed.replace(match.group(0), " ")
    scrubbed = _repeatedly_unquote(scrubbed)
    return bool(
        (home != "/" and home in scrubbed)
        or ABSOLUTE_POSIX_PATH_FRAGMENT.search(scrubbed)
        or ABSOLUTE_WINDOWS_PATH_FRAGMENT.search(scrubbed)
    )


def _repeatedly_unquote(value: str) -> str:
    decoded = value
    for pass_index in range(MAX_PERCENT_DECODE_PASSES + 1):
        expanded = unquote_plus(decoded)
        if expanded == decoded:
            return decoded
        if pass_index == MAX_PERCENT_DECODE_PASSES:
            break
        decoded = expanded
    raise DiscoveryPolicyError("evidence_encoding_depth")


def _pin_pattern(provider: Mapping[str, Any]) -> re.Pattern[str]:
    pin_type = provider.get("pin", {}).get("type") if isinstance(provider.get("pin"), Mapping) else None
    if pin_type == "git-commit":
        return SHA1
    if pin_type == "sha256":
        return SHA256
    raise DiscoveryPolicyError("mutable_upstream_pin")


def _validate_pin(provider: Mapping[str, Any], value: Any, code: str) -> str:
    if not isinstance(value, str) or _pin_pattern(provider).fullmatch(value) is None:
        raise DiscoveryPolicyError(code)
    return value


def _coerce_digest(value: Any, *, allow_none: bool = True) -> Optional[str]:
    if value is None and allow_none:
        return None
    if isinstance(value, str) and DIGEST.fullmatch(value):
        return value
    if value is None:
        raise DiscoveryPolicyError("digest_missing")
    # Synthetic observations may use stable labels instead of precomputed
    # SHA-256 values.  Hashing the label keeps the packet content-addressed and
    # makes the same fixture deterministic without weakening live evidence.
    return _digest(value)


def _first(mapping: Mapping[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def _provider_row(observation: Mapping[str, Any], provider_id: str) -> Mapping[str, Any]:
    """Find the selected provider's row in common synthetic/live shapes."""
    provider = observation.get("provider")
    if isinstance(provider, Mapping):
        row_id = provider.get("provider_id", provider.get("id"))
        if row_id is None or row_id == provider_id:
            return provider
    rows = observation.get("observations")
    if isinstance(rows, list):
        matches = [
            row for row in rows
            if isinstance(row, Mapping) and row.get("provider_id") == provider_id
        ]
        if len(matches) > 1:
            raise DiscoveryPolicyError("multiple_candidates")
        if matches:
            return matches[0]
    providers = observation.get("providers")
    if isinstance(providers, Mapping) and isinstance(providers.get(provider_id), Mapping):
        return providers[provider_id]
    return observation


def _candidate_rows(observation: Mapping[str, Any], provider_id: str) -> list[Mapping[str, Any]]:
    candidates = observation.get("candidates")
    if isinstance(candidates, list):
        if not all(isinstance(row, Mapping) for row in candidates):
            raise DiscoveryPolicyError("candidate_invalid")
        declared_ids = {
            row.get("provider_id", row.get("id"))
            for row in candidates
            if isinstance(row, Mapping)
        }
        foreign_ids = {value for value in declared_ids if value is not None and value != provider_id}
        if foreign_ids:
            raise DiscoveryPolicyError("provider_scope_invalid")
        rows = [
            row for row in candidates
            if isinstance(row, Mapping)
            and row.get("provider_id", row.get("id", provider_id)) == provider_id
        ]
        return rows
    row = _provider_row(observation, provider_id)
    if isinstance(row, Mapping):
        return [row]
    return []


def _candidate_pin(
    provider: Mapping[str, Any],
    provider_id: str,
    observation: Mapping[str, Any],
    explicit_pin: Optional[str],
) -> tuple[str, Mapping[str, Any], str]:
    rows = _candidate_rows(observation, provider_id)
    if len(rows) > 1:
        raise DiscoveryPolicyError("multiple_candidates")
    row = rows[0] if rows else observation
    values: list[str] = []
    if explicit_pin is not None:
        values.append(explicit_pin)
    for source in (row, observation):
        if not isinstance(source, Mapping):
            continue
        if "candidate" in source and source.get("candidate") is not None and not isinstance(source.get("candidate"), Mapping):
            raise DiscoveryPolicyError("candidate_invalid")
        for key in ("candidate_pin", "candidate_immutable_pin", "new_pin", "observed_head", "observed_pin"):
            value = source.get(key)
            if isinstance(value, str):
                values.append(value)
        nested = source.get("candidate")
        if isinstance(nested, Mapping):
            for key in ("pin", "value", "candidate_pin", "new_pin"):
                value = nested.get(key)
                if isinstance(value, str):
                    values.append(value)
        refs = source.get("observed_refs")
        if isinstance(refs, Mapping) and isinstance(refs.get(provider_id), str):
            values.append(str(refs[provider_id]))
    # Preserve order for deterministic errors, then collapse equivalent
    # aliases.  A source observation row may expose both pin and observed_head;
    # only the immutable candidate aliases above are considered.
    unique = list(dict.fromkeys(values))
    if len(unique) > 1:
        raise DiscoveryPolicyError("multiple_candidates")
    if not unique:
        current = str(provider.get("pin", {}).get("value", ""))
        return current, row, "synthetic"
    candidate = _validate_pin(provider, unique[0], "candidate_pin_invalid")
    method = "live" if observation.get("observation_method") == "live" or observation.get("live") is True else "synthetic"
    return candidate, row, method


def _nested_candidate(observation: Mapping[str, Any], row: Mapping[str, Any]) -> Mapping[str, Any]:
    candidate = row.get("candidate")
    if isinstance(candidate, Mapping):
        return candidate
    candidate = observation.get("candidate")
    if isinstance(candidate, Mapping):
        return candidate
    return row


def _extract_digest(
    observation: Mapping[str, Any],
    row: Mapping[str, Any],
    candidate: Mapping[str, Any],
    field: str,
    side: str,
) -> Optional[str]:
    aliases = {
        "source_tree_digest": ("source_tree_digest", "source_tree", "tree_digest"),
        "generated_manifest_digest": ("generated_manifest_digest", "generated_manifest", "manifest_digest"),
        "output_semantic_digest": ("output_semantic_digest", "output_digest", "runtime_output_digest"),
    }[field]
    sources: list[Mapping[str, Any]] = [candidate, row, observation]
    for container_key in ("digests", "digest_evidence", "current_digests", "candidate_digests"):
        container = observation.get(container_key)
        if isinstance(container, Mapping):
            sources.append(container)
    if side == "current":
        nested_names = ("current", "old", "baseline", "active")
        prefix = ("current_", "old_", "baseline_")
    else:
        nested_names = ("candidate", "new", "proposed")
        prefix = ("candidate_", "new_", "proposed_")
    for source in sources:
        if side == "current":
            for section_name in nested_names:
                section = source.get(section_name)
                if not isinstance(section, Mapping):
                    continue
                for alias in aliases:
                    value = section.get(alias)
                    if isinstance(value, Mapping):
                        value = _first(value, nested_names)
                    if value is not None:
                        return _coerce_digest(value)
        for alias in aliases:
            value = source.get(alias)
            if isinstance(value, Mapping):
                value = _first(value, nested_names)
            if value is not None and side == "current":
                # A bare digest field on the provider row describes the
                # candidate only when the row itself is a candidate record.
                # The current side is taken from explicit nested evidence.
                continue
            if value is not None and side == "candidate":
                return _coerce_digest(value)
        for alias in aliases:
            for prefix_value in prefix:
                value = source.get(prefix_value + alias.removesuffix("_digest"))
                if value is None:
                    value = source.get(prefix_value + alias)
                if value is not None:
                    return _coerce_digest(value)
    if side == "current":
        for source in sources:
            for alias in aliases:
                value = source.get(alias)
                if isinstance(value, Mapping):
                    nested = _first(value, nested_names)
                    if nested is not None:
                        return _coerce_digest(nested)
    return None


def _extract_changed_exports(observation: Mapping[str, Any], row: Mapping[str, Any], candidate: Mapping[str, Any], provider: Mapping[str, Any]) -> list[str]:
    value = _first(candidate, ("changed_exports",))
    if value is None:
        value = _first(row, ("changed_exports",))
    if value is None:
        value = _first(observation, ("changed_exports",))
    if value is not None:
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise DiscoveryPolicyError("changed_exports_invalid")
        return sorted(set(value))
    exports = _first(candidate, ("exports", "candidate_exports", "new_exports"))
    if exports is None:
        return []
    if not isinstance(exports, list) or not all(isinstance(item, str) and item for item in exports):
        raise DiscoveryPolicyError("changed_exports_invalid")
    return sorted(set(str(item) for item in provider.get("exports", [])) ^ set(exports))


def _source_rows(sources: Mapping[str, Any], provider_id: str) -> list[Mapping[str, Any]]:
    return [
        row for row in sources.get("sources", [])
        if isinstance(row, Mapping) and row.get("provider_id") == provider_id
    ]


def _semantic_file_digest(path: Path, maintenance: Any) -> str:
    if path.is_symlink() or not path.is_file():
        return _digest("missing:" + path.as_posix())
    try:
        return maintenance.semantic_bytes_digest(path.read_bytes(), path)
    except OSError as error:
        raise DiscoveryError("evidence_read_failed", "transient") from error


def _semantic_tree(root: Path, relative: str, maintenance: Any) -> dict[str, str]:
    target = root / relative
    if target.is_symlink():
        raise DiscoveryPolicyError("unexpected_symlink")
    if not target.exists():
        return {relative: _digest("missing:" + relative)}
    if target.is_file():
        return {relative: _semantic_file_digest(target, maintenance)}
    rows: dict[str, str] = {}
    for path in sorted(target.rglob("*")):
        if path.is_symlink():
            raise DiscoveryPolicyError("unexpected_symlink")
        if path.is_file():
            child = path.relative_to(root).as_posix()
            rows[child] = _semantic_file_digest(path, maintenance)
    return rows


def _current_evidence(
    root: Path,
    provider: Mapping[str, Any],
    source_rows: list[Mapping[str, Any]],
    maintenance: Any,
) -> dict[str, str]:
    provider_id = str(provider["id"])
    target_rows: dict[str, str] = {}
    for source in source_rows:
        for relative in source.get("target_paths", []):
            target_rows.update(_semantic_tree(root, str(relative), maintenance))
    output_digest = _digest({"provider_id": provider_id, "targets": target_rows})

    package_rows: dict[str, Any] = {}
    for relative in (
        f"packages/{provider_id}/package.json",
        "packages/imported-skills/package.json",
        "registry/capabilities.json",
    ):
        path = root / relative
        if path.is_file() and not path.is_symlink():
            if relative.endswith("capabilities.json"):
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as error:
                    raise DiscoveryError("evidence_read_failed", "transient") from error
                capabilities = [
                    row for row in value.get("capabilities", [])
                    if isinstance(row, Mapping)
                    and row.get("ownership", {}).get("provider") == provider_id
                ] if isinstance(value, Mapping) else []
                package_rows[relative] = capabilities
            else:
                package_rows[relative] = _semantic_file_digest(path, maintenance)
    manifest_digest = _digest({"provider_id": provider_id, "manifests": package_rows})
    source_tree_digest = _digest(
        {
            "provider_id": provider_id,
            "canonical_source": provider.get("canonical_source"),
            "pin": provider.get("pin"),
            "exports": sorted(provider.get("exports", [])),
            "export_paths": provider.get("export_paths", {}),
            "targets": target_rows,
        }
    )
    return {
        "source_tree_digest": source_tree_digest,
        "generated_manifest_digest": manifest_digest,
        "output_semantic_digest": output_digest,
    }


def _affected_runtimes(root: Path, provider: Mapping[str, Any]) -> list[str]:
    provider_id = str(provider["id"])
    path = root / "registry" / "capabilities.json"
    runtimes: set[str] = set()
    if path.is_file():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            value = {}
        for row in value.get("capabilities", []) if isinstance(value, Mapping) else []:
            if not isinstance(row, Mapping) or row.get("ownership", {}).get("provider") != provider_id:
                continue
            runtime_data = row.get("runtimes", {})
            targets = runtime_data.get("publish_targets", []) if isinstance(runtime_data, Mapping) else []
            runtimes.update(str(item) for item in targets if isinstance(item, str) and item)
    if not runtimes:
        # External packages are published through both supported runtime
        # targets even when their catalog entries are represented by package
        # manifests rather than capability rows.  Keep logical adapters in a
        # separate packet field below.
        runtimes.update({"claude", "codex"})
    return sorted(runtimes)


def _explicit_risk(observation: Mapping[str, Any], row: Mapping[str, Any], candidate: Mapping[str, Any]) -> Optional[str]:
    value = _first(candidate, ("version_risk_class", "risk_class", "version_risk"))
    if value is None:
        value = _first(row, ("version_risk_class", "risk_class", "version_risk"))
    if value is None:
        value = _first(observation, ("version_risk_class", "risk_class", "version_risk"))
    if value is None:
        return None
    if not isinstance(value, str) or value not in RISK_CLASSES:
        raise DiscoveryPolicyError("version_risk_class_invalid")
    return value


def _risk_class(observation: Mapping[str, Any], row: Mapping[str, Any], candidate: Mapping[str, Any], changed_exports: list[str], old_pin: str, new_pin: str) -> str:
    explicit = _explicit_risk(observation, row, candidate)
    if explicit is not None:
        return explicit
    flags: list[tuple[str, tuple[str, ...]]] = [
        ("major", ("major", "major_change", "breaking_change")),
        ("deprecation", ("deprecated", "deprecation", "deprecation_change")),
        ("security", ("security", "security_change", "security_fix")),
        ("license-or-terms", ("license_change", "terms_change", "license_or_terms")),
        ("cost-or-scope", ("cost_change", "scope_change", "required_scope", "network_required")),
    ]
    for risk, names in flags:
        for source in (candidate, row, observation):
            if any(source.get(name) is True for name in names):
                return risk
    if old_pin == new_pin:
        return "none"
    return "compatible" if not changed_exports else "unknown"


def _compatibility_evidence(
    observation: Mapping[str, Any],
    row: Mapping[str, Any],
    candidate: Mapping[str, Any],
    provider: Mapping[str, Any],
    old_pin: str,
    new_pin: str,
    current_digests: Mapping[str, Optional[str]],
    candidate_digests: Mapping[str, Optional[str]],
) -> dict[str, Any]:
    explicit = _first(candidate, ("compatibility_evidence", "compatibility"))
    if explicit is None:
        explicit = _first(row, ("compatibility_evidence", "compatibility"))
    if explicit is None:
        explicit = _first(observation, ("compatibility_evidence", "compatibility"))
    if explicit is not None and not isinstance(explicit, Mapping):
        raise DiscoveryPolicyError("compatibility_evidence_invalid")
    evidence = copy.deepcopy(dict(explicit)) if isinstance(explicit, Mapping) else {}
    if isinstance(evidence.get("status"), bool):
        evidence["status"] = "verified" if evidence["status"] else "failed"
    evidence.setdefault("status", "verified" if old_pin == new_pin and all(
        current_digests.get(field) == candidate_digests.get(field)
        for field in ("source_tree_digest", "generated_manifest_digest", "output_semantic_digest")
    ) else "pending")
    evidence.setdefault("required_checks", list(provider.get("compatibility", [])))
    evidence["baseline"] = {
        "pin": old_pin,
        **{field: current_digests.get(field) for field in current_digests},
    }
    evidence["candidate"] = {
        "pin": new_pin,
        **{field: candidate_digests.get(field) for field in candidate_digests},
    }
    return evidence


def _unsafe_reasons(observation: Mapping[str, Any], row: Mapping[str, Any], candidate: Mapping[str, Any], provider: Mapping[str, Any], old_pin: str, new_pin: str) -> list[str]:
    reasons: set[str] = set()
    sources = (candidate, row, observation)
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in UNSAFE_KEYS:
            value = source.get(key)
            if value is True or (isinstance(value, (list, tuple, set, Mapping)) and len(value) > 0):
                reasons.add({
                    "multiple_candidates": "multiple_candidates",
                    "duplicate_pr": "duplicate_pr_lane",
                    "duplicate_pr_lane": "duplicate_pr_lane",
                    "unsafe_lineage": "unsafe_lineage",
                    "dirty_vendor": "dirty_protected_vendor",
                    "unexpected_paths": "unexpected_path",
                    "deleted_paths": "deletion_requires_review",
                    "deletions": "deletion_requires_review",
                    "deleted_exports": "deletion_requires_review",
                    "deleted": "deletion_requires_review",
                    "unexpected": "unexpected_path",
                    "dirty_protected_vendor": "dirty_protected_vendor",
                }[key])
        for key in ("canonical_source", "provider_ref", "source"):
            value = source.get(key)
            if value is not None and value != provider.get("canonical_source"):
                # Allow a provider_ref shorthand that normalizes to the same
                # public origin, but reject a different source altogether.
                try:
                    if _maintenance_module(ROOT)._origin_identity(str(value)) != _maintenance_module(ROOT)._origin_identity(str(provider.get("canonical_source"))):
                        reasons.add("provider_origin_mismatch")
                except DiscoveryError:
                    reasons.add("provider_origin_mismatch")
        for key in ("parent_pin", "base_pin", "expected_parent"):
            value = source.get(key)
            if value is not None and value != old_pin:
                reasons.add("unsafe_lineage")
        for key in ("lineage", "lineage_status", "ancestry", "ancestry_status"):
            value = source.get(key)
            if value is False or (
                isinstance(value, str)
                and value in {"unsafe", "ambiguous", "unknown", "unverified", "non_linear"}
            ):
                reasons.add("unsafe_lineage")
        if source.get("lineage_safe") is False:
            reasons.add("unsafe_lineage")
        for key in ("vendor_status", "vendor_state"):
            value = source.get(key)
            if isinstance(value, str) and value in {"dirty", "ambiguous", "unverified"}:
                reasons.add("dirty_protected_vendor")
        vendor = source.get("protected_vendor")
        if isinstance(vendor, Mapping):
            if vendor.get("status") in {"dirty", "ambiguous", "unverified"} and vendor.get("hold_verified") is not True:
                reasons.add("dirty_protected_vendor")
        elif vendor is True:
            reasons.add("dirty_protected_vendor")
        for key in ("open_prs", "candidate_prs", "canonical_prs", "existing_prs", "duplicate_candidates"):
            value = source.get(key)
            if value is True or (isinstance(value, list) and len(value) > 1):
                reasons.add("duplicate_pr_lane")
    candidate_exports = _first(candidate, ("exports", "candidate_exports", "new_exports"))
    if isinstance(candidate_exports, list) and set(provider.get("exports", [])) - set(candidate_exports):
        reasons.add("deletion_requires_review")
    return sorted(reasons)


def _normalise_observation(
    observation: Optional[Mapping[str, Any]],
    *,
    provider_id: str,
    candidate_pin: Optional[str],
    live: bool,
    maintenance: Any,
    providers: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, str]]:
    value = dict(observation or {})
    if live:
        if observation is not None or candidate_pin is not None:
            raise DiscoveryPolicyError("live_and_synthetic_observation_conflict")
        # The live lane is intentionally provider-scoped.  The existing
        # observer remains the only network implementation, but it receives a
        # one-provider map so a discovery request cannot fan out across the
        # catalog or accidentally become a weekly full audit.
        selected = {provider_id: providers[provider_id]}
        observed = maintenance.observe_upstream_heads(selected)
        rows = [row for row in observed.get("observations", []) if row.get("provider_id") == provider_id]
        if len(rows) != 1:
            raise DiscoveryError("live_observation_invalid", "transient")
        value = {
            "observation_method": "live",
            "live": True,
            "observations": rows,
            "provider": rows[0],
        }
        return value, {
            str(row["provider_id"]): str(row["observed_head"])
            for row in observed.get("observations", [])
            if isinstance(row, Mapping) and isinstance(row.get("observed_head"), str)
        }
    if candidate_pin is not None:
        value["candidate_pin"] = candidate_pin
    if not value and candidate_pin is None:
        raise DiscoveryPolicyError("observation_required")
    refs = value.get("observed_refs")
    observed_refs = {
        str(key): str(pin)
        for key, pin in refs.items()
        if isinstance(key, str) and isinstance(pin, str)
    } if isinstance(refs, Mapping) else {}
    return value, observed_refs


def build_discovery_packet(
    provider: Mapping[str, Any],
    observation: Mapping[str, Any],
    *,
    current_evidence: Optional[Mapping[str, Any]] = None,
    source_rows: Optional[list[Mapping[str, Any]]] = None,
    affected_runtimes: Optional[list[str]] = None,
    approval_owner: str = "stack-maintainer",
    maintenance: Any = None,
) -> dict[str, Any]:
    """Build one provider-scoped packet from immutable metadata and evidence."""
    if maintenance is None:
        maintenance = _maintenance_module(ROOT)
    provider_id = provider.get("id")
    if not isinstance(provider_id, str) or not PROVIDER_ID.fullmatch(provider_id):
        raise DiscoveryPolicyError("provider_id_invalid")
    provider_ref = provider.get("canonical_source")
    if not isinstance(provider_ref, str) or not provider_ref.startswith("https://"):
        raise DiscoveryPolicyError("provider_origin_invalid")
    old_pin = _validate_pin(provider, provider.get("pin", {}).get("value"), "current_pin_invalid")
    candidate_pin_value, row, method = _candidate_pin(provider, provider_id, observation, None)
    candidate = _nested_candidate(observation, row)
    new_pin = _validate_pin(provider, candidate_pin_value, "candidate_pin_invalid")
    current = dict(current_evidence or {})
    current.setdefault("source_tree_digest", _digest({"provider": provider_id, "pin": old_pin, "kind": "source-tree"}))
    current.setdefault("generated_manifest_digest", _digest({"provider": provider_id, "pin": old_pin, "kind": "generated-manifest"}))
    current.setdefault("output_semantic_digest", _digest({"provider": provider_id, "pin": old_pin, "kind": "output"}))
    for field in ("source_tree_digest", "generated_manifest_digest", "output_semantic_digest"):
        observed_current = _extract_digest(observation, row, candidate, field, "current")
        if observed_current is not None:
            current[field] = observed_current
    current_digests = {
        field: _coerce_digest(current.get(field), allow_none=False)
        for field in ("source_tree_digest", "generated_manifest_digest", "output_semantic_digest")
    }
    candidate_digests: dict[str, Optional[str]] = {}
    for field in ("source_tree_digest", "generated_manifest_digest", "output_semantic_digest"):
        candidate_digests[field] = _extract_digest(observation, row, candidate, field, "candidate")
    if new_pin == old_pin:
        for field in candidate_digests:
            if candidate_digests[field] is None:
                candidate_digests[field] = current_digests[field]
    changed_exports = _extract_changed_exports(observation, row, candidate, provider)
    risk = _risk_class(observation, row, candidate, changed_exports, old_pin, new_pin)
    unsafe = _unsafe_reasons(observation, row, candidate, provider, old_pin, new_pin)
    if risk not in RISK_CLASSES:
        unsafe.append("version_risk_class_invalid")
    if new_pin == old_pin and any(
        candidate_digests[field] != current_digests[field]
        for field in current_digests
    ):
        unsafe.append("same_pin_digest_mismatch")
    if not isinstance(approval_owner, str) or not approval_owner.strip() or SAFE_ID.fullmatch(approval_owner) is None:
        raise DiscoveryPolicyError("approval_owner_invalid")
    explicit_owner = _first(candidate, ("approval_owner",))
    if explicit_owner is None:
        explicit_owner = _first(row, ("approval_owner",))
    if explicit_owner is None:
        explicit_owner = _first(observation, ("approval_owner",))
    if explicit_owner is not None:
        if not isinstance(explicit_owner, str) or SAFE_ID.fullmatch(explicit_owner) is None:
            raise DiscoveryPolicyError("approval_owner_invalid")
        approval_owner = explicit_owner
    compatibility = _compatibility_evidence(
        observation,
        row,
        candidate,
        provider,
        old_pin,
        new_pin,
        current_digests,
        candidate_digests,
    )
    candidate_evidence_pending = new_pin != old_pin and any(
        value is None for value in candidate_digests.values()
    )
    if candidate_evidence_pending:
        # A remote HEAD is a useful discovery signal, not compatibility proof.
        # Keep the packet reviewable, but make the missing evidence explicit and
        # never describe the update as fully compatible.
        if risk == "compatible":
            risk = "unknown"
        if compatibility.get("status") == "verified":
            compatibility["status"] = "pending"
        compatibility["evidence_required"] = [
            field for field, value in candidate_digests.items() if value is None
        ] + (["compatibility_checks"] if not compatibility.get("checks") else [])
    if compatibility.get("status") == "failed":
        unsafe.append("compatibility_failed")
    release = _first(candidate, ("release_evidence", "release"))
    if release is None:
        release = _first(row, ("release_evidence", "release"))
    if release is None:
        release = _first(observation, ("release_evidence", "release"))
    deprecation = _first(candidate, ("deprecation_evidence", "deprecation"))
    if deprecation is None:
        deprecation = _first(row, ("deprecation_evidence", "deprecation"))
    if deprecation is None:
        deprecation = _first(observation, ("deprecation_evidence", "deprecation"))
    if release is not None and not isinstance(release, Mapping):
        raise DiscoveryPolicyError("release_evidence_invalid")
    if deprecation is not None and not isinstance(deprecation, Mapping):
        raise DiscoveryPolicyError("deprecation_evidence_invalid")
    release = _json_safe(dict(release) if isinstance(release, Mapping) else {}, maintenance)
    deprecation = _json_safe(dict(deprecation) if isinstance(deprecation, Mapping) else {}, maintenance)
    source_rows = source_rows or []
    explicit_runtimes = _first(candidate, ("affected_runtimes", "runtimes"))
    if explicit_runtimes is None:
        explicit_runtimes = _first(row, ("affected_runtimes", "runtimes"))
    if explicit_runtimes is None:
        explicit_runtimes = _first(observation, ("affected_runtimes", "runtimes"))
    if explicit_runtimes is not None:
        if not isinstance(explicit_runtimes, list) or not all(isinstance(item, str) and item for item in explicit_runtimes):
            raise DiscoveryPolicyError("affected_runtimes_invalid")
        runtimes = list(explicit_runtimes)
    else:
        runtimes = affected_runtimes or []
    if not runtimes:
        runtimes = ["claude", "codex"]
    runtimes = sorted(set(runtimes))
    lkg = provider.get("last_known_good")
    if not isinstance(lkg, Mapping) or lkg.get("pin") != old_pin:
        unsafe.append("last_known_good_mismatch")
        lkg = {"pin": old_pin, "metadata_digest": current_digests["output_semantic_digest"]}
    lkg = _json_safe(dict(lkg), maintenance)
    rollback = {
        "provider_id": provider_id,
        "pin": old_pin,
        "source": "registry/upstreams.json",
        "last_known_good": lkg,
        "runtime_output_digest": current_digests["output_semantic_digest"],
    }
    if unsafe:
        status = "blocked"
        reason = sorted(set(unsafe))[0]
    elif new_pin == old_pin and not changed_exports and all(
        candidate_digests[field] == current_digests[field]
        for field in current_digests
    ):
        status = "no_action"
        reason = "unchanged_provider"
        risk = "none"
    else:
        status = "prepared"
        reason = "candidate_evidence_pending" if candidate_evidence_pending else "upstream_update_detected"
    pair = {
        field: {
            "current": current_digests[field],
            "candidate": candidate_digests[field],
            "identical": candidate_digests[field] == current_digests[field]
            if candidate_digests[field] is not None
            else False,
        }
        for field in current_digests
    }
    packet = {
        "schema_version": 1,
        "provider_id": provider_id,
        "provider_ref": provider_ref,
        "status": status,
        "terminal_classification": status,
        "reason_code": reason,
        "result": reason,
        "old_pin": old_pin,
        "new_pin": new_pin,
        "current_pin": old_pin,
        "candidate_pin": new_pin,
        "old_pin_digest": _digest(old_pin),
        "new_pin_digest": _digest(new_pin),
        "source_tree_digest": pair["source_tree_digest"],
        "generated_manifest_digest": pair["generated_manifest_digest"],
        "output_semantic_digest": pair["output_semantic_digest"],
        "changed_exports": changed_exports,
        "affected_runtimes": runtimes,
        "affected_adapters": sorted(set(str(item) for item in provider.get("adapters", []) if isinstance(item, str))),
        "release_evidence": release,
        "deprecation_evidence": deprecation,
        "version_risk_class": risk,
        "risk_class": risk,
        "compatibility_evidence": _json_safe(compatibility, maintenance),
        "approval_owner": approval_owner,
        "approval_required": status == "prepared" or risk in RISK_CLASSES - {"none", "compatible"},
        "last_known_good": lkg,
        "rollback_pointer": rollback,
        "source_observation": {
            "method": method,
            "canonical_source": provider_ref,
            "observed_pin": new_pin,
            "digest": _digest({"provider_id": provider_id, "pin": new_pin, "method": method}),
        },
        "checks": {
            "one_provider_scope": True,
            "one_candidate": True,
            "candidate_pin_immutable": True,
            "current_pin_immutable": True,
            "canonical_source_verified": True,
            "last_known_good_verified": not any(reason == "last_known_good_mismatch" for reason in unsafe),
            "source_tree_digest_identical": pair["source_tree_digest"]["identical"],
            "generated_manifest_digest_identical": pair["generated_manifest_digest"]["identical"],
            "output_semantic_digest_identical": pair["output_semantic_digest"]["identical"],
            "candidate_evidence_pending": any(value is None for value in candidate_digests.values()),
            "candidate_evidence_complete": not candidate_evidence_pending and compatibility.get("status") in {"verified", "passed", "compatible"},
            "materializer_invoked": False,
            "publication_attempted": False,
            "active_pin_changed": False,
            "runtime_outputs_changed": False,
            "branches_changed": False,
            "pull_requests_changed": False,
            "external_state_changed": False,
        },
        "unsafe_reasons": sorted(set(unsafe)),
    }
    return packet


def discover_upstream_update(
    provider_id: str,
    observation: Optional[Mapping[str, Any]] = None,
    *,
    synthetic_observation: Optional[Mapping[str, Any]] = None,
    root: Path = ROOT,
    candidate_pin: Optional[str] = None,
    candidate_immutable_pin: Optional[str] = None,
    live: bool = False,
    policy_path: Path = POLICY,
    sources_path: Path = SOURCES,
    registry_path: Path = UPSTREAMS,
    lock_path: Path = LOCK,
    approval_owner: Optional[str] = None,
    state_dir: Optional[Path] = None,
    run_id: Optional[str] = None,
    owner_id: Optional[str] = None,
    now: Optional[float] = None,
) -> dict[str, Any]:
    """Discover one provider and optionally bind the packet to a receipt."""
    if not isinstance(provider_id, str) or not PROVIDER_ID.fullmatch(provider_id):
        raise DiscoveryPolicyError("provider_id_invalid")
    if observation is not None and synthetic_observation is not None:
        raise DiscoveryPolicyError("multiple_observation_inputs")
    if synthetic_observation is not None:
        observation = synthetic_observation
    if candidate_pin is not None and candidate_immutable_pin is not None and candidate_pin != candidate_immutable_pin:
        raise DiscoveryPolicyError("multiple_candidates")
    if candidate_pin is None:
        candidate_pin = candidate_immutable_pin
    root = Path(root).resolve()
    if Path(policy_path) == POLICY and (root / "config" / "stack-maintenance.json").is_file():
        policy_path = root / "config" / "stack-maintenance.json"
    if Path(sources_path) == SOURCES and (root / "registry" / "maintenance-sources.json").is_file():
        sources_path = root / "registry" / "maintenance-sources.json"
    if Path(registry_path) == UPSTREAMS and (root / "registry" / "upstreams.json").is_file():
        registry_path = root / "registry" / "upstreams.json"
    if Path(lock_path) == LOCK and (root / "upstreams.lock.json").is_file():
        lock_path = root / "upstreams.lock.json"
    maintenance = _maintenance_module(root)
    policy = maintenance.load_policy(Path(policy_path))
    sources = maintenance.load_sources(Path(sources_path))
    maintenance.validate_policy(policy, sources)
    registry, lock = maintenance.load_upstream_metadata(Path(registry_path), Path(lock_path))
    providers = maintenance.validate_upstream_metadata(registry, lock)
    provider = providers.get(provider_id)
    if provider is None:
        raise DiscoveryPolicyError("provider_not_registered")
    source_rows = _source_rows(sources, provider_id)
    if not source_rows:
        raise DiscoveryPolicyError("provider_not_in_maintenance_inventory")
    if any(row.get("disposition") != "catalog-managed-provider" for row in source_rows):
        raise DiscoveryPolicyError("provider_not_catalog_managed")
    current = _current_evidence(root, provider, source_rows, maintenance)
    runtimes = _affected_runtimes(root, provider)
    owner = str(approval_owner or policy.get("discovery", {}).get("approval_owner", "stack-maintainer"))
    try:
        normalised, supplied_refs = _normalise_observation(
            observation,
            provider_id=provider_id,
            candidate_pin=candidate_pin,
            live=live,
            maintenance=maintenance,
            providers=providers,
        )
        packet = build_discovery_packet(
            provider,
            normalised,
            current_evidence=current,
            source_rows=source_rows,
            affected_runtimes=runtimes,
            approval_owner=owner,
            maintenance=maintenance,
        )
    except (DiscoveryError, maintenance.MaintenanceError) as error:
        # Unsafe observation shapes become an explicit provider-scoped block,
        # never an exception that tempts a caller to guess a candidate.  The
        # offending evidence is not copied into the packet, which keeps the
        # receipt redacted even for private or oversized release notes.
        packet = build_discovery_packet(
            provider,
            {"candidate_pin": str(provider["pin"]["value"])},
            current_evidence=current,
            source_rows=source_rows,
            affected_runtimes=runtimes,
            approval_owner=owner,
            maintenance=maintenance,
        )
        retry_class = getattr(error, "retry_class", "non_transient")
        packet["status"] = "failed" if retry_class == "transient" else "blocked"
        packet["reason_code"] = getattr(error, "code", "discovery_failed")
        packet["terminal_classification"] = packet["status"]
        packet["result"] = packet["reason_code"]
        packet["unsafe_reasons"] = sorted(set(packet.get("unsafe_reasons", [])) | {packet["reason_code"]})
        packet["checks"]["observation_rejected"] = True
        packet["checks"]["materializer_invoked"] = False
        supplied_refs = {}
    receipt: Optional[dict[str, Any]] = None
    if state_dir is not None:
        # Fill the existing observer contract for every Git provider while
        # replacing only the selected provider's observed immutable head.  No
        # second lease, circuit, receipt store, or PR lane is introduced.
        refs = {
            provider_key: str(row.get("pin", {}).get("value"))
            for provider_key, row in providers.items()
            if row.get("pin", {}).get("type") == "git-commit"
        }
        refs.update(supplied_refs)
        if packet["new_pin"] and provider.get("pin", {}).get("type") == "git-commit":
            refs[provider_id] = packet["new_pin"]
        receipt = maintenance.run(
            mode="audit",
            state_dir=Path(state_dir),
            policy_path=Path(policy_path),
            sources_path=Path(sources_path),
            run_id=run_id,
            owner_id=owner_id,
            now=now,
            root=root,
            registry_path=Path(registry_path),
            lock_path=Path(lock_path),
            observed_refs=refs or None,
            discovery_packet=packet,
        )
    result = dict(packet)
    result["receipt"] = {
        "persisted": receipt is not None,
        "run_id": receipt.get("run_id") if receipt else None,
        "terminal_classification": receipt.get("terminal_classification") if receipt else None,
        "result": receipt.get("result") if receipt else None,
    }
    return result


# Friendly aliases for embedded callers and tests.
build_packet = build_discovery_packet
discover = discover_upstream_update
discover_update = discover_upstream_update
discover_provider_update = discover_upstream_update
discover_upstream_updates = discover_upstream_update
run_discovery = discover_upstream_update


def _parse_observation(args: argparse.Namespace) -> Optional[dict[str, Any]]:
    if args.observation and args.observation_json:
        raise DiscoveryPolicyError("multiple_observation_inputs")
    if args.observation:
        return _read_json(args.observation, "observation_unreadable")
    if args.observation_json:
        try:
            value = json.loads(args.observation_json)
        except json.JSONDecodeError as error:
            raise DiscoveryPolicyError("observation_invalid") from error
        if not isinstance(value, dict):
            raise DiscoveryPolicyError("observation_invalid")
        return value
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider_positional", nargs="?")
    parser.add_argument("--provider", "--provider-id", dest="provider_id")
    parser.add_argument("--candidate-pin", "--observed-pin", dest="candidate_pin")
    parser.add_argument("--observation", type=Path)
    parser.add_argument("--observation-json", "--synthetic-observation", dest="observation_json")
    parser.add_argument("--live", "--observe-upstreams", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--policy", type=Path, default=POLICY)
    parser.add_argument("--sources", type=Path, default=SOURCES)
    parser.add_argument("--upstreams", type=Path, default=UPSTREAMS)
    parser.add_argument("--upstreams-lock", type=Path, default=LOCK)
    parser.add_argument("--approval-owner")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--owner-id")
    parser.add_argument("--now", type=float)
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        observation = _parse_observation(args)
        provider_id = args.provider_id or args.provider_positional
        if not provider_id:
            raise DiscoveryPolicyError("provider_id_required")
        result = discover_upstream_update(
            provider_id,
            observation,
            root=args.root,
            candidate_pin=args.candidate_pin,
            live=args.live,
            policy_path=args.policy,
            sources_path=args.sources,
            registry_path=args.upstreams,
            lock_path=args.upstreams_lock,
            approval_owner=args.approval_owner,
            state_dir=args.state_dir,
            run_id=args.run_id,
            owner_id=args.owner_id,
            now=args.now,
        )
    except (DiscoveryError, OSError, UnicodeError) as error:
        print(json.dumps({"status": "blocked", "result": getattr(error, "code", "discovery_failed")}, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result.get("status") in {"no_action", "prepared"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
