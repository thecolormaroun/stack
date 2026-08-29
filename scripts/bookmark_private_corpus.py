#!/usr/bin/env python3
"""Shared, privacy-preserving primitives for the U15 bookmark corpus.

The module deliberately keeps owner-local values (raw bookmark rows, cursors,
paths, and media payloads) separate from the public projections emitted by the
U15 command-line scripts.  It has no network client and never calls GBrain.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit


SCHEMA_VERSION = 1
ADAPTER_VERSION = "field-theory-allowlist-v1"
IMPORT_TRANSPORT_VERSION = "gbrain-cli-markdown-v1"
SOURCE_ID = "x-bookmarks"
FIELD_THEORY_SOURCE_ID = "field-theory"
SOURCE_SYNC_APPROVAL = "u15-source-sync-approved-v1"
BACKFILL_APPROVAL = "u15-backfill-approved-v1"
IMPORT_APPROVAL = "x-bookmarks-import-approved-v1"
IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,191}$")
SAFE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

# This is the explicit public contract for the Field Theory bookmarks table.
# It is intentionally a fixed allowlist.  A caller may narrow the columns but
# may not make the adapter discover arbitrary tables or columns at runtime.
FIELD_THEORY_TABLE = "bookmarks"
FIELD_THEORY_COLUMNS = (
    "id", "tweet_id", "url", "text", "author_handle", "author_name",
    "author_profile_image_url", "posted_at", "bookmarked_at", "synced_at",
    "conversation_id", "in_reply_to_status_id", "quoted_status_id",
    "language", "like_count", "repost_count", "reply_count", "quote_count",
    "bookmark_count", "view_count", "media_count", "link_count", "links_json",
    "tags_json", "ingested_via", "categories", "primary_category", "github_urls",
    "domains", "primary_domain", "quoted_tweet_json", "article_title",
    "article_text", "article_site", "enriched_at", "folder_ids", "folder_names",
)
FIELD_THEORY_REQUIRED_COLUMNS = ("id", "tweet_id", "url", "synced_at")


class CorpusError(ValueError):
    """A fail-closed source-contract or corpus error."""


def owner_local_path(path: Path, label: str = "owner-local state") -> Path:
    """Resolve an apply-time private path and reject paths inside this repo."""

    resolved = Path(path).expanduser().resolve(strict=False)
    try:
        resolved.relative_to(REPOSITORY_ROOT)
    except ValueError:
        return resolved
    raise CorpusError(f"{label} must be outside the repository checkout")


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> str:
    """Return deterministic UTF-8 JSON used for every content digest."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def canonical_json_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def opaque(prefix: str, value: Any, length: int = 32) -> str:
    return f"{prefix}:{canonical_json_digest(value)[:length]}"


def safe_identifier(value: str, prefix: str = "id") -> str:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
        return opaque(prefix, value)
    return value


def policy_digest(policy: Any) -> str:
    return canonical_json_digest(policy)


def schema_digest(name: str) -> str:
    return canonical_json_digest({"name": name, "schema_version": SCHEMA_VERSION})


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorpusError(f"invalid source document: {path.name}") from exc


def source_from_document(document: Any) -> dict[str, Any]:
    """Select the enabled Field Theory source from the canonical config shape."""

    if isinstance(document, dict) and isinstance(document.get("sources"), list):
        enabled = [
            source
            for source in document["sources"]
            if isinstance(source, dict)
            and source.get("enabled", True)
            and source.get("adapter") == "field_theory"
        ]
        if not enabled:
            raise CorpusError("no enabled field_theory source")
        return enabled[0]
    if not isinstance(document, dict):
        raise CorpusError("source document must be an object")
    return document


def write_public_json(path: Path, payload: Any) -> None:
    """Write a public projection only; callers must have sanitized payload."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _json_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            return [value]
    return [value]


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    host = parts.hostname.lower() if parts.hostname else ""
    if not host or host in {"localhost", "127.0.0.1", "::1"}:
        return None
    return value.strip()


def _media_records(row: dict[str, Any]) -> list[Any]:
    return _json_list(_first(row, "media", "media_items", "media_json"))


def _link_records(row: dict[str, Any]) -> list[Any]:
    return _json_list(_first(row, "links", "links_json"))


def _folder_values(row: dict[str, Any]) -> list[Any]:
    values = _json_list(_first(row, "folder_ids", "folders", "folder_names"))
    if not values and row.get("folder_id") not in (None, ""):
        values = [row["folder_id"]]
    return values


def _revision_value(row: dict[str, Any]) -> Any:
    return _first(row, "revision", "revision_id", "updated_at", "synced_at", "bookmarked_at", "posted_at") or "unknown"


def _observation_disposition(row: dict[str, Any]) -> str:
    raw = row.get("disposition") or row.get("observation_state") or row.get("state")
    if row.get("deleted") is True or (isinstance(raw, str) and raw.lower() == "deleted"):
        return "deleted"
    if isinstance(raw, str) and raw.lower() in {"missing", "unavailable", "pending", "rejected"}:
        return raw.lower()
    return "accepted"


def source_native_value(row: dict[str, Any]) -> str:
    value = _first(row, "tweet_id", "source_native_id", "id", "bookmark_id", "url")
    if value is None:
        raise CorpusError("bookmark row has no stable source identity")
    return str(value)


def canonical_value(row: dict[str, Any]) -> str:
    value = _first(row, "canonical_url", "url", "original_url", "link")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return source_native_value(row)


def _media_projection(row: dict[str, Any]) -> dict[str, Any]:
    records = _media_records(row)
    declared_count = 0
    raw_declared_count = row.get("media_count")
    if isinstance(raw_declared_count, (int, float, str)) and not isinstance(raw_declared_count, bool):
        try:
            declared_count = max(0, int(raw_declared_count))
        except (TypeError, ValueError):
            declared_count = 0
    projected: list[dict[str, Any]] = []
    unavailable = 0
    metadata_only = 0
    missing_fields: set[str] = set()
    total_bytes = 0
    for record in records:
        if isinstance(record, dict):
            unavailable_reason = record.get("unavailable_reason") or record.get("error")
            if unavailable_reason:
                unavailable += 1
            has_mime = bool(record.get("mime_type") or record.get("mime"))
            has_bytes = record.get("bytes") is not None or record.get("byte_count") is not None
            has_digest = isinstance(record.get("digest"), str) and bool(re.fullmatch(r"[a-f0-9]{64}", record["digest"]))
            missing = [field for field, present in (("mime_type", has_mime), ("byte_count", has_bytes), ("digest", has_digest)) if not present]
            if missing and not unavailable_reason:
                metadata_only += 1
                missing_fields.update(missing)
            byte_value = record.get("bytes", record.get("byte_count", 0))
            try:
                byte_count = max(0, int(byte_value or 0))
            except (TypeError, ValueError):
                byte_count = 0
            total_bytes += byte_count
            projected.append({
                "media_id": opaque("media", record.get("id") or record.get("url") or record),
                "mime_type": str(record.get("mime_type") or record.get("mime") or "unknown"),
                "byte_count": byte_count,
                "content_digest": str(record.get("digest")) if isinstance(record.get("digest"), str) and re.fullmatch(r"[a-f0-9]{64}", record["digest"]) else canonical_json_digest(record),
                "status": "unavailable" if unavailable_reason else "resolved",
                "missing_fields": [] if unavailable_reason else missing,
            })
        else:
            metadata_only += 1
            missing_fields.update({"mime_type", "byte_count", "digest"})
            projected.append({
                "media_id": opaque("media", record),
                "mime_type": "unknown",
                "byte_count": 0,
                "content_digest": canonical_json_digest(record),
                "status": "metadata_only",
                "missing_fields": ["mime_type", "byte_count", "digest"],
            })
    aggregate_metadata_only = False
    if not projected and declared_count > 0:
        missing_fields.update({"mime_type", "byte_count", "digest"})
        metadata_only = declared_count
        aggregate_metadata_only = True
        projected = [{
            "media_id": opaque("media", {"declared_count": declared_count}),
            "mime_type": "unknown",
            "byte_count": 0,
            "content_digest": canonical_json_digest({"declared_count": declared_count}),
            "status": "metadata_only",
            "missing_fields": ["mime_type", "byte_count", "digest"],
        }]
    if not projected:
        state = "not_present"
    elif unavailable == len(projected):
        state = "unavailable"
    elif unavailable:
        state = "partial"
    elif metadata_only:
        state = "metadata_only"
    else:
        state = "resolved"
    return {
        "state": state,
        "count": declared_count if aggregate_metadata_only else len(projected),
        "byte_count": total_bytes,
        "items": projected,
        "digest": canonical_json_digest(projected),
        "missing_fields": sorted(missing_fields),
    }


def _link_projection(row: dict[str, Any]) -> dict[str, Any]:
    links = [str(value) for value in _link_records(row) if isinstance(value, (str, int, float))]
    digests = sorted(canonical_json_digest(value) for value in links)
    return {"state": "captured" if links else "not_present", "count": len(links), "digests": digests, "set_digest": canonical_json_digest(sorted(set(digests)))}


def normalize_observation(row: dict[str, Any], source_id: str, snapshot_id: str, captured_at: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (opaque public observation, owner-local raw record)."""

    if not isinstance(row, dict):
        raise CorpusError("bookmark row must be an object")
    native = source_native_value(row)
    canonical = canonical_value(row)
    revision = _revision_value(row)
    media = _media_projection(row)
    links = _link_projection(row)
    folders = sorted({opaque("folder", value, 24) for value in _folder_values(row)})
    capture_time = str(captured_at or _first(row, "synced_at", "captured_at", "updated_at") or now())
    revision_time = str(_first(row, "revision_at", "updated_at", "synced_at", "posted_at") or capture_time)
    source_native_id = opaque("source-native", native)
    canonical_id = opaque("bookmark", canonical)
    revision_digest = canonical_json_digest(revision)
    content_digest = canonical_json_digest(row)
    disposition = _observation_disposition(row)
    source_identity = opaque("source", {"source_id": source_id, "native": native})
    evidence_id = opaque("evidence", {"source": source_identity, "canonical": canonical_id, "revision": revision_digest})
    public = {
        "schema_version": SCHEMA_VERSION,
        "evidence_id": evidence_id,
        "source_id": safe_identifier(source_id, "source"),
        "source_identity": source_identity,
        "original_source_identity": source_native_id,
        "canonical_source_identity": canonical_id,
        "capture_time": capture_time,
        "revision_time": revision_time,
        "revision_digest": revision_digest,
        "content_digest": content_digest,
        "media": {key: value for key, value in media.items() if key != "items"},
        "media_item_digests": [item["content_digest"] for item in media["items"]],
        "media_item_states": [item["status"] for item in media["items"]],
        "link_capture": links,
        "folder_ids": folders,
        "completeness_state": disposition,
        "adapter_version": ADAPTER_VERSION,
        "derivation": {
            "was_derived_from": [source_identity],
            "was_generated_by": opaque("activity", {"adapter": ADAPTER_VERSION, "snapshot": snapshot_id}),
            "lineage_digest": canonical_json_digest({"source": source_identity, "content": content_digest, "revision": revision_digest}),
        },
    }
    raw = {
        "source_id": source_id,
        "source_native_value": native,
        "canonical_value": canonical,
        "row": row,
        "public": public,
        "media": media,
        "links": links,
        "revision": revision,
    }
    return public, raw


def _source_contract(source: dict[str, Any]) -> dict[str, Any]:
    contract = source.get("field_theory_contract") or source.get("sqlite") or source
    table = contract.get("table", source.get("table", FIELD_THEORY_TABLE))
    columns = contract.get("columns", source.get("columns", list(FIELD_THEORY_COLUMNS)))
    media_roots = contract.get("media_roots", source.get("media_roots", []))
    if table != FIELD_THEORY_TABLE:
        raise CorpusError("field_theory table is not allowlisted")
    if not isinstance(columns, list) or not columns:
        raise CorpusError("field_theory columns must be an explicit allowlist")
    if any(not isinstance(column, str) or column not in FIELD_THEORY_COLUMNS for column in columns):
        raise CorpusError("field_theory column is not allowlisted")
    if not set(FIELD_THEORY_REQUIRED_COLUMNS) <= set(columns):
        raise CorpusError("field_theory allowlist omits a required column")
    if not isinstance(media_roots, list) or any(not isinstance(root, str) or not root.strip() for root in media_roots):
        raise CorpusError("field_theory media_roots must be an explicit allowlist")
    return {"table": table, "columns": list(columns), "media_roots": list(media_roots)}


def field_theory_contract(source: dict[str, Any]) -> dict[str, Any]:
    return _source_contract(source)


def _quoted_identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise CorpusError("invalid SQLite identifier")
    return '"' + value.replace('"', '""') + '"'


def _sqlite_pages(path: Path, source: dict[str, Any]) -> list[dict[str, Any]]:
    contract = _source_contract(source)
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except (OSError, sqlite3.Error) as exc:
        raise CorpusError("field_theory source unavailable") from exc
    try:
        select = ", ".join(_quoted_identifier(column) for column in contract["columns"])
        query = f"SELECT {select} FROM {_quoted_identifier(contract['table'])} ORDER BY {_quoted_identifier('id')}"
        rows = [dict(zip(contract["columns"], values)) for values in connection.execute(query)]
    except sqlite3.Error as exc:
        raise CorpusError("field_theory allowlisted query failed") from exc
    finally:
        connection.close()
    return [{"page_ordinal": 0, "requested_cursor": None, "returned_cursor": None, "rows": rows}]


def load_source_pages(source: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load fixture pages or the exact allowlisted Field Theory SQLite table."""

    if not isinstance(source, dict):
        raise CorpusError("source document must be an object")
    if source.get("pages") is not None:
        pages = source["pages"]
        if not isinstance(pages, list):
            raise CorpusError("source pages must be an array")
        contract = _source_contract(source)
        return pages, contract
    if "items" in source:
        contract = _source_contract(source)
        return [{"page_ordinal": 0, "requested_cursor": None, "returned_cursor": None, "rows": source.get("items", [])}], contract
    paths = source.get("paths") or ([source["path"]] if source.get("path") else [])
    if not paths:
        raise CorpusError("field_theory source has no fixture pages or owner-local path")
    if len(paths) != 1:
        raise CorpusError("field_theory requires one explicitly configured source path")
    path = Path(str(paths[0])).expanduser()
    if path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
        return _sqlite_pages(path, source), _source_contract(source)
    contract = _source_contract(source)
    try:
        if path.suffix.lower() == ".jsonl":
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        else:
            value = read_json(path)
            if isinstance(value, dict) and "pages" in value:
                return list(value["pages"]), _source_contract(value)
            rows = value if isinstance(value, list) else [value]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorpusError("field_theory source unavailable") from exc
    return [{"page_ordinal": 0, "requested_cursor": None, "returned_cursor": None, "rows": rows}], contract


def _cursor_digest(cursor: Any) -> str | None:
    return None if cursor in (None, "") else canonical_json_digest(cursor)


def _page_receipt(page: dict[str, Any], source_id: str, source_identity: str, query_contract_digest: str, snapshot_id: str, policy: str, status: str, canonical_ids: list[str], raw_response_digest: str, retry: dict[str, Any], media_state: str, link_state: str) -> dict[str, Any]:
    requested = page.get("requested_cursor")
    returned = page.get("returned_cursor")
    return {
        "schema_version": SCHEMA_VERSION,
        "receipt_id": opaque("page", {"source": source_id, "snapshot": snapshot_id, "ordinal": page.get("page_ordinal", 0)}),
        "source_id": safe_identifier(source_id, "source"),
        "source_identity": source_identity,
        "query_contract_digest": query_contract_digest,
        "page_ordinal": int(page.get("page_ordinal", 0)),
        "requested_cursor_digest": _cursor_digest(requested),
        "returned_cursor_digest": _cursor_digest(returned),
        "canonical_ids": sorted(canonical_ids),
        "canonical_id_set_digest": canonical_json_digest(sorted(set(canonical_ids))),
        "raw_response_digest": raw_response_digest,
        "row_count": len(page.get("rows", [])) if isinstance(page.get("rows", []), list) else 0,
        "retry": retry,
        "media_resolution": {"state": media_state},
        "link_capture": {"state": link_state},
        "adapter_version": ADAPTER_VERSION,
        "policy_digest": policy,
        "schema_digest": schema_digest("source-page-receipt"),
        "status": status,
    }


def _safe_failure(reason: str, page_ordinal: int | None = None, status: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"reason": reason}
    if page_ordinal is not None:
        result["page_ordinal"] = page_ordinal
    if status is not None:
        result["status"] = status
    return result


def reconcile_pages(source: dict[str, Any], policy: Any, parity: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pages, contract = load_source_pages(source)
    source_id = str(source.get("source_id") or FIELD_THEORY_SOURCE_ID)
    source_input_digest = canonical_json_digest(source)
    snapshot_id = opaque("snapshot", {"source": source_id, "input": source_input_digest, "policy": policy_digest(policy)})
    p_digest = policy_digest(policy)
    source_identity = opaque("source", source_id)
    query_contract_digest = canonical_json_digest({"adapter": ADAPTER_VERSION, "table": contract["table"], "columns": sorted(contract["columns"]), "media_roots": canonical_json_digest(contract["media_roots"])})
    observations: list[dict[str, Any]] = []
    raw_records: list[dict[str, Any]] = []
    page_receipts: list[dict[str, Any]] = []
    seen_requested_cursors: set[str] = set()
    seen_returned_cursors: set[str] = set()
    seen_observation_keys: set[tuple[str, str]] = set()
    duplicate_count = 0
    failure: dict[str, Any] | None = None
    expected_cursor: Any = None
    cursor_exhausted = False
    folder_states: list[str] = []
    revision_states: list[str] = []
    media_states: list[str] = []
    link_states: list[str] = []

    for position, raw_page in enumerate(pages):
        if not isinstance(raw_page, dict):
            failure = _safe_failure("invalid_page", position)
            break
        page = dict(raw_page)
        ordinal = int(page.get("page_ordinal", position))
        requested = page.get("requested_cursor")
        if requested != expected_cursor and position > 0 and failure is None:
            failure = _safe_failure("cursor_gap", ordinal)
        if requested not in (None, ""):
            cursor_key = canonical_json(requested)
            if cursor_key in seen_requested_cursors and failure is None:
                failure = _safe_failure("cursor_cycle", ordinal)
            seen_requested_cursors.add(cursor_key)
        page_error = page.get("error")
        if page_error:
            status_code = page_error.get("status") if isinstance(page_error, dict) else None
            reason = "rate_limited" if status_code == 429 else "source_error"
            retry = {"status": "rate_limited" if status_code == 429 else "failed", "attempts": int(page_error.get("attempts", 1)) if isinstance(page_error, dict) else 1}
            page_receipts.append(_page_receipt(page, source_id, source_identity, query_contract_digest, snapshot_id, p_digest, "partial", [], canonical_json_digest(page), retry, "unknown", "unknown"))
            if failure is None:
                failure = _safe_failure(reason, ordinal, status_code if isinstance(status_code, int) else None)
            expected_cursor = requested
            break
        rows = page.get("rows", [])
        if not isinstance(rows, list):
            failure = _safe_failure("invalid_rows", ordinal)
            break
        page_ids: list[str] = []
        page_media: list[str] = []
        page_links: list[str] = []
        for row in rows:
            public, raw = normalize_observation(row, source_id, snapshot_id)
            key = (public["canonical_source_identity"], public["revision_digest"])
            if key in seen_observation_keys:
                duplicate_count += 1
                continue
            if any(existing["canonical_source_identity"] == public["canonical_source_identity"] for existing in observations):
                public["completeness_state"] = "revised"
            seen_observation_keys.add(key)
            observations.append(public)
            raw_records.append(raw)
            page_ids.append(public["canonical_source_identity"])
            page_media.append(raw["media"]["state"])
            page_links.append(raw["links"]["state"])
            folder_states.append("covered" if public["folder_ids"] else "empty")
            revision_states.append("covered" if public["revision_digest"] else "missing")
            media_states.append(raw["media"]["state"])
            link_states.append(raw["links"]["state"])
        returned = page.get("returned_cursor")
        if returned not in (None, ""):
            returned_key = canonical_json(returned)
            if returned_key in seen_returned_cursors and failure is None:
                failure = _safe_failure("cursor_cycle", ordinal)
            seen_returned_cursors.add(returned_key)
        expected_cursor = returned
        if returned in (None, ""):
            cursor_exhausted = True
        page_receipts.append(_page_receipt(
            page, source_id, source_identity, query_contract_digest, snapshot_id, p_digest, "complete" if failure is None else "partial",
            page_ids, canonical_json_digest(page),
            {"status": "none", "attempts": 1},
            "complete" if all(state in {"resolved", "not_present"} for state in page_media) else "partial",
            "complete" if all(state in {"captured", "not_present"} for state in page_links) else "partial",
        ))
        if failure is not None or cursor_exhausted:
            break

    if pages and not cursor_exhausted and failure is None:
        failure = _safe_failure("cursor_not_exhausted", len(page_receipts) - 1)
    if not pages:
        cursor_exhausted = True
    if failure is not None and failure.get("reason") == "cursor_cycle":
        resume_cursor = pages[int(failure.get("page_ordinal", 0))].get("requested_cursor") if pages else expected_cursor
    else:
        resume_cursor = expected_cursor
    completeness = "complete" if cursor_exhausted and failure is None else ("partial" if failure else "unknown")
    folder_columns_available = "folder_ids" in contract["columns"] or "folder_names" in contract["columns"]
    revision_columns_available = "synced_at" in contract["columns"] or "bookmarked_at" in contract["columns"]
    media_columns_available = "media_count" in contract["columns"] or "media_json" in contract["columns"]
    link_columns_available = "link_count" in contract["columns"] or "links_json" in contract["columns"]
    if folder_columns_available and (not folder_states or all(value in {"covered", "empty"} for value in folder_states)):
        folder_state = "complete"
    elif folder_states:
        folder_state = "partial"
    else:
        folder_state = "unknown"
    if revision_columns_available and (not revision_states or all(value == "covered" for value in revision_states)):
        revision_state = "complete"
    elif revision_states:
        revision_state = "partial"
    else:
        revision_state = "unknown"
    if media_columns_available and (not media_states or all(value in {"resolved", "not_present"} for value in media_states)):
        media_state = "complete"
    elif media_states:
        media_state = "partial"
    else:
        media_state = "unknown"
    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_id": snapshot_id,
        "source_id": safe_identifier(source_id, "source"),
        "source_identity": opaque("source", source_id),
        "source_contract": {
            "adapter": "field_theory",
            "adapter_version": ADAPTER_VERSION,
            "table": contract["table"],
            "columns": sorted(contract["columns"]),
            "media_roots": {"count": len(contract["media_roots"]), "digest": canonical_json_digest(contract["media_roots"])},
        },
        "capture_time": now(),
        "policy_digest": p_digest,
        "schema_digest": schema_digest("source-snapshot"),
        "page_count": len(page_receipts),
        "page_receipts": page_receipts,
        "observation_count": len(observations),
        "duplicate_count": duplicate_count,
        "observations": observations,
        "cursor_exhausted": cursor_exhausted,
        "resume_cursor_digest": _cursor_digest(resume_cursor),
        "folder_coverage": {"state": folder_state, "set_digest": canonical_json_digest(sorted({folder for observation in observations for folder in observation["folder_ids"]}))},
        "revision_coverage": {"state": revision_state, "set_digest": canonical_json_digest(sorted(observation["revision_digest"] for observation in observations))},
        "media_coverage": {"state": media_state, "set_digest": canonical_json_digest(sorted(observation["content_digest"] for observation in observations))},
        "link_coverage": {"state": "complete" if link_columns_available and (not link_states or all(value in {"captured", "not_present"} for value in link_states)) else ("partial" if link_states else "unknown")},
        "set_digest": canonical_json_digest(sorted(observation["canonical_source_identity"] for observation in observations)),
        "completeness_state": completeness,
        "dispositions": {
            "accepted": sorted(observation["canonical_source_identity"] for observation in observations if observation["completeness_state"] == "accepted"),
            "revised": sorted(observation["canonical_source_identity"] for observation in observations if observation["completeness_state"] == "revised"),
            "deleted": sorted(observation["canonical_source_identity"] for observation in observations if observation["completeness_state"] == "deleted"),
            "missing": sorted(observation["canonical_source_identity"] for observation in observations if observation["completeness_state"] == "missing"),
            "unavailable_media": sorted(observation["canonical_source_identity"] for observation in observations if observation["media"]["state"] in {"unavailable", "partial", "metadata_only"}),
        },
        "zero_delta": {"state": "not_run"},
        "failure": failure,
        "parity": {"state": "not_configured"},
    }
    if parity is not None:
        snapshot["parity"] = compare_source_sets(observations, parity.get("observations", parity if isinstance(parity, list) else []))
    return snapshot, raw_records


def compare_source_sets(left: Iterable[dict[str, Any]], right: Iterable[dict[str, Any]]) -> dict[str, Any]:
    def public_identity(row: dict[str, Any]) -> tuple[str, str, str]:
        if "canonical_source_identity" in row:
            folders = row.get("folder_ids", []) if isinstance(row.get("folder_ids", []), list) else []
            return row["canonical_source_identity"], row.get("revision_digest", ""), canonical_json_digest(sorted(str(folder) for folder in folders))
        canonical = canonical_value(row)
        revision = _revision_value(row)
        folders = _folder_values(row)
        return opaque("bookmark", canonical), canonical_json_digest(revision), canonical_json_digest(sorted(opaque("folder", value, 24) for value in folders))

    left_rows = {public_identity(row)[0]: row for row in left}
    right_rows = {public_identity(row)[0]: row for row in right}
    left_items = {identity: public_identity(row)[1:] for identity, row in left_rows.items()}
    right_items = {identity: public_identity(row)[1:] for identity, row in right_rows.items()}
    missing = sorted(set(left_items) - set(right_items))
    extra = sorted(set(right_items) - set(left_items))
    revised = sorted(identity for identity in set(left_items) & set(right_items) if left_items[identity][0] != right_items[identity][0])
    folder_membership_diffs = sorted(
        [{"canonical_id": identity, "left_set_digest": left_items[identity][1], "right_set_digest": right_items[identity][1]}
        for identity in set(left_items) & set(right_items)
        if left_items[identity][1] != right_items[identity][1]
        ], key=lambda item: item["canonical_id"]
    )
    deleted = sorted(
        identity for identity, row in {**left_rows, **right_rows}.items()
        if _observation_disposition(row) == "deleted" or row.get("completeness_state") == "deleted"
    )
    explicit_missing = sorted(
        identity for identity, row in {**left_rows, **right_rows}.items()
        if _observation_disposition(row) == "missing" or row.get("completeness_state") == "missing"
    )
    unavailable_media = sorted(
        identity for identity, row in {**left_rows, **right_rows}.items()
        if (isinstance(row.get("media"), dict) and row["media"].get("state") in {"unavailable", "partial", "metadata_only"})
        or ("media" not in row and _media_projection(row).get("state") in {"unavailable", "partial", "metadata_only"})
    )
    return {
        "state": "match" if not missing and not extra and not revised and not folder_membership_diffs else "diff",
        "missing": missing,
        "extra": extra,
        "revised": revised,
        "folder_membership_diffs": folder_membership_diffs,
        "dispositions": {"deleted": deleted, "missing": sorted(set(missing) | set(explicit_missing)), "unavailable_media": unavailable_media},
        "left_count": len(left_items),
        "right_count": len(right_items),
        "set_digest": canonical_json_digest({"left": sorted(left_items), "right": sorted(right_items)}),
    }


def store_owner_records(ledger_path: Path, records: Iterable[dict[str, Any]]) -> int:
    ledger_path = owner_local_path(ledger_path, "raw bookmark ledger")
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(ledger_path.parent, 0o700)
    connection = sqlite3.connect(ledger_path)
    try:
        os.chmod(ledger_path, 0o600)
        connection.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS source_observations (
          evidence_id TEXT PRIMARY KEY,
          source_id TEXT NOT NULL,
          canonical_id TEXT NOT NULL,
          revision_digest TEXT NOT NULL,
          content_digest TEXT NOT NULL,
          raw_json TEXT NOT NULL,
          public_json TEXT NOT NULL,
          stored_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS source_observations_canonical ON source_observations(canonical_id);
        """)
        added = 0
        with connection:
            for record in records:
                public = record["public"]
                before = connection.total_changes
                connection.execute(
                    "INSERT OR IGNORE INTO source_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        public["evidence_id"], public["source_id"], public["canonical_source_identity"],
                        public["revision_digest"], public["content_digest"], canonical_json(record["row"]),
                        canonical_json(public), now(),
                    ),
                )
                if connection.total_changes > before:
                    added += 1
        return added
    finally:
        connection.close()


def load_owner_rows(ledger_path: Path, evidence_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    ledger_path = owner_local_path(ledger_path, "raw bookmark ledger")
    if not ledger_path.exists():
        return {}
    connection = sqlite3.connect(f"file:{ledger_path.expanduser()}?mode=ro", uri=True)
    try:
        values = list(dict.fromkeys(evidence_ids))
        if not values:
            return {}
        placeholders = ",".join("?" for _ in values)
        rows = connection.execute(
            f"SELECT evidence_id, raw_json FROM source_observations WHERE evidence_id IN ({placeholders})", values
        )
        return {evidence_id: json.loads(raw_json) for evidence_id, raw_json in rows}
    except sqlite3.Error:
        return {}
    finally:
        connection.close()


def atomic_owner_json(path: Path, payload: Any) -> None:
    path = owner_local_path(path, "owner-local checkpoint")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_optional_x_api(config: dict[str, Any] | None, *, approved: bool = False, spend_approved: bool = False) -> dict[str, Any]:
    """Validate an optional parity contract without touching the network."""

    config = config or {"enabled": False}
    enabled = bool(config.get("enabled", False))
    credential_names = {"token", "accesstoken", "refreshtoken", "clientsecret", "apikey", "bearer", "bearertoken", "authorization", "authtoken"}
    def is_plaintext_credential_key(key: Any) -> bool:
        if not isinstance(key, str) or key == "os_secret_ref":
            return False
        normalized = re.sub(r"[^a-z]", "", key.lower())
        return normalized in credential_names or normalized.endswith("token") or normalized.startswith("token") or normalized.startswith("bearer")
    def contains_plaintext_credential_key(value: Any) -> bool:
        if isinstance(value, dict):
            return any(is_plaintext_credential_key(key) or contains_plaintext_credential_key(child) for key, child in value.items())
        if isinstance(value, list):
            return any(contains_plaintext_credential_key(child) for child in value)
        return False
    if contains_plaintext_credential_key(config):
        raise CorpusError("optional X parity rejects plaintext credentials")
    if not enabled:
        return {"state": "disabled", "network": "not_attempted"}
    secret_ref = config.get("os_secret_ref")
    scopes = config.get("scopes")
    rotation = config.get("rotation")
    if not isinstance(secret_ref, str) or not re.fullmatch(r"os-secret:[a-z0-9][a-z0-9-]{1,80}", secret_ref):
        raise CorpusError("optional X parity requires an OS-secret reference")
    if scopes != ["bookmark.read"]:
        raise CorpusError("optional X parity requires the least read scope")
    if not isinstance(rotation, dict) or not rotation.get("rotation_id") or not rotation.get("revocation_state"):
        raise CorpusError("optional X parity requires rotation and revocation metadata")
    if not approved or not spend_approved:
        return {"state": "not_approved", "network": "not_attempted"}
    return {
        "state": "approved_contract",
        "network": "not_attempted",
        "scope_digest": canonical_json_digest(scopes),
        "rotation_metadata_digest": canonical_json_digest({
            "rotation_id": str(rotation["rotation_id"]),
            "revocation_state": str(rotation["revocation_state"]),
        }),
    }
