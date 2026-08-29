#!/usr/bin/env python3
"""Run a bounded, resumable Field Theory history backfill.

Backfill is deliberately separate from recurring delta mode.  It is dry-run by
default and requires the exact U15 approval contract before it creates an
owner-local checkpoint or ledger.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from bookmark_private_corpus import (  # type: ignore
        BACKFILL_APPROVAL,
        CorpusError,
        atomic_owner_json,
        canonical_json,
        canonical_json_digest,
        load_source_pages,
        normalize_observation,
        owner_local_path,
        policy_digest,
        read_json,
        source_from_document,
        store_owner_records,
        write_public_json,
    )
except ModuleNotFoundError:  # imported by a focused test through a file spec
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from bookmark_private_corpus import (  # type: ignore
        BACKFILL_APPROVAL,
        CorpusError,
        atomic_owner_json,
        canonical_json,
        canonical_json_digest,
        load_source_pages,
        normalize_observation,
        owner_local_path,
        policy_digest,
        read_json,
        source_from_document,
        store_owner_records,
        write_public_json,
    )


class BackfillError(CorpusError):
    """A fail-closed backfill contract error."""


def _safe_page_digest(page: dict[str, Any]) -> str:
    return canonical_json_digest(page)


def _load_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackfillError("invalid owner-local backfill checkpoint") from exc
    if not isinstance(value, dict):
        raise BackfillError("invalid owner-local backfill checkpoint")
    return value


def _matching_start(pages: list[dict[str, Any]], state: dict[str, Any] | None, source_digest: str) -> tuple[int, bool]:
    if not state:
        return 0, False
    if state.get("source_digest") == source_digest and state.get("terminal") is True:
        return len(pages), True
    cursor = state.get("next_cursor")
    ordinal = state.get("next_page_ordinal")
    if isinstance(ordinal, int) and 0 <= ordinal < len(pages):
        if pages[ordinal].get("requested_cursor") == cursor:
            return ordinal, False
    for index, page in enumerate(pages):
        if page.get("requested_cursor") == cursor:
            return index, False
    if cursor in (None, "") and not state.get("terminal"):
        return 0, False
    raise BackfillError("checkpoint cursor is not present in the bounded source")


def _receipt_base(source: dict[str, Any], source_digest: str, state: dict[str, Any] | None, apply: bool) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "receipt_id": "backfill:" + canonical_json_digest({"source": source.get("source_id", "field-theory"), "digest": source_digest})[:32],
        "source_id": str(source.get("source_id", "field-theory")),
        "mode": "apply" if apply else "dry-run",
        "source_digest": source_digest,
        "checkpoint_digest": canonical_json_digest(state) if state else None,
        "adapter_version": "field-theory-allowlist-v1",
        "status": "prepared" if not apply else "running",
        "pages_read": 0,
        "first_page_ordinal": None,
        "last_page_ordinal": None,
        "observation_count": 0,
        "stored_count": 0,
        "terminal_cursor": False,
        "resume_cursor_digest": None,
        "zero_delta": False,
        "failure": None,
    }


def backfill_source(source: dict[str, Any], *, state_path: Path, ledger_path: Path, apply: bool = False, approval_contract: str | None = None, max_pages: int | None = None) -> dict[str, Any]:
    """Process pages from the checkpoint, writing only on approved apply."""

    if apply and approval_contract != BACKFILL_APPROVAL:
        raise BackfillError("backfill requires the exact approval contract")
    if apply:
        try:
            state_path = owner_local_path(state_path, "backfill checkpoint")
            ledger_path = owner_local_path(ledger_path, "raw bookmark ledger")
        except CorpusError as exc:
            raise BackfillError(str(exc)) from exc
    pages, _contract = load_source_pages(source)
    source_digest = canonical_json_digest(source)
    state = _load_state(state_path) if apply else None
    receipt = _receipt_base(source, source_digest, state, apply)
    start, already_terminal = _matching_start(pages, state, source_digest) if apply else (0, False)
    if already_terminal:
        receipt.update(status="no_action", terminal_cursor=True, zero_delta=True, checkpoint_digest=canonical_json_digest(state))
        return receipt

    if not apply:
        receipt.update(status="prepared", pages_read=len(pages), observation_count=sum(len(page.get("rows", [])) for page in pages if isinstance(page, dict)))
        return receipt

    records: list[dict[str, Any]] = []
    next_cursor = state.get("next_cursor") if state else None
    page_limit = max_pages if isinstance(max_pages, int) and max_pages > 0 else len(pages)
    for page in pages[start:start + page_limit]:
        if not isinstance(page, dict):
            receipt.update(status="partial", failure={"reason": "invalid_page"})
            break
        ordinal = int(page.get("page_ordinal", start + receipt["pages_read"]))
        requested = page.get("requested_cursor")
        if requested != next_cursor:
            receipt.update(status="partial", failure={"reason": "cursor_gap", "page_ordinal": ordinal})
            break
        if page.get("error"):
            error = page.get("error")
            status = error.get("status") if isinstance(error, dict) else None
            reason = "rate_limited" if status == 429 else "source_error"
            receipt.update(
                status="partial",
                failure={"reason": reason, "page_ordinal": ordinal, **({"status": status} if isinstance(status, int) else {})},
                resume_cursor_digest=canonical_json_digest(requested) if requested not in (None, "") else None,
            )
            checkpoint = {
                "schema_version": 1,
                "source_id": source.get("source_id", "field-theory"),
                "source_digest": source_digest,
                "next_cursor": requested,
                "next_page_ordinal": ordinal,
                "terminal": False,
                "processed_page_digests": state.get("processed_page_digests", []) if state else [],
            }
            atomic_owner_json(state_path, checkpoint)
            return receipt
        rows = page.get("rows", [])
        if not isinstance(rows, list):
            receipt.update(status="partial", failure={"reason": "invalid_rows", "page_ordinal": ordinal})
            break
        for row in rows:
            public, raw = normalize_observation(row, str(source.get("source_id", "field-theory")), "backfill:" + source_digest)
            records.append(raw)
            receipt["observation_count"] += 1
        receipt["pages_read"] += 1
        receipt["first_page_ordinal"] = ordinal if receipt["first_page_ordinal"] is None else receipt["first_page_ordinal"]
        receipt["last_page_ordinal"] = ordinal
        next_cursor = page.get("returned_cursor")
        receipt["resume_cursor_digest"] = canonical_json_digest(next_cursor) if next_cursor not in (None, "") else None
        if next_cursor in (None, ""):
            receipt["terminal_cursor"] = True
            break
    if receipt["terminal_cursor"]:
        receipt["status"] = "complete"
        receipt["zero_delta"] = receipt["observation_count"] == 0
        checkpoint = {
            "schema_version": 1,
            "source_id": source.get("source_id", "field-theory"),
            "source_digest": source_digest,
            "next_cursor": None,
            "next_page_ordinal": len(pages),
            "terminal": True,
            "processed_page_digests": [_safe_page_digest(page) for page in pages[: receipt["last_page_ordinal"] + 1]],
        }
    else:
        receipt["status"] = "partial"
        checkpoint = {
            "schema_version": 1,
            "source_id": source.get("source_id", "field-theory"),
            "source_digest": source_digest,
            "next_cursor": next_cursor,
            "next_page_ordinal": start + receipt["pages_read"],
            "terminal": False,
            "processed_page_digests": [_safe_page_digest(page) for page in pages[: start + receipt["pages_read"]]],
        }
    receipt["stored_count"] = store_owner_records(ledger_path, records)
    atomic_owner_json(state_path, checkpoint)
    receipt["checkpoint_digest"] = canonical_json_digest(checkpoint)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="fixture or owner-local Field Theory source document")
    parser.add_argument("--state", required=True, help="owner-local checkpoint path")
    parser.add_argument("--ledger", required=True, help="owner-local raw observation ledger path")
    parser.add_argument("--out", help="safe receipt output path")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approval-contract")
    parser.add_argument("--max-pages", type=int)
    args = parser.parse_args(argv)
    try:
        source = source_from_document(read_json(Path(args.input)))
        result = backfill_source(
            source,
            state_path=Path(args.state),
            ledger_path=Path(args.ledger),
            apply=args.apply,
            approval_contract=args.approval_contract,
            max_pages=args.max_pages,
        )
        if args.out:
            write_public_json(Path(args.out), result)
        else:
            sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return 0
    except (BackfillError, OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"backfill-bookmark-history: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
