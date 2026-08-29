#!/usr/bin/env python3
"""Prepare or explicitly apply private bookmark deltas to GBrain.

The transport is versioned around the current GBrain CLI's markdown-directory
import shape, but this command never invokes the live CLI unless a caller
injects ``CliGBrainTransport``.  Tests use the same interface with a fake
transport.  Dry-run is the default and creates no markdown directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

try:
    from bookmark_private_corpus import (  # type: ignore
        IMPORT_APPROVAL,
        IMPORT_TRANSPORT_VERSION,
        CorpusError,
        atomic_owner_json,
        canonical_json,
        canonical_json_digest,
        load_owner_rows,
        owner_local_path,
        read_json,
        write_public_json,
    )
except ModuleNotFoundError:  # imported by a focused test through a file spec
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from bookmark_private_corpus import (  # type: ignore
        IMPORT_APPROVAL,
        IMPORT_TRANSPORT_VERSION,
        CorpusError,
        atomic_owner_json,
        canonical_json,
        canonical_json_digest,
        load_owner_rows,
        owner_local_path,
        read_json,
        write_public_json,
    )


class ImportError(CorpusError):
    """A fail-closed GBrain handoff error."""


ACCOUNT_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
DEFAULT_GBRAIN_CLI = str(ACCOUNT_HOME / ".bun" / "bin" / "gbrain")
EXPECTED_GBRAIN_CLI = ACCOUNT_HOME / ".bun" / "install" / "global" / "node_modules" / "gbrain" / "src" / "cli.ts"
DEFAULT_GBRAIN_CONFIG = ACCOUNT_HOME / ".gbrain" / "config.json"
DEFAULT_BUN_CLI = Path("/opt/homebrew/bin/bun")
EXPECTED_BUN_CLI = Path("/opt/homebrew/Cellar/bun/1.3.14/bin/bun")
PINNED_OPERATION_HELPER = Path(__file__).resolve().parent / "gbrain-pinned-operation.ts"
FIXED_PATH = f"{ACCOUNT_HOME}/.bun/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
ALLOWED_LOCAL_POSTGRES_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
ALLOWED_LOCAL_POSTGRES_PORTS = frozenset({5432})
ALLOWED_LOCAL_POSTGRES_DATABASES = frozenset({"gbrain_mookie"})


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


def _local_config_digest(path: Path) -> str | None:
    lexical = Path(path)
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
        or not stat.S_ISREG(details.st_mode)
        or details.st_uid != os.getuid()
        or parent.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) != 0o600
        or stat.S_IMODE(parent.st_mode) & 0o022
        or not isinstance(value, dict)
    ):
        return None
    if value.get("engine") == "postgres":
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
    if value.get("engine") != "pglite" or value.get("database_url") is not None:
        return None
    database_path = value.get("database_path")
    if not isinstance(database_path, str):
        return None
    lexical_database = Path(database_path).expanduser()
    try:
        resolved_database = lexical_database.resolve(strict=True)
        database_details = resolved_database.lstat()
        resolved_database.relative_to(ACCOUNT_HOME / ".gbrain")
    except (OSError, ValueError):
        return None
    allowed = (
        lexical_database.is_absolute()
        and not lexical_database.is_symlink()
        and resolved_database == lexical_database
        and database_details.st_uid == os.getuid()
        and stat.S_IMODE(database_details.st_mode) & 0o022 == 0
    )
    return hashlib.sha256(payload).hexdigest() if allowed else None


def _count(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if isinstance(value, (list, tuple, set)):
        return len(value)
    if isinstance(value, dict):
        return 1
    if isinstance(value, str):
        return 1 if value else 0
    return 0


class GBrainTransport:
    """Injectable transport contract for GBrain import and source canary."""

    contract_version = IMPORT_TRANSPORT_VERSION
    requires_existing_source_inventory = False

    def import_markdown_directory(self, *, source: str, documents: list[dict[str, Any]], idempotency_key: str) -> dict[str, Any]:
        raise NotImplementedError

    def text_canary(self, *, source: str, identity: str) -> dict[str, Any]:
        raise NotImplementedError


class CliGBrainTransport(GBrainTransport):
    """Adapter for the approved CLI contract, with no ambient credentials."""

    requires_existing_source_inventory = True

    def __init__(self, cli_path: str | None = None, runner: Callable[..., Any] | None = None, bun_path: str | Path = DEFAULT_BUN_CLI, config_path: Path | None = None) -> None:
        self.cli_path = cli_path or str(ACCOUNT_HOME / ".bun" / "bin" / "gbrain")
        self.runner = runner or subprocess.run
        self.bun_path = bun_path
        self.config_path = config_path or DEFAULT_GBRAIN_CONFIG

    def _invoke(self, argv: list[str], *, expect_json: bool, input_payload: str | None = None) -> dict[str, Any]:
        config_digest = _local_config_digest(self.config_path)
        bun_executable = _trusted_bun_executable(self.bun_path)
        gbrain_cli = _trusted_gbrain_cli(self.cli_path)
        if config_digest is None or bun_executable is None or gbrain_cli is None or not argv or argv[0] != str(self.bun_path):
            return {"_transport_status": "failed", "_error_type": "local_backend_rejected"}
        invocation = [bun_executable, *argv[1:]]
        if len(invocation) > 2 and invocation[2] == self.cli_path:
            invocation[2] = gbrain_cli
        environment = {
            "GBRAIN_SOURCE": "x-bookmarks",
            "HOME": str(ACCOUNT_HOME),
            "PATH": FIXED_PATH,
            "TMPDIR": "/private/tmp",
        }
        if input_payload is not None:
            environment["GBRAIN_CLI_PATH"] = gbrain_cli
            environment["GBRAIN_CONFIG_SHA256"] = config_digest
        try:
            result = self.runner(
                invocation,
                input=input_payload,
                capture_output=True,
                text=True,
                env=environment,
                cwd=str(ACCOUNT_HOME / ".gbrain"),
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"_transport_status": "unavailable", "_error_type": type(exc).__name__}
        stdout = result.stdout if isinstance(result.stdout, str) else ""
        if not expect_json:
            return {"_transport_status": "success" if result.returncode == 0 else "failed", "_returncode": result.returncode, "_stdout": stdout}
        payload = None
        for line in reversed(stdout.splitlines()):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            break
        if not isinstance(payload, (dict, list)):
            return {"_transport_status": "invalid_response", "_returncode": result.returncode}
        if result.returncode != 0:
            return {"_transport_status": "failed", "_returncode": result.returncode}
        return {"_transport_status": "success", "_returncode": result.returncode, "payload": payload}

    def import_markdown_directory(self, *, source: str, documents: list[dict[str, Any]], idempotency_key: str) -> dict[str, Any]:
        # Idempotency is enforced by Stack's owner-local marker/receipt.  The
        # installed CLI accepts only this directory/source-id/json shape.
        directory = documents[0].get("_directory") if documents else None
        if not isinstance(directory, str):
            return {"status": "failed"}
        argv = [str(self.bun_path), "--no-env-file", str(PINNED_OPERATION_HELPER)]
        request = {"schema_version": 1, "source": source, "operation": "import", "directory": directory}
        invocation = self._invoke(argv, expect_json=True, input_payload=canonical_json(request))
        if invocation.get("_transport_status") != "success":
            return {"status": "failed"}
        payload = invocation.get("payload", {})
        status = str(payload.get("status", ""))
        imported = _count(payload.get("imported"))
        skipped = _count(payload.get("skipped"))
        error_count = _count(payload.get("errors"))
        chunks = _count(payload.get("chunks"))
        total_files = _count(payload.get("total_files"))
        if status != "success":
            return {"status": "failed", "imported_count": imported, "accepted_count": imported + skipped, "skipped_count": skipped, "error_count": error_count, "chunks": chunks, "total_files": total_files}
        return {
            "status": "partial" if error_count else "accepted",
            "imported_count": imported,
            "accepted_count": imported + skipped,
            "skipped_count": skipped,
            "error_count": error_count,
            "chunks": chunks,
            "total_files": total_files,
        }

    def text_canary(self, *, source: str, identity: str) -> dict[str, Any]:
        request = {"schema_version": 1, "source": source, "operation": "keyword", "limit": 3, "query": identity}
        argv = [str(self.bun_path), "--no-env-file", str(PINNED_OPERATION_HELPER)]
        result = self._invoke(argv, expect_json=True, input_payload=canonical_json(request))
        payload = result.get("payload") if result.get("_transport_status") == "success" else None
        if isinstance(payload, dict):
            candidates = payload.get("results", payload.get("items", []))
        else:
            candidates = payload
        suffix = identity.removeprefix("bookmark:")
        expected_slug = "bookmark-" + suffix
        identity_pattern = re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(identity) + r"(?![A-Za-z0-9_-])")
        if isinstance(candidates, list) and len(suffix) == 32 and all(character in "0123456789abcdefABCDEF" for character in suffix):
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                if candidate.get("source_id") != source or candidate.get("slug") != expected_slug:
                    continue
                chunk_text = candidate.get("chunk_text")
                if isinstance(chunk_text, str) and identity_pattern.search(chunk_text):
                    return {"status": "indexed", "source": source, "identity": identity}
        return {"status": "pending", "source": source, "identity": identity}


def _public_document(observation: dict[str, Any], raw_row: dict[str, Any] | None, directory: Path) -> dict[str, Any]:
    identity = observation["canonical_source_identity"]
    # ``body`` is filled from the owner-local ledger when present.  The
    # metadata-only fallback keeps fixture tests deterministic without ever
    # putting raw bookmark text into a public receipt.
    body = "# Private bookmark evidence\n\nEvidence identity: " + identity + "\n"
    if raw_row:
        text = raw_row.get("text") or raw_row.get("article_text") or raw_row.get("article_title")
        if isinstance(text, str) and text:
            body += "\n" + text + "\n"
    filename = identity.replace(":", "-") + ".md"
    return {
        "identity": identity,
        "evidence_id": observation["evidence_id"],
        "content_digest": observation["content_digest"],
        "revision_digest": observation["revision_digest"],
        "markdown": body,
        "_directory": str(directory),
    }


def _write_documents(directory: Path, documents: list[dict[str, Any]]) -> None:
    directory = owner_local_path(directory, "raw GBrain markdown directory")
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    for document in documents:
        filename = document["identity"].replace(":", "-") + ".md"
        path = directory / filename
        path.write_text(document["markdown"], encoding="utf-8")
        os.chmod(path, 0o600)


def _existing_source_identities(root: Path) -> set[str]:
    """Inventory canonical source URLs from an owner-local GBrain source."""

    try:
        root = owner_local_path(root, "private GBrain source root")
    except CorpusError as exc:
        raise ImportError(str(exc)) from exc
    if not root.is_dir():
        raise ImportError("private GBrain source root is unavailable")
    stat = root.stat()
    if stat.st_uid != os.getuid() or stat.st_mode & 0o002:
        raise ImportError("private GBrain source root ownership is unsafe")
    identities: set[str] = set()
    for path in sorted(root.rglob("*.md")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
            if resolved.stat().st_size > 4 * 1024 * 1024:
                continue
            lines = resolved.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise ImportError("private GBrain source inventory failed") from exc
        if not lines or lines[0].strip() != "---":
            continue
        for line in lines[1:]:
            if line.strip() == "---":
                break
            if line.startswith("source_url:"):
                source_url = line.split(":", 1)[1].strip().strip("\"'")
                if source_url.startswith(("https://", "http://")):
                    identities.add("bookmark:" + canonical_json_digest(source_url)[:32])
                break
    return identities


def _safe_result(result: dict[str, Any]) -> dict[str, Any]:
    """Map a transport result into the public receipt vocabulary."""

    status = str(result.get("status", "failed"))
    mapping = {
        "ok": "accepted",
        "imported": "accepted",
        "accepted": "accepted",
        "indexed": "indexed",
        "rejected": "rejected",
        "pending": "pending",
        "partial": "partial",
        "rate_limited": "rate_limited",
        "unavailable": "blocked",
        "failed": "failed",
    }
    safe: dict[str, Any] = {"status": mapping.get(status, "failed")}
    if isinstance(result.get("retry_after_seconds"), (int, float)):
        safe["retry_after_seconds"] = min(300, max(0, int(result["retry_after_seconds"])))
    accepted = result.get("accepted")
    rejected = result.get("rejected")
    if isinstance(accepted, list):
        safe["_accepted_identities"] = [str(item) for item in accepted]
        safe["accepted_count"] = len(accepted)
        safe["_accepted_count"] = len(accepted)
        safe["accepted_id_digest"] = canonical_json_digest(sorted(str(item) for item in accepted))
    if isinstance(rejected, list):
        safe["_rejected_identities"] = [str(item) for item in rejected]
        safe["rejected_count"] = len(rejected)
        safe["rejected_id_digest"] = canonical_json_digest(sorted(str(item) for item in rejected))
    if "accepted_count" in result and not isinstance(accepted, list):
        safe["accepted_count"] = _count(result.get("accepted_count"))
        safe["_accepted_count"] = safe["accepted_count"]
    for key in ("imported_count", "skipped_count", "error_count", "chunks", "total_files"):
        if key in result:
            safe[key] = _count(result.get(key))
    return safe


def import_deltas(snapshot: dict[str, Any], *, output_dir: Path, apply: bool = False, approval_contract: str | None = None, transport: GBrainTransport | None = None, ledger_path: Path | None = None, existing_source_root: Path | None = None, max_attempts: int = 3) -> dict[str, Any]:
    """Import snapshot observations idempotently through an injected transport."""

    if apply and approval_contract != IMPORT_APPROVAL:
        raise ImportError("GBrain import requires the exact approval contract")
    observations = snapshot.get("observations", [])
    if not isinstance(observations, list):
        raise ImportError("snapshot observations must be an array")
    source = "x-bookmarks"
    snapshot_digest = canonical_json_digest(snapshot)
    identities = sorted(str(row["canonical_source_identity"]) for row in observations if isinstance(row, dict) and row.get("canonical_source_identity"))
    source_inventory = _existing_source_identities(existing_source_root) if existing_source_root is not None else set()
    preexisting = set(identities) & source_inventory
    idempotency_material = {
        "snapshot": snapshot_digest,
        "identities": identities,
        "preexisting": sorted(preexisting),
        "transport": IMPORT_TRANSPORT_VERSION,
    }
    idempotency_key = f"{source}:{canonical_json_digest(idempotency_material)}"
    result: dict[str, Any] = {
        "schema_version": 1,
        "receipt_id": "import:" + canonical_json_digest({"source": source, "key": idempotency_key})[:32],
        "source": source,
        "mode": "apply" if apply else "dry-run",
        "snapshot_digest": snapshot_digest,
        "transport": {"contract_version": IMPORT_TRANSPORT_VERSION, "source": source, "operation": "markdown_directory"},
        "idempotency": {"key": idempotency_key, "identity_count": len(identities), "duplicate": False},
        "preexisting": {
            "matched_count": len(preexisting),
            "matched_identity_digest": canonical_json_digest(sorted(preexisting)),
            "source_inventory_digest": canonical_json_digest(sorted(source_inventory)),
        },
        "retry": {"attempts": 0, "max_attempts": max(1, max_attempts), "state": "not_started"},
        "canary": {"state": "not_run"},
        "status": "prepared" if not apply else "pending",
        "accepted_count": 0,
        "rejected_count": 0,
        "pending_count": len(set(identities) - preexisting),
        "failure": None,
    }
    if not apply:
        return result
    try:
        output_dir = owner_local_path(output_dir, "raw GBrain markdown directory")
        if ledger_path is not None:
            ledger_path = owner_local_path(ledger_path, "raw bookmark ledger")
    except CorpusError as exc:
        raise ImportError(str(exc)) from exc
    if snapshot.get("completeness_state") not in {"complete", "partial"}:
        raise ImportError("snapshot completeness state is not importable")
    if snapshot.get("completeness_state") == "partial":
        result["status"] = "partial"
        result["failure"] = {"reason": "source_snapshot_partial"}
        return result
    transport = transport or CliGBrainTransport()
    if existing_source_root is None and bool(getattr(transport, "requires_existing_source_inventory", False)):
        raise ImportError("live GBrain import requires an existing native source inventory")
    marker = output_dir / ".x-bookmarks-import-state.json"
    existing: dict[str, Any] = {}
    if marker.exists():
        try:
            loaded = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ImportError("invalid owner-local import checkpoint") from exc
        if isinstance(loaded, dict):
            existing = loaded
        if existing.get("idempotency_key") == idempotency_key and existing.get("status") in {"accepted", "indexed"}:
            existing_state = str(existing.get("canary_state", "accepted"))
            accepted_identities = sorted({
                str(identity)
                for identity in existing.get("accepted_identities", [])
                if isinstance(identity, str) and identity in identities
            })
            existing_identity = accepted_identities[0] if accepted_identities else (identities[0] if identities else None)
            canary_response = transport.text_canary(source=source, identity=existing_identity) if existing_identity else {"status": "failed"}
            current_canary = _safe_result(canary_response).get("status")
            promoted = "indexed" if current_canary == "indexed" else ("accepted" if existing_state == "accepted" else "failed")
            result.update(
                status=("no_action" if existing_state == "indexed" else "indexed") if promoted == "indexed" else promoted,
                accepted_count=len(accepted_identities),
                pending_count=0,
            )
            result["idempotency"]["duplicate"] = True
            result["canary"] = {"state": promoted, "identity": existing_identity, "source": source}
            if promoted != "indexed":
                result["failure"] = {"reason": "canary_not_indexed"}
            if promoted == "indexed" and existing_state != "indexed":
                atomic_owner_json(marker, {
                    "schema_version": 1,
                    "idempotency_key": idempotency_key,
                    "status": "indexed",
                    "canary_state": "indexed",
                    "accepted_identities": accepted_identities,
                })
            return result
    raw_by_evidence = load_owner_rows(ledger_path, [str(row.get("evidence_id")) for row in observations if isinstance(row, dict)]) if ledger_path else {}
    previously_accepted = preexisting | {
        str(identity)
        for identity in existing.get("accepted_identities", [])
        if isinstance(identity, str) and identity in identities
    }
    batch_identity_digest = canonical_json_digest(sorted(set(identities) - previously_accepted))[:24]
    batch_directory = output_dir / ("batch-" + batch_identity_digest)
    documents = [
        _public_document(row, raw_by_evidence.get(row.get("evidence_id")), batch_directory)
        for row in observations
        if isinstance(row, dict) and row.get("canonical_source_identity") not in previously_accepted
    ]
    if not documents and previously_accepted:
        identity = sorted(previously_accepted)[0]
        canary = _safe_result(transport.text_canary(source=source, identity=identity))
        canary_state = str(canary.get("status", "failed"))
        status = "no_action" if canary_state == "indexed" else ("accepted" if canary_state == "accepted" else "failed")
        result.update(status=status, accepted_count=len(previously_accepted), pending_count=0)
        result["idempotency"]["duplicate"] = True
        result["canary"] = {"state": canary_state, "identity": identity, "source": source}
        if canary_state != "indexed":
            result["failure"] = {"reason": "canary_not_indexed"}
        return result
    _write_documents(batch_directory, documents)
    mapped: dict[str, Any] = {"status": "failed"}
    attempts = 0
    for attempt in range(1, max(1, max_attempts) + 1):
        attempts = attempt
        mapped = _safe_result(transport.import_markdown_directory(source=source, documents=documents, idempotency_key=idempotency_key))
        if mapped["status"] != "rate_limited":
            break
        delay = mapped.get("retry_after_seconds", 0)
        if delay:
            time.sleep(min(5, delay))
    result["retry"] = {"attempts": attempts, "max_attempts": max(1, max_attempts), "state": "exhausted" if mapped["status"] == "rate_limited" else ("retried" if attempts > 1 else "none")}
    batch_accepted = set(str(identity) for identity in mapped.get("_accepted_identities", []))
    batch_accepted_count = _count(mapped.get("_accepted_count", len(batch_accepted)))
    if not batch_accepted and batch_accepted_count >= len(documents) and mapped["status"] in {"accepted", "indexed"}:
        batch_accepted = {str(document["identity"]) for document in documents}
    accepted_identities = previously_accepted | batch_accepted
    result["accepted_count"] = len(accepted_identities) if batch_accepted else len(previously_accepted) + batch_accepted_count
    result["rejected_count"] = int(mapped.get("rejected_count", mapped.get("error_count", 0)))
    result["pending_count"] = max(0, len(identities) - result["accepted_count"] - result["rejected_count"])
    result["transport_result"] = {key: value for key, value in mapped.items() if not key.startswith("_")}
    if mapped["status"] in {"rate_limited", "partial"}:
        result["status"] = "partial"
        result["failure"] = {"reason": "rate_limited" if mapped["status"] == "rate_limited" else "partial_transport_result"}
        atomic_owner_json(marker, {
            "schema_version": 1,
            "idempotency_key": idempotency_key,
            "status": "partial",
            "canary_state": str(existing.get("canary_state", "accepted")),
            "accepted_identities": sorted(accepted_identities),
        })
        return result
    if mapped["status"] in {"failed", "blocked"}:
        result["status"] = mapped["status"]
        result["failure"] = {"reason": "transport_unavailable" if mapped["status"] == "blocked" else "transport_failed"}
        atomic_owner_json(marker, {
            "schema_version": 1,
            "idempotency_key": idempotency_key,
            "status": "partial",
            "canary_state": str(existing.get("canary_state", "accepted")),
            "accepted_identities": sorted(accepted_identities),
        })
        return result
    if mapped["status"] == "rejected":
        result["status"] = "rejected"
        atomic_owner_json(marker, {
            "schema_version": 1,
            "idempotency_key": idempotency_key,
            "status": "rejected",
            "canary_state": "accepted",
            "accepted_identities": sorted(accepted_identities),
        })
        return result
    accepted_identity = sorted(batch_accepted)[0] if batch_accepted else (sorted(accepted_identities)[0] if accepted_identities else None)
    canary_response = transport.text_canary(source=source, identity=accepted_identity) if accepted_identity else {"status": "accepted"}
    canary_state = "indexed" if canary_response.get("status") == "indexed" else "accepted"
    result["canary"] = {"state": canary_state, "identity": accepted_identity, "source": source}
    result["status"] = "indexed" if canary_state == "indexed" else "accepted"
    atomic_owner_json(marker, {
        "schema_version": 1,
        "idempotency_key": idempotency_key,
        "status": result["status"],
        "canary_state": canary_state,
        "accepted_identities": sorted(accepted_identities),
    })
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--markdown-dir", required=True)
    parser.add_argument("--ledger")
    parser.add_argument("--existing-source-root", help="owner-local native x-bookmarks source used to prevent duplicate imports")
    parser.add_argument("--out")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approval-contract")
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        if args.apply and not args.existing_source_root:
            raise ImportError("live GBrain import requires an existing native source inventory")
        snapshot = read_json(Path(args.snapshot))
        if not isinstance(snapshot, dict):
            raise ImportError("snapshot must be an object")
        transport = CliGBrainTransport() if args.apply else None
        result = import_deltas(
            snapshot,
            output_dir=Path(args.markdown_dir),
            apply=args.apply,
            approval_contract=args.approval_contract,
            transport=transport,
            ledger_path=Path(args.ledger) if args.ledger else None,
            existing_source_root=Path(args.existing_source_root) if args.existing_source_root else None,
            max_attempts=args.max_attempts,
        )
        if args.out:
            write_public_json(Path(args.out), result)
        else:
            sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        if not args.apply:
            return 0
        return 0 if result.get("status") in {"indexed", "no_action"} else 1
    except (ImportError, OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"import-bookmark-deltas: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
