#!/usr/bin/env python3
"""Owner-local U15-U18 preparation adapters for weekly intelligence.

This module deliberately has no command-line surface and no provider setup. It
accepts only a sealed owner-local JSON configuration, derives safe artifacts in
the weekly coordinator's supplied state directory, and leaves publication,
promotion, source imports, and live retrieval unavailable.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
SCHEMA_VERSION = 1
STAGE_IDS = {
    "source_intake",
    "design_packet",
    "retrieval",
    "candidate_evaluation",
    "maintenance_link",
    "report_receipt",
}
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SAFE_CODE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,127}$")
LOCAL_POLICY = {
    "schema_version": 1,
    "source_scope": "owner-local-inline-export-only",
    "network": "deny",
    "gbrain": "not_used",
    "ledger": "not_used",
    "promotion": "prohibited",
    "publication": "prohibited",
}


class LocalAdapterError(ValueError):
    """Redacted adapter error translated by the weekly coordinator."""

    def __init__(self, code: str) -> None:
        normalized = _safe_code(code, "local_adapter_failed")
        self.code = normalized
        super().__init__(normalized)


class _BoundFile:
    __slots__ = ("label", "path", "data", "digest", "value")

    def __init__(self, label: str, path: Path, data: bytes, digest: str, value: Any) -> None:
        self.label = label
        self.path = path
        self.data = data
        self.digest = digest
        self.value = value


class _BoundDirectory:
    __slots__ = ("label", "path")

    def __init__(self, label: str, path: Path) -> None:
        self.label = label
        self.path = path


def _safe_code(value: Any, fallback: str) -> str:
    text = re.sub(r"[^a-z0-9_-]+", "_", str(value or "").strip().lower()).strip("_")[:128]
    return text if SAFE_CODE_RE.fullmatch(text or "") else fallback


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_bytes(value: Any) -> bytes:
    return (_canonical_json(value) + "\n").encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_json(value: Any) -> str:
    return _digest_bytes(_canonical_json(value).encode("utf-8"))


def _inside_stack(path: Path) -> bool:
    try:
        path.relative_to(ROOT.resolve())
        return True
    except ValueError:
        return False


def _absolute_path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise LocalAdapterError(f"{label}_path_invalid")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise LocalAdapterError(f"{label}_path_invalid")
    return Path(os.path.abspath(str(candidate)))


def _is_allowed_system_alias(path: Path) -> bool:
    allowed = {
        Path("/tmp"): Path("/private/tmp"),
        Path("/var"): Path("/private/var"),
        Path("/etc"): Path("/private/etc"),
    }
    expected = allowed.get(path)
    if expected is None:
        return False
    try:
        return Path(os.path.realpath(path)) == expected
    except OSError:
        return False


def _reject_symlink_ancestors(path: Path, label: str, *, allow_missing_leaf: bool = False) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current = current / component
        try:
            info = current.lstat()
        except FileNotFoundError:
            if allow_missing_leaf and current == path:
                return
            raise LocalAdapterError(f"{label}_unavailable") from None
        except OSError:
            raise LocalAdapterError(f"{label}_unavailable") from None
        if stat.S_ISLNK(info.st_mode) and not _is_allowed_system_alias(current):
            raise LocalAdapterError("owner_local_symlink_detected")


def _verify_private_file(value: Any, label: str) -> Path:
    lexical = _absolute_path(value, label)
    _reject_symlink_ancestors(lexical, label)
    try:
        resolved = lexical.resolve(strict=True)
        file_info = resolved.lstat()
        parent_info = resolved.parent.lstat()
    except OSError:
        raise LocalAdapterError(f"{label}_unavailable") from None
    if _inside_stack(resolved):
        raise LocalAdapterError("owner_local_path_in_stack")
    if not stat.S_ISREG(file_info.st_mode):
        raise LocalAdapterError(f"{label}_file_invalid")
    if not stat.S_ISDIR(parent_info.st_mode):
        raise LocalAdapterError(f"{label}_parent_invalid")
    if file_info.st_uid != os.getuid() or parent_info.st_uid != os.getuid():
        raise LocalAdapterError("owner_local_owner_invalid")
    if stat.S_IMODE(parent_info.st_mode) != 0o700:
        raise LocalAdapterError("owner_local_parent_permissions_invalid")
    if stat.S_IMODE(file_info.st_mode) != 0o600:
        raise LocalAdapterError("owner_local_file_permissions_invalid")
    return resolved


def _verify_private_directory(value: Any, label: str, *, outside_stack: bool = True) -> Path:
    lexical = _absolute_path(value, label)
    _reject_symlink_ancestors(lexical, label)
    try:
        resolved = lexical.resolve(strict=True)
        info = resolved.lstat()
    except OSError:
        raise LocalAdapterError(f"{label}_unavailable") from None
    if outside_stack and _inside_stack(resolved):
        raise LocalAdapterError("owner_local_path_in_stack")
    if not stat.S_ISDIR(info.st_mode):
        raise LocalAdapterError(f"{label}_directory_invalid")
    if info.st_uid != os.getuid():
        raise LocalAdapterError("owner_local_owner_invalid")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise LocalAdapterError("owner_local_directory_permissions_invalid")
    return resolved


def _prepare_private_state_directory(value: Any) -> Path:
    """Use an existing private state directory or create exactly its leaf."""

    lexical = _absolute_path(value, "state_directory")
    if _inside_stack(lexical.resolve(strict=False)):
        raise LocalAdapterError("owner_local_path_in_stack")
    _reject_symlink_ancestors(lexical, "state_directory", allow_missing_leaf=True)
    if lexical.exists():
        return _verify_private_directory(str(lexical), "state_directory")
    # A first CLI run may create its configured leaf, but never scaffolds a
    # broader path: its existing parent must already be owner-only.
    _verify_private_directory(str(lexical.parent), "state_directory_parent")
    try:
        lexical.mkdir(mode=0o700)
    except OSError:
        raise LocalAdapterError("state_directory_unavailable") from None
    return _verify_private_directory(str(lexical), "state_directory")


def _read_private_bytes(path: Path, label: str) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise LocalAdapterError(f"{label}_unavailable") from None
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise LocalAdapterError("owner_local_file_permissions_invalid")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _bind_json(value: Any, label: str) -> _BoundFile:
    path = _verify_private_file(value, label)
    data = _read_private_bytes(path, label)
    try:
        decoded = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise LocalAdapterError(f"{label}_json_invalid") from None
    return _BoundFile(label, path, data, _digest_bytes(data), decoded)


def _verify_unchanged(bound: _BoundFile) -> None:
    """Detect a reloadable domain input that changed after its sealed read."""

    current = _verify_private_file(str(bound.path), bound.label)
    if current != bound.path or _digest_bytes(_read_private_bytes(current, bound.label)) != bound.digest:
        raise LocalAdapterError("owner_local_input_changed")


def _load_fixed_module(name: str, filename: str) -> Any:
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise LocalAdapterError("domain_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        raise LocalAdapterError("domain_module_unavailable") from None
    return module


def _repo_file_digest(path: Path) -> str:
    try:
        return _digest_bytes(path.read_bytes())
    except OSError:
        raise LocalAdapterError("domain_module_unavailable") from None


def _iso_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or "T" not in value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _private_artifact_payload(value: Any, forbidden_paths: set[str]) -> bool:
    forbidden_keys = {
        "raw", "row", "raw_observation", "source_document",
        "source_path", "source_paths", "harness_root", "materialization_receipt",
    }
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in forbidden_keys:
                return False
            if not _private_artifact_payload(child, forbidden_paths):
                return False
        return True
    if isinstance(value, list):
        return all(_private_artifact_payload(child, forbidden_paths) for child in value)
    if isinstance(value, str):
        return not value.startswith("/") and value not in forbidden_paths
    return True


class LocalPreparationAdapters:
    """Safe local callback adapter used by ``WeeklyIntelligenceCoordinator``."""

    def __init__(
        self,
        config_path: Path,
        state_dir: Path,
        transport: Any | None = None,
        *,
        as_of: str | None = None,
    ) -> None:
        self._state_dir = _prepare_private_state_directory(str(state_dir))
        self._config_bound = _bind_json(str(config_path), "adapter_config")
        self._config = self._validate_config(self._config_bound.value)

        self._corpus = _load_fixed_module("stack_weekly_local_bookmark_private_corpus", "bookmark_private_corpus.py")
        self._packet = _load_fixed_module("stack_weekly_local_design_packet", "build-design-intelligence-packet.py")
        self._query = _load_fixed_module("stack_weekly_local_design_query", "query-design-intelligence.py")
        self._evaluator = _load_fixed_module("stack_weekly_local_design_evaluator", "evaluate-design-intelligence-candidate.py")
        self._retrieval_transport_mode = str(self._config.get("retrieval_transport", "programmatic_offline"))
        if as_of is not None and not _iso_timestamp(as_of):
            raise LocalAdapterError("retrieval_as_of_invalid")
        self._as_of = as_of
        if transport is not None:
            self._transport = transport
        elif self._retrieval_transport_mode == "live-gbrain-text-v1":
            self._transport = self._query.CliGBrainTransport(live=True)
        else:
            self._transport = None
        self._profiles_path = ROOT / "config" / "candidate-evaluation-profiles.json"
        try:
            self._profiles_data = json.loads(self._profiles_path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise LocalAdapterError("domain_module_unavailable") from None
        try:
            self._profile = self._evaluator._profile(self._profiles_data, "design-learning-v1")
        except Exception:
            raise LocalAdapterError("domain_module_unavailable") from None

        self._code_digests = {
            "weekly_local_adapters": _repo_file_digest(SCRIPT),
            "bookmark_private_corpus": _repo_file_digest(ROOT / "scripts" / "bookmark_private_corpus.py"),
            "build_design_intelligence_packet": _repo_file_digest(ROOT / "scripts" / "build-design-intelligence-packet.py"),
            "query_design_intelligence": _repo_file_digest(ROOT / "scripts" / "query-design-intelligence.py"),
            "validate_private_overlay": _repo_file_digest(ROOT / "scripts" / "validate-private-overlay.py"),
            "evaluate_design_intelligence_candidate": _repo_file_digest(ROOT / "scripts" / "evaluate-design-intelligence-candidate.py"),
            "candidate_evaluation_profiles": _repo_file_digest(self._profiles_path),
        }
        self._code_digest = _digest_json(self._code_digests)
        self._policy_digest = _digest_json(LOCAL_POLICY)
        self._prompt_version = str(getattr(self._packet, "DEFAULT_PROMPT", "design-intelligence-card-v1"))
        self._model_version = str(getattr(self._packet, "DEFAULT_MODEL", "local-deterministic-v1"))
        self._prompt_digest = _digest_json(self._prompt_version)
        self._model_digest = _digest_json(self._model_version)
        self._sampling = {"temperature": 0, "seed": 0}
        self._sampling_digest = _digest_json(self._sampling)

        self._source_document: dict[str, Any] | None = None
        self._source_snapshot: dict[str, Any] | None = None
        self._ledger_bound: _BoundFile | None = None
        if "source_document" in self._config:
            self._source_bound = _bind_json(self._config["source_document"], "source_document")
            self._source_document = self._validate_source_document(self._source_bound.value)
        else:
            self._source_bound = _bind_json(self._config["source_snapshot"], "source_snapshot")
            self._source_snapshot = self._validate_source_snapshot(self._source_bound.value)
            ledger_path = _verify_private_file(self._config["source_ledger"], "source_ledger")
            ledger_data = _read_private_bytes(ledger_path, "source_ledger")
            self._ledger_bound = _BoundFile(
                "source_ledger",
                ledger_path,
                ledger_data,
                _digest_bytes(ledger_data),
                None,
            )
        target = self._config.get("target_manifest")
        self._target_bound = _bind_json(target, "target_manifest") if target is not None else None
        if self._target_bound is not None and not isinstance(self._target_bound.value, Mapping):
            raise LocalAdapterError("target_manifest_json_invalid")
        request = self._config.get("retrieval_request")
        self._request_bound = _bind_json(request, "retrieval_request") if request is not None else None
        if self._request_bound is not None and not isinstance(self._request_bound.value, Mapping):
            raise LocalAdapterError("retrieval_request_json_invalid")
        grant = self._config.get("retrieval_grant")
        self._grant_bound = _bind_json(grant, "retrieval_grant") if grant is not None else None
        if self._grant_bound is not None and not isinstance(self._grant_bound.value, Mapping):
            raise LocalAdapterError("retrieval_grant_json_invalid")
        self._evaluation = self._load_evaluation(self._config.get("evaluation"))

    @staticmethod
    def _validate_config(value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise LocalAdapterError("adapter_config_json_invalid")
        allowed = {
            "schema_version", "source_document", "source_snapshot", "source_ledger",
            "retrieval_request", "target_manifest", "retrieval_grant", "evaluation", "retrieval_transport",
        }
        if set(value) - allowed or value.get("schema_version") != SCHEMA_VERSION:
            raise LocalAdapterError("adapter_config_fields_invalid")
        inline = "source_document" in value
        sealed = "source_snapshot" in value or "source_ledger" in value
        if inline == sealed:
            raise LocalAdapterError("adapter_config_fields_invalid")
        source_fields = ("source_document",) if inline else ("source_snapshot", "source_ledger")
        if not all(isinstance(value.get(field), str) and value[field] for field in source_fields):
            raise LocalAdapterError("adapter_config_fields_invalid")
        if "target_manifest" in value and value["target_manifest"] is not None and not isinstance(value["target_manifest"], str):
            raise LocalAdapterError("adapter_config_fields_invalid")
        if "retrieval_request" in value and value["retrieval_request"] is not None and not isinstance(value["retrieval_request"], str):
            raise LocalAdapterError("adapter_config_fields_invalid")
        if "retrieval_grant" in value and value["retrieval_grant"] is not None and not isinstance(value["retrieval_grant"], str):
            raise LocalAdapterError("adapter_config_fields_invalid")
        if value.get("retrieval_transport", "programmatic_offline") not in {"programmatic_offline", "live-gbrain-text-v1"}:
            raise LocalAdapterError("adapter_config_fields_invalid")
        if value.get("retrieval_transport") == "live-gbrain-text-v1" and not all(
            isinstance(value.get(field), str) and value[field]
            for field in ("retrieval_request", "target_manifest", "retrieval_grant")
        ):
            raise LocalAdapterError("adapter_config_fields_invalid")
        if "evaluation" in value and value["evaluation"] is not None and not isinstance(value["evaluation"], Mapping):
            raise LocalAdapterError("adapter_config_fields_invalid")
        return dict(value)

    @staticmethod
    def _validate_source_document(value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise LocalAdapterError("source_document_invalid")
        base = {"schema_version", "source_id", "captured_at"}
        inline = {"pages", "items"}
        if set(value) - (base | inline) or not base.issubset(value):
            raise LocalAdapterError("source_document_inline_only")
        if value.get("schema_version") != SCHEMA_VERSION or not isinstance(value.get("source_id"), str) or not value["source_id"]:
            raise LocalAdapterError("source_document_invalid")
        if not _iso_timestamp(value.get("captured_at")):
            raise LocalAdapterError("source_document_capture_time_invalid")
        selected = [key for key in inline if key in value]
        if len(selected) != 1 or not isinstance(value[selected[0]], list):
            raise LocalAdapterError("source_document_inline_only")
        return copy.deepcopy(dict(value))

    @staticmethod
    def _validate_source_snapshot(value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise LocalAdapterError("source_snapshot_invalid")
        observations = value.get("observations")
        if (
            value.get("schema_version") != SCHEMA_VERSION
            or value.get("completeness_state") not in {"complete", "partial"}
            or not isinstance(value.get("source_id"), str)
            or not _iso_timestamp(value.get("capture_time"))
            or not isinstance(observations, list)
            or value.get("observation_count") != len(observations)
            or not isinstance(value.get("set_digest"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", value["set_digest"])
        ):
            raise LocalAdapterError("source_snapshot_invalid")
        for observation in observations:
            if not isinstance(observation, Mapping):
                raise LocalAdapterError("source_snapshot_invalid")
            for key in ("evidence_id", "canonical_source_identity", "revision_digest", "content_digest"):
                if not isinstance(observation.get(key), str) or not observation[key]:
                    raise LocalAdapterError("source_snapshot_invalid")
        return copy.deepcopy(dict(value))

    def _load_evaluation(self, value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise LocalAdapterError("evaluation_config_invalid")
        required = {"packet", "materialization_receipt", "harness_root", "manifests", "results"}
        if set(value) != required:
            if set(value) <= required:
                return {"missing": True}
            raise LocalAdapterError("evaluation_config_invalid")
        manifests = value.get("manifests")
        results = value.get("results")
        split_names = {"development", "holdout", "rotating_canary"}
        if not isinstance(manifests, Mapping) or not isinstance(results, Mapping) or set(manifests) != split_names or set(results) != split_names:
            return {"missing": True}
        try:
            packet = _bind_json(value["packet"], "evaluation_packet")
            materialization = _bind_json(value["materialization_receipt"], "materialization_receipt")
            harness = _BoundDirectory("evaluation_harness_root", _verify_private_directory(value["harness_root"], "evaluation_harness_root"))
            bound_manifests = {name: _bind_json(manifests[name], f"evaluation_{name}_manifest") for name in sorted(split_names)}
            bound_results = {name: _bind_json(results[name], f"evaluation_{name}_results") for name in sorted(split_names)}
        except LocalAdapterError:
            raise
        if not isinstance(packet.value, Mapping) or not isinstance(materialization.value, Mapping):
            raise LocalAdapterError("evaluation_config_invalid")
        return {
            "packet": packet,
            "materialization": materialization,
            "harness": harness,
            "manifests": bound_manifests,
            "results": bound_results,
        }

    def _pinned_source_document(self) -> dict[str, Any]:
        if self._source_document is None:
            raise LocalAdapterError("source_document_unavailable")
        document = copy.deepcopy(self._source_document)
        timestamp = document["captured_at"]

        def pin_row(row: Any) -> Any:
            if not isinstance(row, Mapping):
                return row
            copied = dict(row)
            if not any(copied.get(key) for key in ("synced_at", "captured_at", "updated_at")):
                copied["captured_at"] = timestamp
            return copied

        if "items" in document:
            document["items"] = [pin_row(row) for row in document["items"]]
        else:
            pages: list[Any] = []
            for page in document["pages"]:
                if not isinstance(page, Mapping):
                    pages.append(page)
                    continue
                copied_page = dict(page)
                if isinstance(copied_page.get("rows"), list):
                    copied_page["rows"] = [pin_row(row) for row in copied_page["rows"]]
                pages.append(copied_page)
            document["pages"] = pages
        return document

    def _reconcile(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if self._source_snapshot is not None:
            if self._ledger_bound is None:
                raise LocalAdapterError("source_ledger_unavailable")
            _verify_unchanged(self._source_bound)
            _verify_unchanged(self._ledger_bound)
            snapshot = copy.deepcopy(self._source_snapshot)
            observations = snapshot.get("observations", [])
            evidence_ids = [str(row["evidence_id"]) for row in observations]
            try:
                raw_by_evidence = self._corpus.load_owner_rows(
                    self._ledger_bound.path,
                    evidence_ids,
                )
            except Exception:
                raise LocalAdapterError("source_ledger_read_failed") from None
            _verify_unchanged(self._source_bound)
            _verify_unchanged(self._ledger_bound)
            if set(raw_by_evidence) != set(evidence_ids):
                raise LocalAdapterError("source_ledger_incomplete")
            raw_records = [raw_by_evidence[evidence_id] for evidence_id in evidence_ids]
            for observation, raw in zip(observations, raw_records):
                try:
                    normalized, _record = self._corpus.normalize_observation(
                        raw,
                        str(observation.get("source_id", snapshot.get("source_id", "field-theory"))),
                        str(snapshot.get("snapshot_id", "sealed-snapshot")),
                    )
                except Exception:
                    raise LocalAdapterError("source_ledger_mismatch") from None
                for key in ("evidence_id", "canonical_source_identity", "revision_digest", "content_digest"):
                    if normalized.get(key) != observation.get(key):
                        raise LocalAdapterError("source_ledger_mismatch")
            return snapshot, raw_records
        try:
            snapshot, raw_records = self._corpus.reconcile_pages(self._pinned_source_document(), copy.deepcopy(LOCAL_POLICY))
        except Exception:
            raise LocalAdapterError("source_reconciliation_failed") from None
        if not isinstance(snapshot, Mapping) or not isinstance(raw_records, list):
            raise LocalAdapterError("source_reconciliation_failed")
        result = dict(snapshot)
        # The source export is the sole timestamp authority. Reconcile's
        # convenience clock must not make exact resume artifacts drift.
        result["capture_time"] = self._source_document["captured_at"]
        return result, raw_records

    def _effective_request(self) -> dict[str, Any] | None:
        if self._request_bound is None:
            return None
        request = copy.deepcopy(dict(self._request_bound.value))
        if self._as_of is not None:
            freshness = request.get("freshness")
            if not isinstance(freshness, Mapping):
                raise LocalAdapterError("retrieval_request_json_invalid")
            request["freshness"] = {**dict(freshness), "as_of": self._as_of}
        return request

    def _retrieval_attestation(self) -> dict[str, Any] | None:
        if self._retrieval_transport_mode != "live-gbrain-text-v1":
            return None
        if self._request_bound is None or self._target_bound is None or self._grant_bound is None:
            raise LocalAdapterError("live_retrieval_contract_unavailable")
        attest = getattr(self._transport, "campaign_attestation", None)
        if not callable(attest):
            raise LocalAdapterError("live_retrieval_contract_unavailable")
        try:
            for bound in (self._request_bound, self._target_bound, self._grant_bound):
                _verify_unchanged(bound)
            result = attest(
                self._effective_request(),
                target_manifest=self._target_bound.path,
                source_grant=self._grant_bound.path,
            )
            for bound in (self._request_bound, self._target_bound, self._grant_bound):
                _verify_unchanged(bound)
        except LocalAdapterError:
            raise
        except Exception:
            raise LocalAdapterError("live_retrieval_attestation_failed") from None
        if not isinstance(result, Mapping):
            raise LocalAdapterError("live_retrieval_attestation_failed")
        allowed = {
            "state", "reason_code", "source", "target_manifest_digest",
            "source_grant_digest", "index_version", "model_version",
            "source_freshness_at", "egress_contract", "provider_calls",
            "attestation_digest",
        }
        if set(result) != allowed:
            raise LocalAdapterError("live_retrieval_attestation_failed")
        return dict(result)

    def _source_manifest(
        self,
        snapshot: Mapping[str, Any],
        retrieval_attestation: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "state": str(snapshot.get("completeness_state", "failed")),
            "source_count": 1,
            "owner_local": True,
            "source_digest": self._source_bound.digest,
            "source_document_digest": self._source_bound.digest,
            "source_input_kind": "sealed_snapshot_ledger" if self._source_snapshot is not None else "inline_export",
            "source_ledger_digest": self._ledger_bound.digest if self._ledger_bound is not None else None,
            "config_digest": self._config_bound.digest,
            "code_digest": self._code_digest,
            "code_digests": dict(self._code_digests),
            "policy_digest": self._policy_digest,
            "snapshot_digest": _digest_json(snapshot),
            "retrieval_inputs": {
                "request_digest": self._request_bound.digest if self._request_bound is not None else None,
                "target_manifest_digest": self._target_bound.digest if self._target_bound is not None else None,
                "source_grant_digest": self._grant_bound.digest if self._grant_bound is not None else None,
                "target_authorization_code_digest": self._code_digests["validate_private_overlay"],
                "freshness_date": self._as_of[:10] if self._as_of is not None else None,
                "live_source_attestation": dict(retrieval_attestation) if retrieval_attestation is not None else None,
            },
        }

    def _source_delta(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        completeness = str(snapshot.get("completeness_state", "failed"))
        if completeness == "complete":
            state = "changed" if int(snapshot.get("observation_count", 0) or 0) else "empty"
        elif completeness == "partial":
            state = "partial"
        else:
            state = "failed"
        material = {
            "source_document_digest": self._source_bound.digest,
            "config_digest": self._config_bound.digest,
            "code_digest": self._code_digest,
            "policy_digest": self._policy_digest,
            "set_digest": snapshot.get("set_digest"),
            "state": state,
        }
        return {"schema_version": SCHEMA_VERSION, "state": state, "changed": state == "changed", "digest": _digest_json(material)}

    def _eval_config(self) -> dict[str, Any]:
        if not self._evaluation or self._evaluation.get("missing"):
            return {"schema_version": SCHEMA_VERSION, "state": "not_configured", "input_digests": {}}
        return {
            "schema_version": SCHEMA_VERSION,
            "state": "configured",
            "profile": "design-learning-v1",
            "input_digests": {
                "packet": self._evaluation["packet"].digest,
                "materialization_receipt": self._evaluation["materialization"].digest,
                "profiles": self._code_digests["candidate_evaluation_profiles"],
                "manifests": {name: bound.digest for name, bound in self._evaluation["manifests"].items()},
                "results": {name: bound.digest for name, bound in self._evaluation["results"].items()},
            },
        }

    def campaign_inputs(self) -> dict[str, Any]:
        snapshot, _raw_records = self._reconcile()
        retrieval_attestation = self._retrieval_attestation()
        live = self._retrieval_transport_mode == "live-gbrain-text-v1"
        return {
            "source_manifest": self._source_manifest(snapshot, retrieval_attestation),
            "source_delta": self._source_delta(snapshot),
            "model_config": {
                "schema_version": SCHEMA_VERSION,
                "model": self._model_version,
                "execution": "local-cli-read-only" if live else "local-deterministic-no-egress",
                "provider_calls": 0,
                "network": "local-subprocess-only" if live else "not_attempted",
                "egress_contract": "gbrain-keyword-fts-no-provider-v1" if live else "none",
            },
            "prompt_config": {
                "schema_version": SCHEMA_VERSION,
                "version": self._prompt_version,
                "digest": self._prompt_digest,
            },
            "eval_config": self._eval_config(),
        }

    def _artifact_directory(self, run_id: str) -> Path:
        artifacts = self._state_dir / "artifacts"
        run_dir = artifacts / run_id
        for directory in (artifacts, run_dir):
            if directory.exists():
                try:
                    info = directory.lstat()
                except OSError:
                    raise LocalAdapterError("stage_artifact_unavailable") from None
                if (
                    directory.is_symlink()
                    or not stat.S_ISDIR(info.st_mode)
                    or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o700
                ):
                    raise LocalAdapterError("stage_artifact_permissions_invalid")
                continue
            try:
                directory.mkdir(mode=0o700)
            except OSError:
                raise LocalAdapterError("stage_artifact_unavailable") from None
            try:
                info = directory.lstat()
            except OSError:
                raise LocalAdapterError("stage_artifact_unavailable") from None
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700 or not stat.S_ISDIR(info.st_mode):
                raise LocalAdapterError("stage_artifact_permissions_invalid")
        return run_dir

    def _persist(self, stage: str, run_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        forbidden_paths = {
            str(self._config_bound.path),
            str(self._source_bound.path),
            str(self._state_dir),
        }
        if self._ledger_bound is not None:
            forbidden_paths.add(str(self._ledger_bound.path))
        if self._target_bound is not None:
            forbidden_paths.add(str(self._target_bound.path))
        if not _private_artifact_payload(payload, forbidden_paths):
            raise LocalAdapterError("stage_artifact_privacy_invalid")
        directory = self._artifact_directory(run_id)
        target = directory / f"{stage}.json"
        data = _canonical_bytes(dict(payload))
        digest = _digest_bytes(data)
        if target.exists() or target.is_symlink():
            try:
                info = target.lstat()
            except OSError:
                raise LocalAdapterError("stage_artifact_unavailable") from None
            if (
                target.is_symlink()
                or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise LocalAdapterError("stage_artifact_permissions_invalid")
            if _read_private_bytes(target, "stage_artifact") != data:
                raise LocalAdapterError("stage_artifact_conflict")
        try:
            # The evaluator's owner-local writer uses a temporary inode plus a
            # no-clobber hard link, so an interrupted write cannot strand a
            # partial final artifact that poisons a deterministic resume.
            self._evaluator._write_idempotent(target, data)
        except Exception:
            raise LocalAdapterError("stage_artifact_conflict") from None
        actual = _read_private_bytes(target, "stage_artifact")
        if actual != data:
            raise LocalAdapterError("stage_artifact_conflict")
        digest = _digest_bytes(actual)
        return {
            "artifact_path": f"artifacts/{run_id}/{stage}.json",
            "output_digest": digest,
        }

    @staticmethod
    def _blocked(code: str, artifact: Mapping[str, Any] | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {"status": "blocked", "reason_code": _safe_code(code, "local_adapter_stage_failed")}
        if artifact is not None:
            result.update(artifact)
        return result

    @staticmethod
    def _prepared(artifact: Mapping[str, Any]) -> dict[str, Any]:
        return {"status": "prepared", **artifact}

    def _run_id(self, context: Any) -> str:
        if not isinstance(context, Mapping):
            raise LocalAdapterError("adapter_context_invalid")
        run_id = context.get("run_id")
        if not isinstance(run_id, str) or not SAFE_ID_RE.fullmatch(run_id):
            raise LocalAdapterError("adapter_context_invalid")
        return run_id

    def _source_stage(self, run_id: str) -> dict[str, Any]:
        snapshot, _raw_records = self._reconcile()
        artifact = self._persist("source_intake", run_id, snapshot)
        if snapshot.get("completeness_state") != "complete":
            return self._blocked("source_snapshot_incomplete", artifact)
        return self._prepared(artifact)

    def _design_stage(self, run_id: str) -> dict[str, Any]:
        snapshot, raw_records = self._reconcile()
        if snapshot.get("completeness_state") != "complete":
            return self._blocked("source_snapshot_incomplete")
        observations = snapshot.get("observations")
        if not isinstance(observations, list) or len(observations) != len(raw_records):
            return self._blocked("source_reconciliation_failed")
        input_doc = {
            "source_manifest": self._source_manifest(snapshot),
            "delta": self._source_delta(snapshot),
            "observations": [
                {"observation": public, "raw": raw}
                for public, raw in zip(observations, raw_records)
            ],
        }
        derivation = {
            "policy": LOCAL_POLICY,
            "config": {"adapter_config_digest": self._config_bound.digest, "execution": "local-deterministic-no-egress"},
            "sampling": self._sampling,
            "policy_digest": self._policy_digest,
            "config_digest": self._config_bound.digest,
            "code_digest": self._code_digest,
            "prompt_digest": self._prompt_digest,
            "model_digest": self._model_digest,
            "sampling_digest": self._sampling_digest,
        }
        try:
            packet = self._packet.build_packet(input_doc, analyzer=None, derivation=derivation)
        except Exception:
            return self._blocked("design_packet_build_failed")
        if not isinstance(packet, Mapping):
            return self._blocked("design_packet_build_failed")
        artifact = self._persist("design_packet", run_id, packet)
        if packet.get("status") in {"failed", "partial"}:
            return self._blocked("design_packet_not_prepared", artifact)
        return self._prepared(artifact)

    def _retrieval_stage(self, run_id: str) -> dict[str, Any]:
        if self._request_bound is None:
            return self._blocked("retrieval_request_missing")
        if self._target_bound is None:
            return self._blocked("target_manifest_missing")
        if self._retrieval_transport_mode == "live-gbrain-text-v1" and self._grant_bound is None:
            return self._blocked("retrieval_grant_missing")
        if self._transport is None:
            return self._blocked("live_retrieval_contract_unavailable")
        try:
            # ``retrieve`` must reread its attestation path. Prove the sealed
            # bytes immediately before and after that call rather than copying
            # a competing authority into temporary storage.
            for bound in (self._request_bound, self._target_bound, self._grant_bound):
                if bound is not None:
                    _verify_unchanged(bound)
            response = self._query.retrieve(
                self._effective_request(),
                target_manifest=self._target_bound.path,
                transport=self._transport,
                source_grant=self._grant_bound.path if self._grant_bound is not None else None,
            )
            for bound in (self._request_bound, self._target_bound, self._grant_bound):
                if bound is not None:
                    _verify_unchanged(bound)
        except LocalAdapterError as error:
            return self._blocked(error.code)
        except Exception:
            return self._blocked("retrieval_failed")
        if not isinstance(response, Mapping):
            return self._blocked("retrieval_failed")
        artifact_payload = dict(response)
        live = self._retrieval_transport_mode == "live-gbrain-text-v1"
        artifact_payload["adapter_transport"] = {
            "mode": "live-gbrain-text-v1" if live else "programmatic_offline",
            "live": live,
        }
        artifact = self._persist("retrieval", run_id, artifact_payload)
        status = str(response.get("status", "failed"))
        if status == "complete":
            return self._prepared(artifact)
        if status == "degraded":
            return self._blocked("retrieval_quality_gate_unmet", artifact)
        return self._blocked("retrieval_result_unavailable", artifact)

    def _evaluation_stage(self, run_id: str) -> dict[str, Any]:
        evaluation = self._evaluation
        if not evaluation or evaluation.get("missing"):
            artifact = self._persist("candidate_evaluation", run_id, {
                "schema_version": SCHEMA_VERSION,
                "status": "no_candidate_selected",
                "reason_code": "no_material_candidate_selected",
                "evaluation": "not_run",
                "synthetic_feedback_used": False,
                "human_feedback_used": False,
                "promotion": "prohibited",
                "publication": "prohibited",
            })
            return self._prepared(artifact)
        try:
            for bound in (
                evaluation["packet"],
                evaluation["materialization"],
                *evaluation["manifests"].values(),
                *evaluation["results"].values(),
            ):
                _verify_unchanged(bound)
            receipt = self._evaluator.evaluate_design_candidate(
                copy.deepcopy(dict(evaluation["packet"].value)),
                copy.deepcopy(dict(evaluation["materialization"].value)),
                manifests={name: bound.path for name, bound in evaluation["manifests"].items()},
                results={name: bound.path for name, bound in evaluation["results"].items()},
                profile=copy.deepcopy(dict(self._profile)),
                harness_root=evaluation["harness"].path,
            )
            for bound in (
                evaluation["packet"],
                evaluation["materialization"],
                *evaluation["manifests"].values(),
                *evaluation["results"].values(),
            ):
                _verify_unchanged(bound)
        except LocalAdapterError as error:
            return self._blocked(error.code)
        except Exception:
            return self._blocked("candidate_evaluation_failed")
        if not isinstance(receipt, Mapping):
            return self._blocked("candidate_evaluation_failed")
        artifact = self._persist("candidate_evaluation", run_id, receipt)
        status = str(receipt.get("status", "blocked-eval"))
        if status == "awaiting_approval":
            return self._prepared(artifact)
        if status == "blocked-eval":
            return self._blocked("candidate_evaluation_blocked", artifact)
        if status == "rejected":
            return self._blocked("candidate_evaluation_rejected", artifact)
        if status == "human_review_required":
            return self._blocked("candidate_evaluation_human_review_required", artifact)
        return self._blocked("candidate_evaluation_unexpected_status", artifact)

    def __call__(self, stage_id: str, context: Mapping[str, Any]) -> dict[str, Any]:
        if stage_id not in STAGE_IDS:
            return self._blocked("unsupported_stage")
        try:
            run_id = self._run_id(context)
            if stage_id == "source_intake":
                return self._source_stage(run_id)
            if stage_id == "design_packet":
                return self._design_stage(run_id)
            if stage_id == "retrieval":
                return self._retrieval_stage(run_id)
            if stage_id == "candidate_evaluation":
                return self._evaluation_stage(run_id)
            maintenance = context.get("maintenance") if isinstance(context, Mapping) else None
            if isinstance(maintenance, Mapping) and maintenance.get("status") == "linked":
                return {"status": "prepared"}
            return self._blocked("maintenance_receipt_not_linked")
        except LocalAdapterError as error:
            return self._blocked(error.code)
        except Exception:
            return self._blocked("local_adapter_stage_failed")
