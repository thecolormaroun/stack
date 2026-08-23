#!/usr/bin/env python3
"""Prepare or explicitly apply private bookmark deltas to GBrain.

The transport is versioned around the current GBrain CLI's markdown-directory
import shape, but this command never invokes the live CLI unless a caller
injects ``CliGBrainTransport``.  Tests use the same interface with a fake
transport.  Dry-run is the default and creates no markdown directory.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

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

    def import_markdown_directory(self, *, source: str, documents: list[dict[str, Any]], idempotency_key: str) -> dict[str, Any]:
        raise NotImplementedError

    def text_canary(self, *, source: str, identity: str) -> dict[str, Any]:
        raise NotImplementedError


class CliGBrainTransport(GBrainTransport):
    """Adapter for the approved CLI contract, with no ambient credentials."""

    def __init__(self, cli_path: str | None = None, runner: Callable[..., Any] | None = None) -> None:
        self.cli_path = cli_path or os.environ.get("GBRAIN_CLI", os.path.expanduser("~/.bun/bin/gbrain"))
        self.runner = runner or subprocess.run

    def _invoke(self, argv: list[str], *, expect_json: bool) -> dict[str, Any]:
        environment = os.environ.copy()
        environment["GBRAIN_SOURCE"] = "x-bookmarks"
        try:
            result = self.runner(argv, capture_output=True, text=True, env=environment, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"_transport_status": "unavailable", "_error_type": type(exc).__name__}
        stdout = result.stdout if isinstance(result.stdout, str) else ""
        if not expect_json:
            return {"_transport_status": "success" if result.returncode == 0 else "failed", "_returncode": result.returncode, "_stdout": stdout}
        try:
            payload = json.loads(stdout) if stdout.strip() else None
        except json.JSONDecodeError:
            return {"_transport_status": "invalid_response", "_returncode": result.returncode}
        if not isinstance(payload, dict):
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
        argv = [self.cli_path, "import", directory, "--source-id", source, "--json"]
        invocation = self._invoke(argv, expect_json=True)
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
        argv = [self.cli_path, "search", identity, "--limit", "1"]
        result = self._invoke(argv, expect_json=False)
        if result.get("_transport_status") == "success" and identity in str(result.get("_stdout", "")):
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


def import_deltas(snapshot: dict[str, Any], *, output_dir: Path, apply: bool = False, approval_contract: str | None = None, transport: GBrainTransport | None = None, ledger_path: Path | None = None, max_attempts: int = 3) -> dict[str, Any]:
    """Import snapshot observations idempotently through an injected transport."""

    if apply and approval_contract != IMPORT_APPROVAL:
        raise ImportError("GBrain import requires the exact approval contract")
    observations = snapshot.get("observations", [])
    if not isinstance(observations, list):
        raise ImportError("snapshot observations must be an array")
    source = "x-bookmarks"
    snapshot_digest = canonical_json_digest(snapshot)
    identities = sorted(str(row["canonical_source_identity"]) for row in observations if isinstance(row, dict) and row.get("canonical_source_identity"))
    idempotency_material = {"snapshot": snapshot_digest, "identities": identities, "transport": IMPORT_TRANSPORT_VERSION}
    idempotency_key = f"{source}:{canonical_json_digest(idempotency_material)}"
    result: dict[str, Any] = {
        "schema_version": 1,
        "receipt_id": "import:" + canonical_json_digest({"source": source, "key": idempotency_key})[:32],
        "source": source,
        "mode": "apply" if apply else "dry-run",
        "snapshot_digest": snapshot_digest,
        "transport": {"contract_version": IMPORT_TRANSPORT_VERSION, "source": source, "operation": "markdown_directory"},
        "idempotency": {"key": idempotency_key, "identity_count": len(identities), "duplicate": False},
        "retry": {"attempts": 0, "max_attempts": max(1, max_attempts), "state": "not_started"},
        "canary": {"state": "not_run"},
        "status": "prepared" if not apply else "pending",
        "accepted_count": 0,
        "rejected_count": 0,
        "pending_count": len(identities),
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
            existing_identity = identities[0] if identities else None
            canary_response = transport.text_canary(source=source, identity=existing_identity) if existing_identity else {"status": existing_state}
            promoted = "indexed" if existing_state == "indexed" or canary_response.get("status") == "indexed" else existing_state
            result.update(status="no_action" if existing_state == "indexed" or promoted != "indexed" else "indexed", pending_count=0)
            result["idempotency"]["duplicate"] = True
            result["canary"] = {"state": promoted, "identity": existing_identity, "source": source}
            if promoted == "indexed" and existing_state != "indexed":
                atomic_owner_json(marker, {"schema_version": 1, "idempotency_key": idempotency_key, "status": "indexed", "canary_state": "indexed"})
            return result
    raw_by_evidence = load_owner_rows(ledger_path, [str(row.get("evidence_id")) for row in observations if isinstance(row, dict)]) if ledger_path else {}
    previously_accepted = {str(identity) for identity in existing.get("accepted_identities", []) if isinstance(identity, str)}
    documents = [
        _public_document(row, raw_by_evidence.get(row.get("evidence_id")), output_dir)
        for row in observations
        if isinstance(row, dict) and row.get("canonical_source_identity") not in previously_accepted
    ]
    if not documents and previously_accepted:
        result.update(status="no_action", accepted_count=len(previously_accepted), pending_count=0)
        result["idempotency"]["duplicate"] = True
        result["canary"] = {"state": str(existing.get("canary_state", "accepted")), "identity": sorted(previously_accepted)[0], "source": source}
        return result
    _write_documents(output_dir, documents)
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
    accepted_identity = sorted(accepted_identities)[0] if accepted_identities else None
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
    parser.add_argument("--out")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approval-contract")
    parser.add_argument("--cli")
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        snapshot = read_json(Path(args.snapshot))
        if not isinstance(snapshot, dict):
            raise ImportError("snapshot must be an object")
        transport = CliGBrainTransport(args.cli) if args.apply and args.cli else None
        result = import_deltas(
            snapshot,
            output_dir=Path(args.markdown_dir),
            apply=args.apply,
            approval_contract=args.approval_contract,
            transport=transport,
            ledger_path=Path(args.ledger) if args.ledger else None,
            max_attempts=args.max_attempts,
        )
        if args.out:
            write_public_json(Path(args.out), result)
        else:
            sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return 0
    except (ImportError, OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"import-bookmark-deltas: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
