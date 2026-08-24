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
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
SOURCE = "x-bookmarks"
SCHEMA_VERSION = 1
RRF_K = 60
REQUEST_FIELDS = {"schema_version", "request_id", "source", "target", "context", "filters", "freshness", "top_k"}
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
TERM_RE = re.compile(r"[a-z][a-z0-9-]{1,63}")


class RetrievalError(ValueError):
    """A fail-closed authorization, request, transport, or response error."""


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


def validate_target(request: dict[str, Any], manifest_path: Path) -> dict[str, str]:
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
    return {"name": name, "identity": identity, "manifest_digest": manifest_digest}


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
    terms = sorted(_terms(values))
    filters = request.get("filters", {})
    exact_values = [str(filters[key]) for key in ("evidence_id", "author", "date", "folder", "url") if filters.get(key)]
    if not terms and not exact_values:
        raise RetrievalError("request context has no searchable terms")
    return " ".join(exact_values + terms[:64])[:4096]


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
    if targets is not None and (
        not isinstance(targets, list)
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
        "authorized_target_identities": list(targets) if isinstance(targets, list) else None,
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


def _result_age(candidate: dict[str, Any], as_of: datetime) -> int | None:
    indexed = _parse_time(candidate.get("indexed_at"))
    if indexed is None:
        return None
    return max(0, int((as_of - indexed).total_seconds() // 86400))


def retrieve(
    request: dict[str, Any], *, target_manifest: Path, transport: Any,
) -> dict[str, Any]:
    validate_request(request)
    target = validate_target(request, target_manifest)
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
            if targets is not None and target["identity"] not in targets:
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
    max_age = request["freshness"]["max_age_days"]
    for rank, (score, candidate, reasons) in enumerate(scored[:top_k], start=1):
        age = _result_age(candidate, as_of)
        stale = age is None or age > max_age
        stale_count += int(stale)
        results.append({
            "rank": rank,
            "candidate_id": candidate["candidate_id"],
            "evidence_id": candidate["evidence_id"],
            "source": SOURCE,
            "media_identity": candidate["media_identity"],
            "citation_locator": candidate["citation_locator"],
            "similarity_score": round(score, 12),
            "similarity_reasons": reasons or ["source-scoped-retrieval"],
            "uncertainty": "Index date is unavailable." if age is None else ("Result exceeds the requested freshness window." if stale else "Ranking is deterministic for the pinned request and index response."),
            "media_state": candidate["media_state"],
            "freshness_age_days": age,
            "stale": stale,
        })
    valid_text_states = {"complete", "partial", "unavailable", "failed"}
    valid_image_states = {"complete", "partial", "not_requested", "unavailable", "failed"}
    text_state = str(text_response.get("state", "failed"))
    image_state = str(image_response.get("state", "not_requested"))
    if text_state not in valid_text_states:
        text_state = "failed"
    if image_state not in valid_image_states:
        image_state = "failed"
    missing_modalities: list[str] = []
    degradations: list[str] = []
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
    if results and len(results) < 3:
        degradations.append("sparse-results")
    if text_state in {"failed", "unavailable"} and not results:
        status = "failed"
    elif not results:
        status = "empty"
    elif degradations or text_state not in {"complete", "partial"}:
        status = "degraded"
    else:
        status = "complete"
    index_versions = sorted({str(value) for value in (text_response.get("index_version"), image_response.get("index_version")) if value})
    model_versions = sorted({str(value) for value in (text_response.get("model_version"), image_response.get("model_version")) if value})
    response: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "response_id": opaque("response", {"request": request, "target_manifest_digest": target["manifest_digest"], "results": [row["candidate_id"] for row in results]}),
        "request_id": request["request_id"],
        "request_digest": digest(request),
        "status": status,
        "source": SOURCE,
        "target": target,
        "results": results,
        "result_count": len(results),
        "missing_modalities": missing_modalities,
        "degradations": sorted(set(degradations)),
        "index": {
            "versions": index_versions or ["unknown"],
            "model_versions": model_versions or ["unknown"],
            "freshness_as_of": request["freshness"]["as_of"],
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
            "source_scope_enforced": True,
            "configuration_changed": False,
            "reindex_attempted": False,
            "paid_fallback_attempted": False,
            "external_write_attempted": False,
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
    for match in re.finditer(r"(?m)^[\[{]", stdout):
        try:
            return json.loads(stdout[match.start():])
        except json.JSONDecodeError:
            continue
    raise RetrievalError("GBrain returned no valid JSON payload")


def _gbrain_candidate(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("source_id") != SOURCE:
        return None
    slug = value.get("slug")
    if not isinstance(slug, str) or not re.fullmatch(r"[A-Za-z0-9._~/-]+", slug):
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
    modality = str(value.get("modality", "")).lower()
    has_media = modality in {"image", "multimodal"} or bool(value.get("image_path") or value.get("image_url"))
    return {
        "candidate_id": opaque("candidate", {"source": SOURCE, "slug": slug, "chunk_id": value.get("chunk_id")}),
        "evidence_id": opaque("evidence", source_identity),
        "source": SOURCE,
        "citation_locator": f"gbrain:{SOURCE}/{slug}",
        "media_identity": opaque("media", {"slug": slug, "chunk_id": value.get("chunk_id")}) if has_media else None,
        "text_terms": sorted(_terms(text)),
        "image_terms": sorted(_terms(value.get("ocr_text", ""))),
        "metadata": metadata,
        "indexed_at": value.get("effective_date"),
        "media_state": "resolved" if has_media else "unknown",
        "transport_score": value.get("score", 0.0),
    }


class CliGBrainTransport:
    """Read-only adapter for the installed GBrain call surface."""

    def __init__(self, cli_path: str | None = None, runner: Callable[..., Any] | None = None) -> None:
        self.cli_path = cli_path or os.environ.get("GBRAIN_CLI", os.path.expanduser("~/.bun/bin/gbrain"))
        self.runner = runner or subprocess.run

    def _call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(arguments, separators=(",", ":"), sort_keys=True)
        argv = [self.cli_path, "call", tool, payload]
        environment = os.environ.copy()
        environment["GBRAIN_SOURCE"] = SOURCE
        try:
            result = self.runner(argv, capture_output=True, text=True, env=environment, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return {"state": "unavailable", "results": [], "index_version": "gbrain-cli", "model_version": "unknown"}
        if result.returncode != 0:
            return {"state": "failed", "results": [], "index_version": "gbrain-cli", "model_version": "unknown"}
        try:
            raw = _parse_cli_json(result.stdout if isinstance(result.stdout, str) else "")
        except RetrievalError:
            return {"state": "failed", "results": [], "index_version": "gbrain-cli", "model_version": "unknown"}
        values = raw if isinstance(raw, list) else raw.get("results", []) if isinstance(raw, dict) else []
        candidates = [candidate for value in values if (candidate := _gbrain_candidate(value)) is not None]
        return {"state": "complete", "results": candidates, "index_version": "gbrain-cli", "model_version": "gbrain-search"}

    def text_search(self, query: str, limit: int) -> dict[str, Any]:
        return self._call("search", {"query": query, "limit": limit})

    def image_search(self, image: str, query: str, limit: int) -> dict[str, Any]:
        path = Path(image).expanduser().resolve(strict=False)
        if not path.is_file():
            return {"state": "unavailable", "results": [], "index_version": "gbrain-cli", "model_version": "gbrain-image"}
        return self._call("search_by_image", {"image_path": str(path), "limit": limit, "query": query, "source_id": SOURCE})


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
    parser.add_argument("--out", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--candidates", type=Path, help="synthetic or owner-local pinned candidate fixture")
    group.add_argument("--live-gbrain", action="store_true", help="use read-only source-scoped GBrain search")
    parser.add_argument("--cli", help="explicit GBrain executable for live mode")
    args = parser.parse_args(argv)
    try:
        request = load_owner_request(args.request)
        transport = FixtureFileTransport(load_json(args.candidates)) if args.candidates else CliGBrainTransport(args.cli)
        response = retrieve(request, target_manifest=args.target_manifest, transport=transport)
        write_response(args.out, response)
        print(json.dumps({"status": response["status"], "result_count": response["result_count"], "response_digest": response["response_digest"]}, sort_keys=True))
        return 0 if response["status"] != "failed" else 1
    except (RetrievalError, OSError, TypeError, ValueError) as exc:
        print(f"design retrieval failed closed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
