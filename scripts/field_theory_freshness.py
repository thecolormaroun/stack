#!/usr/bin/env python3
"""Read-only Field Theory freshness and database-binding preflight.

The Field Theory maintenance owner publishes one small, owner-local JSON
projection at ``~/.local/state/field-theory/refresh/``.  The expected
``field-theory-refresh-receipt/v1`` keys are:

``schema``, ``run_id``, ``generated_at``, ``outcome``, ``authoritative``,
``deterministic_checks_passed``, ``source``, ``database_binding``,
``state_binding_before``, ``state_binding_after``, ``media``, ``stages``,
``stage_contract``, and ``safe_restart``.
``database_binding`` must contain ``row_count``, ``max_source_timestamp``,
``identity_revision_sha256``, ``table``, ``identity_column``, and
``revision_column``.  The verifier reads only ``tweet_id`` and ``synced_at``
from the allowlisted ``bookmarks`` table; it never reads bookmark bodies.

This module is deliberately read-only.  It does not create directories,
rewrite receipts, mutate SQLite, import data, or call GBrain.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import re
import sqlite3
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


MAX_AGE_SECONDS = 36 * 60 * 60
RECEIPT_SCHEMA = "field-theory-refresh-receipt/v1"
DEFAULT_RECEIPT_RELATIVE = Path(
    ".local/state/field-theory/refresh/field-theory-refresh-receipt.json"
)
RECEIPT_REQUIRED_KEYS = frozenset(
    {
        "schema",
        "run_id",
        "generated_at",
        "outcome",
        "authoritative",
        "deterministic_checks_passed",
        "source",
        "database_binding",
        "state_binding_before",
        "state_binding_after",
        "media",
        "stages",
        "stage_contract",
        "safe_restart",
    }
)
BINDING_REQUIRED_KEYS = frozenset(
    {
        "row_count",
        "max_source_timestamp",
        "identity_revision_sha256",
        "table",
        "identity_column",
        "revision_column",
    }
)
ACCEPTED_OUTCOMES = frozenset(
    {"applied_verified", "applied_verified_with_deferred_llm"}
)
DIGEST_RE = re.compile(r"^[a-f0-9]{64}$")
FIELD_THEORY_TABLE = "bookmarks"
IDENTITY_COLUMN = "tweet_id"
REVISION_COLUMN = "synced_at"


def _allowed_system_alias(path: Path) -> bool:
    """Allow macOS's stable /private aliases, but no user path aliases."""

    expected = {
        Path("/tmp"): Path("/private/tmp"),
        Path("/var"): Path("/private/var"),
        Path("/etc"): Path("/private/etc"),
    }.get(path)
    return expected is not None and Path(os.path.realpath(path)) == expected


def owner_home() -> Path:
    """Return the current account's home without trusting ``$HOME``."""

    return Path(pwd.getpwuid(os.getuid()).pw_dir).absolute()


def default_receipt_path() -> Path:
    return owner_home() / DEFAULT_RECEIPT_RELATIVE


def _owner_expand(value: str) -> Path:
    """Expand only the documented tilde form against the passwd home."""

    if value == "~":
        return owner_home()
    if value.startswith("~/"):
        return owner_home() / value[2:]
    return Path(value)


def _failure(reason: str) -> dict[str, Any]:
    # Failure output intentionally contains only a stable reason class.  In
    # particular, it never includes a source path or receipt contents.
    return {"ok": False, "reason": reason}


def _success(*, age_seconds: int, binding: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "reason": "fresh_bound",
        "age_seconds": age_seconds,
        "database_binding": dict(binding),
    }


def _normalize_sqlite_value(value: Any) -> str:
    """Normalize one allowlisted SQLite value to the shared string form."""

    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def canonical_identity_revision_digest(rows: list[tuple[str, str]]) -> str:
    """Hash the shared tuple-list representation used by Hermes and Stack."""

    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_database_binding(database_path: Path) -> dict[str, Any]:
    """Read only the identity/revision projection from the Field Theory DB."""

    path = _owner_expand(str(database_path)).absolute()
    try:
        details = path.lstat()
    except OSError as exc:
        raise ValueError("database_unavailable") from exc
    if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid():
        raise ValueError("database_path_invalid")

    # URI quoting prevents a local filename from changing the SQLite mode or
    # attaching another database.  mode=ro is the only supported mode here.
    from urllib.parse import quote

    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except (OSError, sqlite3.Error) as exc:
        raise ValueError("database_unavailable") from exc
    try:
        try:
            rows = connection.execute(
                'SELECT "tweet_id", "synced_at" FROM "bookmarks" '
                'ORDER BY "tweet_id"'
            ).fetchall()
        except sqlite3.Error as exc:
            raise ValueError("database_contract_invalid") from exc
    finally:
        connection.close()

    normalized = [
        (_normalize_sqlite_value(identity), _normalize_sqlite_value(revision))
        for identity, revision in rows
    ]
    max_timestamp = max((revision for _, revision in normalized), default="")
    return {
        "row_count": len(normalized),
        "max_source_timestamp": max_timestamp,
        "identity_revision_sha256": canonical_identity_revision_digest(normalized),
        "table": FIELD_THEORY_TABLE,
        "identity_column": IDENTITY_COLUMN,
        "revision_column": REVISION_COLUMN,
    }


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _reject_symlink_ancestors(path: Path) -> str | None:
    """Reject substituted receipt paths before opening the leaf."""

    lexical = Path(os.path.abspath(str(path.expanduser())))
    current = Path(lexical.anchor)
    for component in lexical.parts[1:]:
        current /= component
        try:
            details = current.lstat()
        except FileNotFoundError:
            # The caller reports a more precise missing-parent/receipt reason.
            continue
        except OSError:
            return "receipt_path_unavailable"
        if stat.S_ISLNK(details.st_mode) and not _allowed_system_alias(current):
            return "receipt_path_substituted"
    return None


def _read_private_receipt(path: Path) -> tuple[dict[str, Any] | None, os.stat_result | None, str | None]:
    """Open a receipt with O_NOFOLLOW and verify owner-only path controls."""

    path = _owner_expand(str(path)).absolute()
    ancestor_error = _reject_symlink_ancestors(path)
    if ancestor_error:
        return None, None, ancestor_error
    try:
        parent = path.parent.lstat()
    except FileNotFoundError:
        return None, None, "receipt_parent_missing"
    except OSError:
        return None, None, "receipt_path_unavailable"
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.getuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        return None, None, "receipt_parent_permissions_invalid"

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, os.O_RDONLY | nofollow)
    except FileNotFoundError:
        return None, None, "receipt_missing"
    except OSError:
        return None, None, "receipt_unavailable"
    try:
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) != 0o600
        ):
            return None, details, "receipt_permissions_invalid"
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            try:
                value = json.load(handle)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None, details, "receipt_malformed"
    except OSError:
        return None, details, "receipt_unavailable"
    finally:
        if descriptor != -1:
            os.close(descriptor)
    if not isinstance(value, dict):
        return None, details, "receipt_malformed"
    return value, details, None


def _validate_receipt_shape(receipt: Mapping[str, Any]) -> str | None:
    missing = RECEIPT_REQUIRED_KEYS - set(receipt)
    if missing:
        return "receipt_schema_incomplete"
    if receipt.get("schema") != RECEIPT_SCHEMA:
        return "receipt_schema_mismatch"
    if receipt.get("outcome") not in ACCEPTED_OUTCOMES:
        return "receipt_outcome_invalid"
    if receipt.get("authoritative") is not True:
        return "receipt_not_authoritative"
    if receipt.get("deterministic_checks_passed") is not True:
        return "deterministic_checks_failed"
    if not isinstance(receipt.get("run_id"), str) or not str(receipt.get("run_id")).strip():
        return "receipt_run_id_invalid"

    for key in ("state_binding_before", "state_binding_after"):
        state_binding = receipt.get(key)
        if not isinstance(state_binding, dict):
            return "state_binding_invalid"
        if not {"md", "library", "commands", "media_cache", "root_files"}.issubset(state_binding):
            return "state_binding_incomplete"
        media_cache = state_binding.get("media_cache")
        if not isinstance(media_cache, dict) or media_cache.get("transactional") is not True:
            return "state_binding_media_not_transactional"
    after_root_files = receipt["state_binding_after"].get("root_files")
    if not isinstance(after_root_files, dict):
        return "state_binding_incomplete"
    database_file = after_root_files.get("bookmarks_db")
    if not isinstance(database_file, dict) or not DIGEST_RE.fullmatch(
        str(database_file.get("sha256") or "")
    ):
        return "state_binding_database_invalid"

    source = receipt.get("source")
    source_id = (
        source.get("id", source.get("source_id"))
        if isinstance(source, dict)
        else source
    )
    if source_id != "field-theory":
        return "receipt_source_mismatch"
    for key in ("media", "stages", "stage_contract", "safe_restart"):
        if not isinstance(receipt.get(key), dict):
            return f"receipt_{key}_invalid"
    stage_contract = receipt["stage_contract"]
    if (
        stage_contract.get("complete") is not True
        or not isinstance(stage_contract.get("expected"), list)
        or not stage_contract.get("expected")
        or stage_contract.get("missing") != []
        or stage_contract.get("invalid_states") != []
    ):
        return "stage_contract_incomplete"
    safe_restart = receipt["safe_restart"]
    if (
        safe_restart.get("snapshot_created") is not True
        or safe_restart.get("media_cache_transactional") is not True
    ):
        return "safe_restart_incomplete"

    binding = receipt.get("database_binding")
    if not isinstance(binding, dict) or not BINDING_REQUIRED_KEYS <= set(binding):
        return "receipt_database_binding_incomplete"
    if (
        binding.get("table") != FIELD_THEORY_TABLE
        or binding.get("identity_column") != IDENTITY_COLUMN
        or binding.get("revision_column") != REVISION_COLUMN
    ):
        return "receipt_database_contract_mismatch"
    row_count = binding.get("row_count")
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
        return "receipt_row_count_invalid"
    if not isinstance(binding.get("max_source_timestamp"), str):
        return "receipt_timestamp_invalid"
    if not isinstance(binding.get("identity_revision_sha256"), str) or not DIGEST_RE.fullmatch(
        binding["identity_revision_sha256"]
    ):
        return "receipt_digest_invalid"
    return None


def verify_receipt(
    receipt_path: Path,
    database_path: Path,
    *,
    now: datetime | None = None,
    max_age_seconds: int = MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Validate one receipt and bind it to the current read-only database."""

    receipt, file_details, error = _read_private_receipt(Path(receipt_path))
    if error:
        return _failure(error)
    assert receipt is not None and file_details is not None

    shape_error = _validate_receipt_shape(receipt)
    if shape_error:
        return _failure(shape_error)
    generated = _parse_timestamp(receipt.get("generated_at"))
    if generated is None:
        return _failure("receipt_timestamp_invalid")
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age_from_generated = (reference - generated).total_seconds()
    age_from_file = reference.timestamp() - file_details.st_mtime
    if age_from_generated < 0:
        return _failure("receipt_generated_at_future")
    if age_from_file < 0:
        return _failure("receipt_mtime_future")
    age_seconds = int(max(age_from_generated, age_from_file))
    if age_seconds > max_age_seconds:
        return _failure("receipt_stale")

    try:
        observed = read_database_binding(Path(database_path))
    except ValueError as exc:
        return _failure(str(exc))
    if observed != receipt["database_binding"]:
        return _failure("database_binding_mismatch")
    expected_file_digest = str(
        (
            ((receipt.get("state_binding_after") or {}).get("root_files") or {}).get(
                "bookmarks_db"
            )
            or {}
        ).get("sha256")
        or ""
    )
    try:
        actual_file_digest = file_sha256(Path(database_path))
    except OSError:
        return _failure("database_unavailable")
    if expected_file_digest != actual_file_digest:
        return _failure("database_file_binding_mismatch")
    return _success(age_seconds=age_seconds, binding=observed)


def _source_contract(source: Mapping[str, Any]) -> Mapping[str, Any]:
    contract = source.get("field_theory_contract") or source.get("sqlite") or {}
    return contract if isinstance(contract, dict) else {}


def _configured_receipt_path(source: Mapping[str, Any]) -> Path:
    """Resolve the one documented owner-local receipt location."""

    configured = _source_contract(source).get("freshness_receipt")
    candidate = default_receipt_path() if configured is None else _owner_expand(str(configured)).absolute()
    expected = default_receipt_path()
    # Compare the lexical paths.  Resolving here would make a symlinked path
    # look allowlisted; the leaf/ancestor checks reject such substitution.
    if candidate != expected:
        raise ValueError("receipt_path_not_allowlisted")
    return candidate


def _database_path(source: Mapping[str, Any]) -> Path | None:
    paths = source.get("paths")
    if not isinstance(paths, list) or len(paths) != 1 or not isinstance(paths[0], str):
        return None
    path = _owner_expand(paths[0])
    if path.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        return None
    return path


def preflight_source(source: Mapping[str, Any]) -> dict[str, Any]:
    """Run the receipt gate for a live SQLite Field Theory source.

    Fixture/item sources and non-SQLite exports remain available to focused
    unit tests and dry-run adapter checks.  The installed SQLite source is
    gated before any Stack ledger is opened.
    """

    if source.get("adapter") != "field_theory":
        return {"ok": True, "reason": "not_field_theory"}
    if "items" in source or source.get("pages") is not None:
        return {"ok": True, "reason": "fixture_source"}
    paths = source.get("paths")
    # JSON/JSONL exports are still valid adapter inputs; only the installed
    # SQLite corpus has a stable database-binding receipt to verify.
    if not isinstance(paths, list) or len(paths) != 1 or not isinstance(paths[0], str):
        return {"ok": True, "reason": "non_sqlite_source"}
    database_path = _database_path(source)
    if database_path is None:
        return {"ok": True, "reason": "non_sqlite_source"}
    try:
        receipt_path = _configured_receipt_path(source)
    except ValueError as exc:
        return _failure(str(exc))
    return verify_receipt(receipt_path, database_path)


def preflight_sources(document: Mapping[str, Any]) -> dict[str, Any]:
    sources = document.get("sources") if isinstance(document, dict) else None
    if not isinstance(sources, list):
        return _failure("sources_document_invalid")
    checks: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict) or not source.get("enabled", True):
            continue
        if source.get("adapter") != "field_theory":
            continue
        result = preflight_source(source)
        checks.append({"source_id": source.get("id", "unknown"), **result})
    failures = [check for check in checks if not check.get("ok")]
    return {
        "ok": not failures,
        "reason": "fresh_bound" if not failures else "field_theory_freshness_failed",
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--database", type=Path)
    args = parser.parse_args(argv)
    if (args.receipt is None) != (args.database is None):
        parser.error("--receipt and --database must be provided together")
    if args.receipt is not None and args.database is not None:
        result = verify_receipt(args.receipt, args.database)
    else:
        source_path = args.sources or Path(__file__).resolve().parents[1] / "config/bookmark-sources.json"
        try:
            document = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            result = _failure("sources_document_invalid")
        else:
            result = preflight_sources(document)
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0 if result.get("ok") else 75


if __name__ == "__main__":
    raise SystemExit(main())
