#!/usr/bin/env python3
"""Reconcile the approved Field Theory bookmark source into a safe snapshot.

The default is a read-only dry run.  The JSON emitted by this command is a
public projection containing only opaque identities and digests; raw rows and
cursor values remain in the owner-local ledger when ``--apply`` is explicitly
approved.
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
    FIELD_THEORY_SOURCE_ID,
    IMPORT_APPROVAL,
    SOURCE_SYNC_APPROVAL,
    atomic_owner_json,
    canonical_json_digest as _canonical_json_digest,
    compare_source_sets,
    load_owner_rows,
    normalize_observation,
    policy_digest,
    read_json,
    reconcile_pages,
    source_from_document,
    store_owner_records,
    validate_optional_x_api,
        write_public_json,
    )
except ModuleNotFoundError:  # imported by a focused test through a file spec
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from bookmark_private_corpus import (  # type: ignore
        BACKFILL_APPROVAL,
        CorpusError,
        FIELD_THEORY_SOURCE_ID,
        IMPORT_APPROVAL,
        SOURCE_SYNC_APPROVAL,
        atomic_owner_json,
        canonical_json_digest as _canonical_json_digest,
        compare_source_sets,
        load_owner_rows,
        normalize_observation,
        policy_digest,
        read_json,
        reconcile_pages,
        source_from_document,
        store_owner_records,
        validate_optional_x_api,
        write_public_json,
    )


def canonical_json_digest_public(value: Any) -> str:
    """Compatibility alias used by focused tests and downstream scripts."""

    return _canonical_json_digest(value)


# The tests and public contract intentionally use this short name.
canonical_json_digest = canonical_json_digest_public


def reconcile_sources(source: dict[str, Any], policy: Any, parity: dict[str, Any] | None = None, *, ledger_path: Path | None = None, apply: bool = False, previous_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a safe source snapshot and optionally persist owner-local rows."""

    snapshot, raw_records = reconcile_pages(source_from_document(source), policy, parity)
    if previous_snapshot is not None:
        current = {row["canonical_source_identity"]: row["revision_digest"] for row in snapshot["observations"]}
        previous = {row["canonical_source_identity"]: row["revision_digest"] for row in previous_snapshot.get("observations", [])}
        snapshot["zero_delta"] = {
            "state": "passed" if current == previous else "changed",
            "changed_count": sum(1 for identity in set(current) | set(previous) if current.get(identity) != previous.get(identity)),
            "digest": canonical_json_digest({"current": current, "previous": previous}),
        }
    if apply:
        if ledger_path is None:
            raise CorpusError("--apply requires an owner-local ledger path")
        stored = store_owner_records(ledger_path, raw_records)
        snapshot["owner_local"] = {"stored_observations": stored, "ledger_state": "updated"}
    else:
        snapshot["owner_local"] = {"stored_observations": 0, "ledger_state": "not_touched"}
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", help="fixture or owner-local Field Theory export")
    parser.add_argument("--sources", default=str(Path(__file__).parents[1] / "config/bookmark-sources.json"))
    parser.add_argument("--policy", default=str(Path(__file__).parents[1] / "config/bookmark-fetch-policy.json"))
    parser.add_argument("--policy-inline", help=argparse.SUPPRESS)
    parser.add_argument("--parity", help="approved fixture snapshot for set-diff audit; never a live endpoint")
    parser.add_argument("--ledger", help="owner-local ledger path; ignored during dry run")
    parser.add_argument("--zero-delta-against", help="previous safe snapshot for a second-pass check")
    parser.add_argument("--out", help="safe snapshot output path")
    parser.add_argument("--apply", action="store_true", help="persist raw observations to the owner-local ledger")
    parser.add_argument("--approval-contract", help="exact human approval contract for source mutation")
    parser.add_argument("--x-api-approved", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--x-api-spend-approved", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        input_doc = read_json(Path(args.input)) if args.input else read_json(Path(args.sources))
        source = source_from_document(input_doc)
        policy = json.loads(args.policy_inline) if args.policy_inline else read_json(Path(args.policy))
        parity = read_json(Path(args.parity)) if args.parity else None
        if args.apply and args.approval_contract != SOURCE_SYNC_APPROVAL:
            raise CorpusError("source synchronization requires the exact approval contract")
        # This validates the optional lane and explicitly proves that no
        # network request is attempted by the reconciliation command.
        optional_x = source.get("optional_x_api") or policy.get("optional_x_api")
        optional_contract = validate_optional_x_api(
            optional_x,
            approved=args.x_api_approved,
            spend_approved=args.x_api_spend_approved,
        )
        snapshot = reconcile_sources(
            source,
            policy,
            parity,
            ledger_path=Path(args.ledger) if args.ledger else None,
            apply=args.apply,
            previous_snapshot=read_json(Path(args.zero_delta_against)) if args.zero_delta_against else None,
        )
        snapshot["parity_contract"] = optional_contract
        if not args.apply:
            snapshot["mode"] = "dry-run"
        else:
            snapshot["mode"] = "apply"
        if args.out:
            write_public_json(Path(args.out), snapshot)
        else:
            sys.stdout.write(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
        return 0
    except (CorpusError, OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"reconcile-bookmark-sources: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
