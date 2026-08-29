#!/usr/bin/env python3
"""Retrieve source-scoped design inspiration without mutating GBrain.

The request and response are owner-local.  A trusted U9 target manifest is
verified before any candidate is read or ranked.  The live adapter exposes
only GBrain's read-only search operations under ``x-bookmarks``; it has no
import, reindex, provider-fallback, or configuration path.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import pwd
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
SOURCE = "x-bookmarks"
SCHEMA_VERSION = 1
RRF_K = 60
REQUEST_FIELDS = {"schema_version", "request_id", "source", "target", "context", "filters", "freshness", "top_k"}
SOURCE_GRANT_FIELDS = {
    "schema_version", "grant_id", "owner_identity", "source", "target_identity",
    "locator_scopes", "expires_at", "egress_contract", "allowed_cli_versions",
}
CONTEXT_FIELDS = {
    "project", "repository", "route", "component", "viewport", "device",
    "brief", "code", "markup", "screenshot",
}
OPAQUE_RE = re.compile(r"^[a-z][a-z0-9-]{1,32}:[a-f0-9]{16,64}$")
DIGEST_RE = re.compile(r"^[a-f0-9]{64}$")
TARGET_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
TARGET_ID_RE = re.compile(r"^local-target:[a-z0-9][a-z0-9-]*$")
OWNER_ID_RE = re.compile(r"^local-owner:[a-z0-9][a-z0-9-]*$")
LOCATOR_RE = re.compile(r"^gbrain:x-bookmarks/[A-Za-z0-9._~/-]+$")
BOOKMARK_SLUG_RE = re.compile(r"^(?:bookmarks/[A-Za-z0-9._~/-]+|bookmark-[a-f0-9]{32})$")
TERM_RE = re.compile(r"[a-z][a-z0-9-]{1,63}")
DESIGN_QUERY_PRIORITY = (
    "hierarchy", "navigation", "layout", "typography", "motion", "responsive",
    "mobile", "dashboard", "table", "filters", "form", "modal", "sidebar",
)
SAFE_RECEIPT_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
CLI_VERSION_RE = re.compile(r"^(?:gbrain\s+)?([0-9][A-Za-z0-9._-]{0,63})$")
ACCOUNT_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
SAFE_SUBPROCESS_ENV_KEYS = ("PATH", "HOME", "TMPDIR")
DEFAULT_GBRAIN_CLI = str(ACCOUNT_HOME / ".bun" / "bin" / "gbrain")
EXPECTED_GBRAIN_CLI = ACCOUNT_HOME / ".bun" / "install" / "global" / "node_modules" / "gbrain" / "src" / "cli.ts"
DEFAULT_BUN_CLI = Path("/opt/homebrew/bin/bun")
EXPECTED_BUN_CLI = Path("/opt/homebrew/Cellar/bun/1.3.14/bin/bun")
DEFAULT_GBRAIN_CONFIG = ACCOUNT_HOME / ".gbrain" / "config.json"
PINNED_OPERATION_HELPER = ROOT / "scripts" / "gbrain-pinned-operation.ts"
LIVE_EGRESS_CONTRACT = "gbrain-keyword-fts-no-provider-v1"
SUPPORTED_LIVE_CLI_VERSIONS = frozenset({"0.42.67.0"})
ALLOWED_LOCATOR_SCOPES = frozenset({"bookmarks/", "bookmark-"})
ALLOWED_LOCAL_POSTGRES_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
ALLOWED_LOCAL_POSTGRES_PORTS = frozenset({5432})
ALLOWED_LOCAL_POSTGRES_DATABASES = frozenset({"gbrain_mookie"})


class RetrievalError(ValueError):
    """A fail-closed authorization, request, transport, or response error."""


_TARGET_BINDING_TOKEN = object()
_SOURCE_GRANT_TOKEN = object()


def _trusted_bun_executable(path: str | Path) -> str | None:
    lexical = Path(path)
    if lexical != DEFAULT_BUN_CLI:
        return None
    try:
        resolved = lexical.resolve(strict=True)
        expected = EXPECTED_BUN_CLI.resolve(strict=True)
        details = resolved.lstat()
    except OSError:
        return None
    if (
        resolved != expected
        or not stat.S_ISREG(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) & 0o022
        or not os.access(resolved, os.X_OK)
    ):
        return None
    return str(resolved)


def _trusted_gbrain_cli(path: str | Path) -> str | None:
    lexical = Path(path)
    if lexical != Path(DEFAULT_GBRAIN_CLI):
        return None
    try:
        resolved = lexical.resolve(strict=True)
        expected = EXPECTED_GBRAIN_CLI.resolve(strict=True)
        details = resolved.lstat()
        package = json.loads((expected.parents[1] / "package.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if (
        resolved != expected
        or not stat.S_ISREG(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) & 0o022
        or not os.access(resolved, os.X_OK)
        or not isinstance(package, dict)
        or package.get("name") != "gbrain"
        or package.get("version") != "0.42.67.0"
    ):
        return None
    return str(resolved)


class _TrustedTarget(dict[str, str]):
    """Internal capability produced only after owner-local manifest validation."""

    __slots__ = ("_binding_token",)

    def __init__(self, *, name: str, identity: str, manifest_digest: str) -> None:
        super().__init__(name=name, identity=identity, manifest_digest=manifest_digest)
        self._binding_token = _TARGET_BINDING_TOKEN


class _TrustedSourceGrant(dict[str, Any]):
    """Internal capability produced only after owner-local grant validation."""

    __slots__ = ("_binding_token",)

    def __init__(self, **values: Any) -> None:
        super().__init__(values)
        self._binding_token = _SOURCE_GRANT_TOKEN


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def opaque(prefix: str, value: Any) -> str:
    return f"{prefix}:{digest(value)}"


def owner_local_path(path: Path, label: str) -> Path:
    raw = Path(path).expanduser()
    if raw.is_symlink() or raw.parent.is_symlink():
        raise RetrievalError(f"{label} must not use a symlink")
    resolved = raw.resolve(strict=False)
    try:
        resolved.relative_to(ROOT)
    except ValueError:
        return resolved
    raise RetrievalError(f"{label} must be outside the repository checkout")


def write_response(path: Path, response: dict[str, Any]) -> Path:
    target = owner_local_path(path, "owner-local retrieval response")
    staged: Path | None = None
    try:
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_file():
                raise RetrievalError("owner-local retrieval response must be a regular file")
            details = target.stat()
            if details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) != 0o600:
                raise RetrievalError("existing owner-local retrieval response must be owner-only mode 0600")
        if target.parent.exists():
            if target.parent.is_symlink() or not target.parent.is_dir():
                raise RetrievalError("owner-local retrieval response parent must be a regular directory")
            details = target.parent.stat()
            if details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) != 0o700:
                raise RetrievalError("owner-local retrieval response parent must be owner-only mode 0700")
        else:
            target.parent.mkdir(parents=True, mode=0o700)
            os.chmod(target.parent, 0o700)
        descriptor, staged_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        staged = Path(staged_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(response, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(staged, 0o600)
        os.replace(staged, target)
        staged = None
    except OSError as exc:
        raise RetrievalError("unable to write owner-local retrieval response") from exc
    finally:
        if staged is not None:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                pass
    return target


def load_owner_request(path: Path) -> dict[str, Any]:
    request_path = owner_local_path(path, "owner-local retrieval request")
    try:
        parent = request_path.parent.stat()
        details = request_path.stat()
    except OSError as exc:
        raise RetrievalError("owner-local retrieval request is unavailable") from exc
    if (
        request_path.is_symlink()
        or not request_path.is_file()
        or request_path.parent.is_symlink()
        or parent.st_uid != os.getuid()
        or details.st_uid != os.getuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
        or stat.S_IMODE(details.st_mode) != 0o600
    ):
        raise RetrievalError("owner-local retrieval request requires directory mode 0700 and file mode 0600")
    value = load_json(request_path)
    if not isinstance(value, dict):
        raise RetrievalError("request must be an object")
    return value


def _load_overlay_module() -> Any:
    path = ROOT / "scripts" / "validate-private-overlay.py"
    spec = importlib.util.spec_from_file_location("stack_private_overlay_for_retrieval", path)
    if spec is None or spec.loader is None:
        raise RetrievalError("private target authorization validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_target(request: dict[str, Any], manifest_path: Path) -> _TrustedTarget:
    target = request.get("target")
    if not isinstance(target, dict) or set(target) != {"name", "identity", "owner_identity"}:
        raise RetrievalError("request target must contain name, identity, and owner_identity")
    name, identity, owner = target.get("name"), target.get("identity"), target.get("owner_identity")
    if not isinstance(name, str) or not TARGET_RE.fullmatch(name):
        raise RetrievalError("request target name is invalid")
    if not isinstance(identity, str) or not TARGET_ID_RE.fullmatch(identity):
        raise RetrievalError("request target identity is invalid")
    if not isinstance(owner, str) or not OWNER_ID_RE.fullmatch(owner):
        raise RetrievalError("request target owner identity is invalid")
    manifest = owner_local_path(manifest_path, "trusted target manifest")
    try:
        overlay = _load_overlay_module()
        overlay.validate_target_manifest(manifest, {"owner_identity": owner}, name, identity)
    except Exception as exc:
        raise RetrievalError("trusted target attestation failed") from exc
    try:
        manifest_digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    except OSError as exc:
        raise RetrievalError("trusted target attestation failed") from exc
    return _TrustedTarget(name=name, identity=identity, manifest_digest=manifest_digest)


def _load_owner_capability(path: Path, label: str) -> tuple[dict[str, Any], str]:
    capability = owner_local_path(path, label)
    try:
        parent = capability.parent.stat()
        details = capability.stat()
        payload = capability.read_bytes()
        value = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RetrievalError(f"{label} is unavailable") from exc
    if (
        capability.is_symlink()
        or not capability.is_file()
        or capability.parent.is_symlink()
        or parent.st_uid != os.getuid()
        or details.st_uid != os.getuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
        or stat.S_IMODE(details.st_mode) != 0o600
        or not isinstance(value, dict)
    ):
        raise RetrievalError(f"{label} requires owner-only file mode 0600 in directory mode 0700")
    return value, hashlib.sha256(payload).hexdigest()


def validate_source_grant(
    request: dict[str, Any], target: _TrustedTarget, grant_path: Path,
) -> _TrustedSourceGrant:
    value, grant_digest = _load_owner_capability(grant_path, "trusted source grant")
    if set(value) != SOURCE_GRANT_FIELDS or value.get("schema_version") != SCHEMA_VERSION:
        raise RetrievalError("trusted source grant fields are invalid")
    grant_id = value.get("grant_id")
    owner_identity = value.get("owner_identity")
    target_identity = value.get("target_identity")
    scopes = value.get("locator_scopes")
    versions = value.get("allowed_cli_versions")
    expires_at = _parse_time(value.get("expires_at"))
    as_of = _parse_time(request.get("freshness", {}).get("as_of"))
    if not isinstance(grant_id, str) or not OPAQUE_RE.fullmatch(grant_id):
        raise RetrievalError("trusted source grant identity is invalid")
    if owner_identity != request["target"]["owner_identity"] or target_identity != target["identity"]:
        raise RetrievalError("trusted source grant target binding is invalid")
    if value.get("source") != SOURCE or value.get("egress_contract") != LIVE_EGRESS_CONTRACT:
        raise RetrievalError("trusted source grant source contract is invalid")
    if (
        not isinstance(scopes, list) or not scopes or len(scopes) != len(set(scopes))
        or not all(isinstance(scope, str) and scope in ALLOWED_LOCATOR_SCOPES for scope in scopes)
    ):
        raise RetrievalError("trusted source grant locator scopes are invalid")
    if (
        not isinstance(versions, list) or not versions or len(versions) != len(set(versions))
        or not all(isinstance(version, str) and version in SUPPORTED_LIVE_CLI_VERSIONS for version in versions)
    ):
        raise RetrievalError("trusted source grant CLI versions are invalid")
    if expires_at is None or as_of is None or expires_at <= as_of or expires_at <= _utc_now():
        raise RetrievalError("trusted source grant is expired")
    return _TrustedSourceGrant(
        grant_id=grant_id,
        owner_identity=owner_identity,
        source=SOURCE,
        target_identity=target_identity,
        locator_scopes=tuple(sorted(scopes)),
        expires_at=expires_at.isoformat(),
        egress_contract=LIVE_EGRESS_CONTRACT,
        allowed_cli_versions=tuple(sorted(versions)),
        grant_digest=grant_digest,
    )


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        text += "T00:00:00+00:00"
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_now() -> datetime:
    """Return the authoritative execution clock for expiring live grants."""

    return datetime.now(timezone.utc)


def _terms(value: Any) -> set[str]:
    values: list[str] = []
    if isinstance(value, str):
        values.append(value)
    elif isinstance(value, dict):
        for child in value.values():
            values.extend(_terms(child))
    elif isinstance(value, list):
        for child in value:
            values.extend(_terms(child))
    return set(TERM_RE.findall(" ".join(values).lower()))


def _request_query(request: dict[str, Any]) -> str:
    context = request.get("context")
    if not isinstance(context, dict):
        raise RetrievalError("request context must be an object")
    values = [
        context.get("project"), context.get("repository"), context.get("route"),
        context.get("component"), context.get("device"), context.get("brief"),
        context.get("code"), context.get("markup"),
    ]
    terms = _terms(values)
    filters = request.get("filters", {})
    exact_values = [str(filters[key]) for key in ("evidence_id", "author", "date", "folder", "url") if filters.get(key)]
    if not terms and not exact_values:
        raise RetrievalError("request context has no searchable terms")
    component_terms = TERM_RE.findall(str(context.get("component", "")).lower())
    focused: list[str] = []
    for term in [*(component_terms[:1]), "interface", "design"]:
        if term not in focused:
            focused.append(term)
    for term in DESIGN_QUERY_PRIORITY:
        if term in terms and term not in focused:
            focused.append(term)
            break
    if not component_terms:
        for term in sorted(terms):
            if term not in focused:
                focused.insert(0, term)
                break
    return " ".join(exact_values + focused)[:4096]


def validate_request(request: dict[str, Any]) -> None:
    if not isinstance(request, dict) or request.get("schema_version") != SCHEMA_VERSION:
        raise RetrievalError("request schema_version is unsupported")
    if set(request) != REQUEST_FIELDS:
        raise RetrievalError("request has missing or unsupported fields")
    if not isinstance(request.get("request_id"), str) or not OPAQUE_RE.fullmatch(request["request_id"]):
        raise RetrievalError("request_id must be opaque")
    if request.get("source") != SOURCE:
        raise RetrievalError("retrieval source must be x-bookmarks")
    top_k = request.get("top_k")
    if not isinstance(top_k, int) or isinstance(top_k, bool) or not 3 <= top_k <= 7:
        raise RetrievalError("top_k must be between 3 and 7")
    freshness = request.get("freshness")
    if not isinstance(freshness, dict) or set(freshness) != {"as_of", "max_age_days"}:
        raise RetrievalError("freshness must contain as_of and max_age_days")
    if _parse_time(freshness.get("as_of")) is None:
        raise RetrievalError("freshness as_of must be a timestamp")
    max_age = freshness.get("max_age_days")
    if not isinstance(max_age, int) or isinstance(max_age, bool) or max_age < 0:
        raise RetrievalError("freshness max_age_days must be nonnegative")
    filters = request.get("filters", {})
    allowed_filters = {"evidence_id", "author", "date", "folder", "url"}
    if not isinstance(filters, dict) or not set(filters) <= allowed_filters:
        raise RetrievalError("request filters are invalid")
    for value in filters.values():
        if not isinstance(value, str) or not value or len(value) > 2048:
            raise RetrievalError("request filters must be nonempty strings")
    if "evidence_id" in filters and not OPAQUE_RE.fullmatch(filters["evidence_id"]):
        raise RetrievalError("evidence_id filter must be opaque")
    context = request.get("context")
    if not isinstance(context, dict) or not set(context) <= CONTEXT_FIELDS:
        raise RetrievalError("request context must be an object")
    for key in ("project", "repository", "route", "component", "device", "brief", "code", "markup"):
        if key in context and not isinstance(context[key], str):
            raise RetrievalError(f"request context {key} must be a string")
    viewport = context.get("viewport")
    if viewport is not None and (
        not isinstance(viewport, dict)
        or not isinstance(viewport.get("width"), int)
        or not isinstance(viewport.get("height"), int)
        or isinstance(viewport.get("width"), bool)
        or isinstance(viewport.get("height"), bool)
        or viewport["width"] <= 0 or viewport["height"] <= 0
    ):
        raise RetrievalError("request viewport is invalid")
    screenshot = context.get("screenshot")
    if screenshot is not None and (
        not isinstance(screenshot, dict)
        or set(screenshot) != {"path", "digest"}
        or not isinstance(screenshot.get("path"), str)
        or not screenshot.get("path")
        or not isinstance(screenshot.get("digest"), str)
        or not DIGEST_RE.fullmatch(screenshot["digest"])
    ):
        raise RetrievalError("request screenshot contract is invalid")
    _request_query(request)


def _candidate(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    required = ("candidate_id", "evidence_id", "source", "citation_locator")
    if any(not isinstance(value.get(key), str) for key in required):
        return None
    if not OPAQUE_RE.fullmatch(value["candidate_id"]) or not OPAQUE_RE.fullmatch(value["evidence_id"]):
        return None
    if value["source"] != SOURCE or not LOCATOR_RE.fullmatch(value["citation_locator"]):
        return None
    media_identity = value.get("media_identity")
    if media_identity is not None and (not isinstance(media_identity, str) or not OPAQUE_RE.fullmatch(media_identity)):
        return None
    text_terms = sorted(_terms(value.get("text_terms", [])))
    image_terms = sorted(_terms(value.get("image_terms", [])))
    metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
    targets = value.get("authorized_target_identities")
    if (
        not isinstance(targets, list) or not targets
        or not all(isinstance(item, str) and TARGET_ID_RE.fullmatch(item) for item in targets)
    ):
        return None
    media_state = str(value.get("media_state", "unknown"))
    if media_state not in {"resolved", "partial", "unavailable", "corrupt", "unknown"}:
        media_state = "unknown"
    return {
        "candidate_id": value["candidate_id"],
        "evidence_id": value["evidence_id"],
        "source": SOURCE,
        "citation_locator": value["citation_locator"],
        "media_identity": media_identity,
        "text_terms": text_terms,
        "image_terms": image_terms,
        "metadata": metadata,
        "indexed_at": value.get("indexed_at"),
        "media_state": media_state,
        "authorized_target_identities": list(targets),
        "reported_stale": value.get("reported_stale") is True,
        "transport_score": float(value.get("transport_score", 0.0)) if isinstance(value.get("transport_score", 0.0), (int, float)) else 0.0,
    }


def _exact_reasons(candidate: dict[str, Any], filters: dict[str, str]) -> list[str]:
    metadata = candidate["metadata"]
    reasons: list[str] = []
    for key in ("author", "date", "folder", "url"):
        if key in filters and str(metadata.get(key, "")) == filters[key]:
            reasons.append("exact-" + key)
    if filters.get("evidence_id") == candidate["evidence_id"]:
        reasons.append("exact-evidence-id")
    return reasons


def _rank_map(values: list[dict[str, Any]]) -> dict[str, int]:
    return {row["candidate_id"]: index for index, row in enumerate(values, start=1)}


def _result_freshness(candidate: dict[str, Any], as_of: datetime) -> tuple[int | None, str]:
    indexed = _parse_time(candidate.get("indexed_at"))
    if indexed is None:
        return None, "missing"
    if indexed > as_of:
        return None, "future"
    return int((as_of - indexed).total_seconds() // 86400), "fresh"


def retrieve(
    request: dict[str, Any], *, target_manifest: Path, transport: Any,
    source_grant: Path | None = None,
) -> dict[str, Any]:
    validate_request(request)
    target = validate_target(request, target_manifest)
    trusted_grant: _TrustedSourceGrant | None = None
    if bool(getattr(transport, "requires_source_grant", False)):
        if source_grant is None:
            raise RetrievalError("live retrieval requires a trusted source grant")
        trusted_grant = validate_source_grant(request, target, source_grant)
    bind_target = getattr(transport, "bind_trusted_target", None)
    if callable(bind_target):
        bind_target(target, request["freshness"], trusted_grant)
    query = _request_query(request)
    top_k = request["top_k"]
    filters = request.get("filters", {})
    screenshot = request["context"].get("screenshot")
    text_response = transport.text_search(query, max(20, top_k * 4))
    if not isinstance(text_response, dict):
        raise RetrievalError("text transport response is invalid")
    image_response = {"state": "not_requested", "results": []}
    if screenshot is not None:
        image_response = transport.image_search(screenshot["path"], query, max(20, top_k * 4))
        if not isinstance(image_response, dict):
            raise RetrievalError("image transport response is invalid")
    def authorized(values: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for value in values if isinstance(values, list) else []:
            normalized = _candidate(value)
            if normalized is None:
                continue
            targets = normalized["authorized_target_identities"]
            if target["identity"] not in targets:
                continue
            rows.append(normalized)
        return rows

    text_values = authorized(text_response.get("results", []))
    image_values = authorized(image_response.get("results", []))
    candidates: dict[str, dict[str, Any]] = {}
    for normalized in text_values + image_values:
        candidates[normalized["candidate_id"]] = normalized
    context_terms = _terms(query)
    lexical = sorted(
        candidates.values(),
        key=lambda row: (-len(context_terms & set(row["text_terms"])), row["candidate_id"]),
    )
    exact = sorted(
        (row for row in candidates.values() if _exact_reasons(row, filters)),
        key=lambda row: (-len(_exact_reasons(row, filters)), row["candidate_id"]),
    )
    ranks = {
        "exact": _rank_map(exact),
        "lexical": _rank_map(lexical),
        "text": _rank_map(text_values),
        "image": _rank_map(image_values),
    }
    weights = {"exact": 3.0, "lexical": 1.5, "text": 2.0, "image": 2.0}
    scored: list[tuple[float, dict[str, Any], list[str]]] = []
    as_of = _parse_time(request["freshness"]["as_of"])
    assert as_of is not None
    for candidate in candidates.values():
        identity = candidate["candidate_id"]
        score = sum(weights[lane] / (RRF_K + rank_map[identity]) for lane, rank_map in ranks.items() if identity in rank_map)
        reasons = _exact_reasons(candidate, filters)
        if identity in ranks["lexical"] and context_terms & set(candidate["text_terms"]):
            reasons.append("lexical-context")
        if identity in ranks["text"]:
            reasons.append("gbrain-text")
        if identity in ranks["image"]:
            reasons.append("gbrain-image")
        scored.append((score, candidate, sorted(set(reasons))))
    scored.sort(key=lambda row: (-row[0], row[1]["candidate_id"]))
    results: list[dict[str, Any]] = []
    stale_count = 0
    future_count = 0
    max_age = request["freshness"]["max_age_days"]
    for rank, (score, candidate, reasons) in enumerate(scored[:top_k], start=1):
        age, freshness_state = _result_freshness(candidate, as_of)
        stale = freshness_state != "fresh" or age is not None and age > max_age or candidate["reported_stale"]
        stale_count += int(stale)
        future_count += int(freshness_state == "future")
        if freshness_state == "missing":
            uncertainty = "Index date is unavailable."
        elif freshness_state == "future":
            uncertainty = "Result date is in the future of the pinned request."
        elif stale:
            uncertainty = "Result exceeds the requested freshness window."
        else:
            uncertainty = "Ranking is deterministic for the pinned request and index response."
        results.append({
            "rank": rank,
            "candidate_id": candidate["candidate_id"],
            "evidence_id": candidate["evidence_id"],
            "source": SOURCE,
            "media_identity": candidate["media_identity"],
            "citation_locator": candidate["citation_locator"],
            "similarity_score": round(score, 12),
            "similarity_reasons": reasons or ["source-scoped-retrieval"],
            "uncertainty": uncertainty,
            "media_state": candidate["media_state"],
            "freshness_age_days": age,
            "stale": stale,
        })
    valid_text_states = {"complete", "partial", "empty", "unavailable", "failed"}
    valid_image_states = {"complete", "partial", "not_requested", "unavailable", "failed"}
    text_state = str(text_response.get("state", "failed"))
    image_state = str(image_response.get("state", "not_requested"))
    if text_state not in valid_text_states:
        text_state = "failed"
    if image_state not in valid_image_states:
        image_state = "failed"
    missing_modalities: list[str] = []
    degradations: list[str] = []
    reason_code = text_response.get("reason_code")
    if not isinstance(reason_code, str) or not re.fullmatch(r"[a-z0-9-]{1,64}", reason_code):
        reason_code = None
    if text_state in {"unavailable", "failed"}:
        missing_modalities.append("text")
        degradations.append("text-unavailable")
    elif text_state == "partial":
        degradations.append("text-partial")
    if screenshot is not None and image_state in {"unavailable", "failed"}:
        missing_modalities.append("image")
        degradations.append("image-unavailable")
    elif screenshot is not None and image_state == "partial":
        degradations.append("image-partial")
    if stale_count:
        degradations.append("stale-index")
    if future_count:
        degradations.append("future-index")
    if results and len(results) < 3:
        degradations.append("sparse-results")
    if text_state in {"failed", "unavailable"} and not results:
        status = "failed"
    elif not results:
        status = "degraded" if text_state == "partial" else "empty"
    elif degradations or text_state not in {"complete", "partial"}:
        status = "degraded"
    else:
        status = "complete"
    index_versions = sorted({str(value) for value in (text_response.get("index_version"), image_response.get("index_version")) if isinstance(value, str) and SAFE_RECEIPT_RE.fullmatch(value)})
    model_versions = sorted({str(value) for value in (text_response.get("model_version"), image_response.get("model_version")) if isinstance(value, str) and SAFE_RECEIPT_RE.fullmatch(value)})
    source_freshness = text_response.get("source_freshness_at")
    freshness_as_of = source_freshness if isinstance(source_freshness, str) and _parse_time(source_freshness) is not None else request["freshness"]["as_of"]
    receipt_binding = {
        "source": SOURCE,
        "manifest_digest": target["manifest_digest"],
        "source_grant_digest": trusted_grant["grant_digest"] if trusted_grant is not None else None,
        "index_versions": index_versions or ["unknown"],
        "model_versions": model_versions or ["unknown"],
        "freshness_as_of": freshness_as_of,
        "egress_contract": LIVE_EGRESS_CONTRACT if trusted_grant is not None else "fixture-programmatic-v1",
    }
    response: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "response_id": opaque("response", {"request": request, "receipt_binding": receipt_binding, "results": [row["candidate_id"] for row in results]}),
        "request_id": request["request_id"],
        "request_digest": digest(request),
        "status": status,
        "source": SOURCE,
        "target": target,
        "authorization": {
            "mode": "source-wide-owner-grant-v1" if trusted_grant is not None else "per-result-fixture-v1",
            "target_manifest_digest": target["manifest_digest"],
            "source_grant_digest": trusted_grant["grant_digest"] if trusted_grant is not None else None,
        },
        "results": results,
        "result_count": len(results),
        "missing_modalities": missing_modalities,
        "degradations": sorted(set(degradations)),
        "reason_code": reason_code,
        "index": {
            "versions": receipt_binding["index_versions"],
            "model_versions": receipt_binding["model_versions"],
            "freshness_as_of": freshness_as_of,
            "max_age_days": max_age,
            "stale_result_count": stale_count,
        },
        "ranking": {
            "method": "weighted-rrf-v1",
            "rrf_k": RRF_K,
            "deterministic": True,
            "weights": weights,
        },
        "safety": {
            "target_attested": True,
            "source_grant_attested": trusted_grant is not None or not bool(getattr(transport, "requires_source_grant", False)),
            "source_scope_enforced": True,
            "configuration_changed": False,
            "reindex_attempted": False,
            "paid_fallback_attempted": False,
            "external_write_attempted": False,
            "egress_contract": receipt_binding["egress_contract"],
            "provider_calls": 0,
        },
    }
    response["response_digest"] = digest(response)
    return response


def evaluate_ranking(ranked_ids: list[str], qrels: dict[str, int], *, k: int = 5) -> dict[str, float]:
    top = ranked_ids[:k]
    relevant = {identity for identity, grade in qrels.items() if isinstance(grade, int) and grade > 0}
    recall = len(relevant & set(top)) / len(relevant) if relevant else 1.0
    dcg = sum((2 ** int(qrels.get(identity, 0)) - 1) / math.log2(rank + 1) for rank, identity in enumerate(top, start=1))
    ideal = sorted((int(grade) for grade in qrels.values() if isinstance(grade, int) and grade > 0), reverse=True)[:k]
    idcg = sum((2 ** grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(ideal, start=1))
    return {"recall_at_k": recall, "ndcg_at_k": dcg / idcg if idcg else 1.0}


def _parse_cli_json(stdout: str) -> Any:
    if not isinstance(stdout, str) or not stdout.strip():
        raise RetrievalError("GBrain returned no valid JSON payload")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RetrievalError("GBrain returned invalid JSON") from exc


def _gbrain_candidate(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("source_id") != SOURCE:
        return None
    if value.get("unverified") is True or value.get("archived") is True or value.get("corrupted") is True:
        return None
    slug = value.get("slug")
    if not isinstance(slug, str) or not re.fullmatch(r"[A-Za-z0-9._~/-]+", slug):
        return None
    if (
        not isinstance(value.get("page_id"), int)
        or isinstance(value.get("page_id"), bool)
        or not isinstance(value.get("chunk_id"), int)
        or isinstance(value.get("chunk_id"), bool)
        or not isinstance(value.get("chunk_text"), str)
        or not value["chunk_text"]
        or not isinstance(value.get("stale"), bool)
        or not isinstance(value.get("score"), (int, float))
        or isinstance(value.get("score"), bool)
        or not math.isfinite(float(value["score"]))
    ):
        return None
    if value.get("effective_date") is not None and _parse_time(value.get("effective_date")) is None:
        return None
    modality = str(value.get("modality", "text")).lower()
    if modality != "text":
        return None
    text_parts = [
        value.get(key) for key in ("title", "chunk_text", "evidence")
        if isinstance(value.get(key), str)
    ]
    text = "\n".join(text_parts)
    matched = re.search(r"(?:bookmark|evidence):[a-f0-9]{16,64}", text)
    source_identity = matched.group(0) if matched else opaque("source-result", {"slug": slug, "page_id": value.get("page_id")})
    metadata: dict[str, str] = {}
    for match in re.finditer(r"(?im)^(author|date|folder|url):\s*(.+?)\s*$", text):
        metadata[match.group(1).lower()] = match.group(2)
    return {
        "candidate_id": opaque("candidate", {"source": SOURCE, "slug": slug, "chunk_id": value.get("chunk_id")}),
        "evidence_id": opaque("evidence", source_identity),
        "source": SOURCE,
        "citation_locator": f"gbrain:{SOURCE}/{slug}",
        "media_identity": None,
        "text_terms": sorted(_terms(text)),
        "image_terms": [],
        "metadata": metadata,
        "indexed_at": value.get("effective_date"),
        "media_state": "unavailable",
        "reported_stale": value["stale"],
        "transport_score": value["score"],
    }


class CliGBrainTransport:
    """Opt-in, text-only GBrain adapter with a target-bound read receipt."""

    requires_source_grant = True

    def __init__(
        self,
        cli_path: str | None = None,
        runner: Callable[..., Any] | None = None,
        *,
        live: bool = False,
        version_provider: Callable[[], str] | None = None,
        bun_path: str | Path | None = None,
        keyword_runner: Callable[..., Any] | None = None,
        gbrain_config_path: Path | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.cli_path = cli_path or DEFAULT_GBRAIN_CLI
        self.runner = runner or subprocess.run
        self.live = live
        self.version_provider = version_provider
        self.bun_path = bun_path or DEFAULT_BUN_CLI
        self.keyword_runner = keyword_runner or runner or subprocess.run
        self.gbrain_config_path = gbrain_config_path or DEFAULT_GBRAIN_CONFIG
        self.now_provider = now_provider or _utc_now
        self._trusted_target: _TrustedTarget | None = None
        self._source_grant: _TrustedSourceGrant | None = None
        self._freshness: dict[str, Any] | None = None
        self._attestation: dict[str, str] | None = None
        self._attestation_state = "unavailable"
        self._attestation_reason = "trusted-target-unbound"

    @staticmethod
    def _environment() -> dict[str, str]:
        return {
            "PATH": f"{ACCOUNT_HOME}/.bun/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(ACCOUNT_HOME),
            "TMPDIR": "/private/tmp",
            "GBRAIN_SOURCE": SOURCE,
        }

    def _grant_current(self) -> bool:
        if self._source_grant is None:
            return False
        expires_at = _parse_time(self._source_grant.get("expires_at"))
        try:
            now = self.now_provider()
            return expires_at is not None and isinstance(now, datetime) and expires_at > now
        except Exception:
            return False

    def _local_backend_digest(self) -> str | None:
        """Attest and bind a fixed owner-local backend without connecting."""

        lexical = Path(self.gbrain_config_path)
        try:
            resolved = lexical.resolve(strict=True)
            details = resolved.lstat()
            parent = resolved.parent.lstat()
            payload = resolved.read_bytes()
            value = json.loads(payload.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if (
            lexical.is_symlink()
            or lexical.parent.is_symlink()
            or resolved != lexical
            or resolved != DEFAULT_GBRAIN_CONFIG and self.gbrain_config_path == DEFAULT_GBRAIN_CONFIG
            or not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.getuid()
            or parent.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) != 0o600
            or stat.S_IMODE(parent.st_mode) & 0o022
            or not isinstance(value, dict)
        ):
            return None
        engine = value.get("engine")
        if engine == "postgres":
            url_value = value.get("database_url")
            if not isinstance(url_value, str):
                return None
            try:
                parsed = urlparse(url_value)
                port = parsed.port
            except ValueError:
                return None
            database = unquote(parsed.path.lstrip("/"))
            allowed = (
                parsed.scheme in {"postgres", "postgresql"}
                and parsed.hostname in ALLOWED_LOCAL_POSTGRES_HOSTS
                and port in ALLOWED_LOCAL_POSTGRES_PORTS
                and database in ALLOWED_LOCAL_POSTGRES_DATABASES
                and not parsed.params
                and not parsed.query
                and not parsed.fragment
            )
            return hashlib.sha256(payload).hexdigest() if allowed else None
        if engine != "pglite" or value.get("database_url") is not None:
            return None
        database_path = value.get("database_path")
        if not isinstance(database_path, str):
            return None
        lexical_database = Path(database_path).expanduser()
        try:
            resolved_database = lexical_database.resolve(strict=True)
            db_details = resolved_database.lstat()
            resolved_database.relative_to(ACCOUNT_HOME / ".gbrain")
        except (OSError, ValueError):
            return None
        allowed = (
            lexical_database.is_absolute()
            and not lexical_database.is_symlink()
            and resolved_database == lexical_database
            and db_details.st_uid == os.getuid()
            and stat.S_IMODE(db_details.st_mode) & 0o022 == 0
        )
        return hashlib.sha256(payload).hexdigest() if allowed else None

    def _local_backend_allowed(self) -> bool:
        return self._local_backend_digest() is not None

    def bind_trusted_target(
        self,
        target: _TrustedTarget,
        freshness: dict[str, Any],
        source_grant: _TrustedSourceGrant | None,
    ) -> None:
        if not isinstance(target, _TrustedTarget) or target._binding_token is not _TARGET_BINDING_TOKEN:
            raise RetrievalError("live retrieval requires a manifest-attested target")
        if (
            not isinstance(source_grant, _TrustedSourceGrant)
            or source_grant._binding_token is not _SOURCE_GRANT_TOKEN
            or source_grant.get("source") != SOURCE
            or source_grant.get("target_identity") != target["identity"]
        ):
            raise RetrievalError("live retrieval requires an attested source grant")
        as_of = _parse_time(freshness.get("as_of") if isinstance(freshness, dict) else None)
        max_age = freshness.get("max_age_days") if isinstance(freshness, dict) else None
        if as_of is None or not isinstance(max_age, int) or isinstance(max_age, bool) or max_age < 0:
            raise RetrievalError("live retrieval requires validated freshness")
        self._trusted_target = target
        self._source_grant = source_grant
        self._freshness = {"as_of": as_of, "max_age_days": max_age}
        self._attestation = None
        self._attestation_state = "unavailable"
        self._attestation_reason = "source-attestation-not-run"

    @staticmethod
    def _command_allowed(argv: list[str]) -> bool:
        if len(argv) == 2 and argv[1] == "--version":
            return True
        if len(argv) != 4 or argv[1:3] != ["call", "sources_status"]:
            return False
        try:
            payload = json.loads(argv[3])
        except (TypeError, json.JSONDecodeError):
            return False
        return isinstance(payload, dict) and payload == {"id": SOURCE}

    def _receipt(self, state: str, reason_code: str, *, attestation: dict[str, str] | None = None) -> dict[str, Any]:
        bound = attestation or self._attestation
        response = {
            "state": state,
            "results": [],
            "index_version": bound["index_version"] if bound else "unknown",
            "model_version": bound["model_version"] if bound else "unknown",
            "reason_code": reason_code,
            "egress_contract": LIVE_EGRESS_CONTRACT,
            "provider_calls": 0,
        }
        if bound:
            response["source"] = bound["source"]
            response["manifest_digest"] = bound["manifest_digest"]
            response["source_grant_digest"] = bound["source_grant_digest"]
            response["source_freshness_at"] = bound["source_freshness_at"]
        return response

    def _run(self, argv: list[str]) -> tuple[str | None, str]:
        if not self._command_allowed(argv):
            return None, "failed"
        if not self._grant_current():
            return None, "grant-expired"
        bun_executable = _trusted_bun_executable(self.bun_path)
        gbrain_cli = _trusted_gbrain_cli(self.cli_path)
        config_digest = self._local_backend_digest()
        if bun_executable is None or gbrain_cli is None or config_digest is None or not argv or argv[0] != self.cli_path:
            return None, "failed"
        operation = "version" if len(argv) == 2 and argv[1] == "--version" else "sources_status"
        try:
            helper = PINNED_OPERATION_HELPER.resolve(strict=True)
            if helper != PINNED_OPERATION_HELPER or helper.is_symlink() or helper.stat().st_uid != os.getuid():
                return None, "failed"
            environment = self._environment()
            environment["GBRAIN_CLI_PATH"] = gbrain_cli
            environment["GBRAIN_CONFIG_SHA256"] = config_digest
            result = self.runner(
                [bun_executable, "--no-env-file", str(helper)],
                input=canonical_json({"schema_version": 1, "source": SOURCE, "operation": operation}),
                capture_output=True,
                text=True,
                env=environment,
                cwd=str(PINNED_OPERATION_HELPER.parent),
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None, "unavailable"
        if getattr(result, "returncode", 1) != 0:
            return None, "failed"
        stdout = getattr(result, "stdout", None)
        return (stdout, "complete") if isinstance(stdout, str) else (None, "failed")

    def _run_keyword(self, query: str, limit: int) -> tuple[str | None, str]:
        """Run the pinned direct FTS adapter without configuring an AI gateway."""

        if (
            not isinstance(query, str)
            or not query
            or len(query) > 4096
            or not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 140
        ):
            return None, "failed"
        if not self._grant_current():
            return None, "grant-expired"
        bun_executable = _trusted_bun_executable(self.bun_path)
        gbrain_cli = _trusted_gbrain_cli(self.cli_path)
        if bun_executable is None or gbrain_cli is None:
            return None, "failed"
        config_digest = self._local_backend_digest()
        if config_digest is None:
            return None, "backend-rejected"
        try:
            helper = PINNED_OPERATION_HELPER.resolve(strict=True)
            if helper != PINNED_OPERATION_HELPER or helper.is_symlink() or helper.stat().st_uid != os.getuid():
                return None, "failed"
            payload = json.dumps(
                {"schema_version": 1, "source": SOURCE, "operation": "keyword", "query": query, "limit": limit},
                separators=(",", ":"),
                sort_keys=True,
            )
            environment = self._environment()
            environment["GBRAIN_CLI_PATH"] = gbrain_cli
            environment["GBRAIN_CONFIG_SHA256"] = config_digest
            result = self.keyword_runner(
                [bun_executable, "--no-env-file", str(helper)],
                input=payload,
                capture_output=True,
                text=True,
                env=environment,
                cwd=str(PINNED_OPERATION_HELPER.parent),
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None, "unavailable"
        if getattr(result, "returncode", 1) != 0:
            return None, "failed"
        stdout = getattr(result, "stdout", None)
        return (stdout, "complete") if isinstance(stdout, str) else (None, "failed")

    def _version(self) -> tuple[str | None, str]:
        if self.version_provider is not None:
            try:
                output = self.version_provider()
            except Exception:
                return None, "failed"
        else:
            output, state = self._run([self.cli_path, "--version"])
            if output is None:
                return None, state
        match = CLI_VERSION_RE.fullmatch(output.strip()) if isinstance(output, str) else None
        return (match.group(1), "complete") if match else (None, "failed")

    def _attest_source(self) -> tuple[dict[str, str] | None, str, str]:
        if not self.live:
            return None, "unavailable", "live-not-opted-in"
        if self._trusted_target is None or self._source_grant is None or self._freshness is None:
            return None, "unavailable", "trusted-target-unbound"
        if not self._grant_current():
            return None, "failed", "source-grant-expired"
        if not self._local_backend_allowed():
            return None, "failed", "local-backend-rejected"
        if self._attestation is not None:
            return self._attestation, self._attestation_state, self._attestation_reason
        version, version_state = self._version()
        if version is None:
            if version_state == "grant-expired":
                return None, "failed", "source-grant-expired"
            return None, version_state, "cli-version-unavailable" if version_state == "unavailable" else "cli-version-invalid"
        if version not in SUPPORTED_LIVE_CLI_VERSIONS or version not in self._source_grant["allowed_cli_versions"]:
            return None, "failed", "cli-version-unsupported"
        payload = json.dumps({"id": SOURCE}, separators=(",", ":"), sort_keys=True)
        stdout, state = self._run([self.cli_path, "call", "sources_status", payload])
        if stdout is None:
            if state == "grant-expired":
                return None, "failed", "source-grant-expired"
            return None, state, "source-attestation-unavailable" if state == "unavailable" else "source-attestation-failed"
        try:
            status = _parse_cli_json(stdout)
        except RetrievalError:
            return None, "failed", "source-attestation-invalid"
        if not isinstance(status, dict) or status.get("error") or status.get("isError"):
            return None, "failed", "source-attestation-invalid"
        if status.get("id") != SOURCE:
            return None, "failed", "source-mismatch"
        last_commit = status.get("last_commit")
        fresh_at = status.get("last_sync_at")
        page_count = status.get("page_count")
        clone_state = status.get("clone_state")
        if (
            not isinstance(last_commit, str)
            or not SAFE_RECEIPT_RE.fullmatch(last_commit)
            or not isinstance(fresh_at, str)
            or _parse_time(fresh_at) is None
            or not isinstance(page_count, int)
            or isinstance(page_count, bool)
            or page_count < 0
            or not isinstance(status.get("archived"), bool)
            or not isinstance(clone_state, str)
        ):
            return None, "failed", "source-attestation-invalid"
        if status.get("archived") is True:
            return None, "failed", "source-archived"
        if clone_state == "corrupted":
            return None, "failed", "source-corrupted"
        if clone_state not in {"healthy", "not-applicable", "local-attested"}:
            return None, "failed", "source-attestation-invalid"
        parsed_fresh_at = _parse_time(fresh_at)
        assert parsed_fresh_at is not None
        try:
            helper_digest = hashlib.sha256(PINNED_OPERATION_HELPER.read_bytes()).hexdigest()
        except OSError:
            return None, "failed", "keyword-adapter-unavailable"
        attestation = {
            "source": SOURCE,
            "target_identity": self._source_grant["target_identity"],
            "manifest_digest": self._trusted_target["manifest_digest"],
            "source_grant_digest": self._source_grant["grant_digest"],
            "index_version": f"gbrain:{SOURCE}:{last_commit}:pages-{page_count}",
            "model_version": f"gbrain-cli:{version}:stack-keyword:{helper_digest[:16]}",
            "source_freshness_at": parsed_fresh_at.isoformat(),
            "egress_contract": LIVE_EGRESS_CONTRACT,
        }
        as_of = self._freshness["as_of"]
        if parsed_fresh_at > as_of:
            return attestation, "failed", "source-freshness-future"
        if (as_of - parsed_fresh_at).total_seconds() > self._freshness["max_age_days"] * 86400:
            self._attestation = attestation
            self._attestation_state = "partial"
            self._attestation_reason = "source-freshness-stale"
            return attestation, "partial", "source-freshness-stale"
        self._attestation = attestation
        self._attestation_state = "complete"
        self._attestation_reason = ""
        return attestation, "complete", ""

    def campaign_attestation(
        self,
        request: dict[str, Any],
        *,
        target_manifest: Path,
        source_grant: Path,
    ) -> dict[str, Any]:
        """Return a safe source receipt for semantic campaign invalidation."""

        validate_request(request)
        target = validate_target(request, target_manifest)
        grant = validate_source_grant(request, target, source_grant)
        self.bind_trusted_target(target, request["freshness"], grant)
        attestation, state, reason = self._attest_source()
        material = {
            "state": state,
            "reason_code": reason or None,
            "source": SOURCE,
            "target_manifest_digest": target["manifest_digest"],
            "source_grant_digest": grant["grant_digest"],
            "index_version": attestation.get("index_version") if attestation else None,
            "model_version": attestation.get("model_version") if attestation else None,
            "source_freshness_at": attestation.get("source_freshness_at") if attestation else None,
            "egress_contract": LIVE_EGRESS_CONTRACT,
            "provider_calls": 0,
        }
        return {**material, "attestation_digest": digest(material)}

    def text_search(self, query: str, limit: int) -> dict[str, Any]:
        attestation, attestation_state, reason_code = self._attest_source()
        if attestation is None:
            return self._receipt(attestation_state, reason_code)
        if attestation_state == "failed":
            return self._receipt("failed", reason_code, attestation=attestation)
        candidate_runs: list[dict[str, dict[str, Any]]] = []
        for _attempt in range(2):
            stdout, state = self._run_keyword(query, limit)
            if stdout is None:
                reason = (
                    "source-grant-expired" if state == "grant-expired"
                    else "local-backend-rejected" if state == "backend-rejected"
                    else "search-unavailable" if state == "unavailable"
                    else "search-failed"
                )
                return self._receipt("failed" if state in {"grant-expired", "backend-rejected"} else state, reason, attestation=attestation)
            try:
                raw = _parse_cli_json(stdout)
            except RetrievalError:
                return self._receipt("failed", "search-invalid-json", attestation=attestation)
            if isinstance(raw, dict) and (raw.get("error") or raw.get("isError")):
                return self._receipt("failed", "search-error-envelope", attestation=attestation)
            values = raw if isinstance(raw, list) else raw.get("results") if isinstance(raw, dict) else None
            if not isinstance(values, list) or not all(isinstance(value, dict) for value in values):
                return self._receipt("failed", "search-invalid-response", attestation=attestation)
            run_candidates: dict[str, dict[str, Any]] = {}
            for value in values:
                if value.get("source_id") != SOURCE:
                    return self._receipt("failed", "search-source-mismatch", attestation=attestation)
                slug = value.get("slug")
                if isinstance(slug, str) and re.fullmatch(r"[A-Za-z0-9._~/-]+", slug) and not BOOKMARK_SLUG_RE.fullmatch(slug):
                    continue
                if value.get("archived") is True:
                    return self._receipt("failed", "search-result-archived", attestation=attestation)
                if value.get("corrupted") is True:
                    return self._receipt("failed", "search-result-corrupted", attestation=attestation)
                if value.get("unverified") is True:
                    continue
                candidate = _gbrain_candidate(value)
                if candidate is None:
                    return self._receipt("failed", "search-result-invalid", attestation=attestation)
                if not any(str(slug).startswith(scope) for scope in self._source_grant["locator_scopes"]):
                    continue
                candidate["authorized_target_identities"] = [self._source_grant["target_identity"]]
                run_candidates[candidate["candidate_id"]] = candidate
            candidate_runs.append(run_candidates)
        self._attestation = None
        final_attestation, final_state, final_reason = self._attest_source()
        if final_attestation is None or final_state == "failed":
            return self._receipt("failed", final_reason or "source-reattestation-failed", attestation=attestation)
        if final_attestation != attestation:
            return self._receipt("failed", "source-changed-during-search", attestation=final_attestation)
        stable_ids = {
            candidate_id
            for candidate_id in set(candidate_runs[0]).intersection(candidate_runs[1])
            if canonical_json(candidate_runs[0][candidate_id]) == canonical_json(candidate_runs[1][candidate_id])
        }
        candidates = [candidate_runs[0][candidate_id] for candidate_id in sorted(stable_ids)]
        if not candidates:
            return self._receipt("partial" if attestation_state == "partial" else "empty", "search-empty", attestation=attestation)
        return {
            "state": "partial" if attestation_state == "partial" else "complete",
            "results": candidates,
            "index_version": attestation["index_version"],
            "model_version": attestation["model_version"],
            "source_freshness_at": attestation["source_freshness_at"],
            "source_grant_digest": attestation["source_grant_digest"],
            "egress_contract": LIVE_EGRESS_CONTRACT,
            "provider_calls": 0,
            **({"reason_code": reason_code} if reason_code else {}),
        }

    def image_search(self, image: str, query: str, limit: int) -> dict[str, Any]:
        return self._receipt("unavailable", "live-image-disabled")


class FixtureFileTransport:
    def __init__(self, document: dict[str, Any]) -> None:
        values = document.get("candidates", []) if isinstance(document, dict) else []
        self.candidates = [row for value in values if (row := _candidate(value)) is not None]
        self.index_version = str(document.get("index_version", "fixture-index"))
        self.model_version = str(document.get("model_version", "fixture-model"))

    def text_search(self, query: str, limit: int) -> dict[str, Any]:
        terms = _terms(query)
        values = sorted(self.candidates, key=lambda row: (-len(terms & set(row["text_terms"])), row["candidate_id"]))
        return {"state": "complete", "results": values[:limit], "index_version": self.index_version, "model_version": self.model_version}

    def image_search(self, image: str, query: str, limit: int) -> dict[str, Any]:
        terms = _terms(query)
        values = sorted(self.candidates, key=lambda row: (-len(terms & set(row["image_terms"])), row["candidate_id"]))
        return {"state": "complete", "results": values[:limit], "index_version": self.index_version, "model_version": self.model_version + "-image"}


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RetrievalError(f"invalid JSON document: {path.name}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--target-manifest", type=Path, required=True)
    parser.add_argument("--source-grant", type=Path, help="owner-local x-bookmarks retrieval grant required for live mode")
    parser.add_argument("--out", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--candidates", type=Path, help="synthetic or owner-local pinned candidate fixture")
    group.add_argument("--live-gbrain", action="store_true", help="use read-only source-scoped GBrain search")
    args = parser.parse_args(argv)
    if args.live_gbrain and args.source_grant is None:
        parser.error("--live-gbrain requires --source-grant")
    if args.source_grant is not None and not args.live_gbrain:
        parser.error("--source-grant requires --live-gbrain")
    try:
        request = load_owner_request(args.request)
        transport = FixtureFileTransport(load_json(args.candidates)) if args.candidates else CliGBrainTransport(live=args.live_gbrain)
        response = retrieve(
            request,
            target_manifest=args.target_manifest,
            transport=transport,
            source_grant=args.source_grant,
        )
        write_response(args.out, response)
        print(json.dumps({"status": response["status"], "result_count": response["result_count"], "response_digest": response["response_digest"]}, sort_keys=True))
        return 0 if response["status"] != "failed" else 1
    except (RetrievalError, OSError, TypeError, ValueError):
        print("design retrieval failed closed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
