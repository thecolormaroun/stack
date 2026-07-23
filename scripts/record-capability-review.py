#!/usr/bin/env python3
"""Record a human capability review without authorizing source mutation.

This command binds an explicit review artifact to the current audit and
migration map. It never moves files, creates destination receipts, activates
catalog entries, compiles runtimes, or enables scheduling.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


DISPOSITION_LIFECYCLE = {
    "keep": lambda _source: "active",
    "hold": lambda source: source,
    "demote": lambda _source: "candidate",
    "merge": lambda _source: "deprecated",
    "move": lambda _source: "external",
    "archive": lambda _source: "archived",
}
ALLOWED_DECISIONS = set(DISPOSITION_LIFECYCLE)
CONSEQUENTIAL_PROPOSALS = {"move", "merge", "demote", "archive", "hold"}
APPLY_PREREQUISITE_DECISIONS = {"move", "merge"}


class ReviewError(ValueError):
    """The review cannot be safely bound to the migration."""


def canonical_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReviewError(f"{label} is not readable JSON") from error
    if not isinstance(value, dict):
        raise ReviewError(f"{label} must be an object")
    return value


def validate_review(review: dict[str, Any], migration: dict[str, Any]) -> dict[str, dict[str, Any]]:
    required = {
        "schema_version", "migration_id", "reviewed_by", "reviewed_at",
        "approval_statement", "scope", "batch_confirm_unchanged_keeps", "decisions",
    }
    if set(review) != required or review.get("schema_version") != "capability-migration-review-decision/v1":
        raise ReviewError("review artifact has unsupported or missing fields")
    if review.get("migration_id") != migration.get("migration_id"):
        raise ReviewError("review artifact does not match the migration")
    if review.get("scope") != "disposition-review-only":
        raise ReviewError("review scope must remain disposition-review-only")
    if review.get("batch_confirm_unchanged_keeps") is not True:
        raise ReviewError("unchanged keeps require explicit batch confirmation")
    for field in ("reviewed_by", "reviewed_at", "approval_statement"):
        if not isinstance(review.get(field), str) or not review[field].strip():
            raise ReviewError(f"review artifact requires {field}")
    rows = review.get("decisions")
    if not isinstance(rows, list):
        raise ReviewError("review decisions must be a list")
    by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ReviewError("review decisions must be objects")
        allowed = {"canonical_name", "decision", "rationale", "merge_target"}
        if set(row) - allowed or not {"canonical_name", "decision", "rationale"} <= set(row):
            raise ReviewError("review decision has unsupported or missing fields")
        name, decision = row["canonical_name"], row["decision"]
        if not isinstance(name, str) or name in by_name:
            raise ReviewError("review decision names must be unique strings")
        if decision not in ALLOWED_DECISIONS:
            raise ReviewError(f"{name}: invalid review decision")
        if not isinstance(row["rationale"], str) or not row["rationale"].strip():
            raise ReviewError(f"{name}: review rationale is required")
        if decision == "merge" and (not isinstance(row.get("merge_target"), str) or not row["merge_target"] or row["merge_target"] == name):
            raise ReviewError(f"{name}: merge_target is required")
        if decision != "merge" and "merge_target" in row:
            raise ReviewError(f"{name}: merge_target is only valid for merge")
        by_name[name] = row

    expected = {
        item["source"]["canonical_name"]
        for item in migration.get("decisions", [])
        if item.get("proposed_disposition") in CONSEQUENTIAL_PROPOSALS
    }
    if set(by_name) != expected:
        missing = sorted(expected - set(by_name))
        extra = sorted(set(by_name) - expected)
        raise ReviewError(f"review must cover every consequential decision exactly once; missing={missing}, extra={extra}")
    return by_name


def record_review(
    audit: dict[str, Any], migration: dict[str, Any], review: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if migration.get("status") != "draft" or migration.get("human_approval") != "not granted":
        raise ReviewError("migration is not an unapproved draft")
    recommendations = validate_review(review, migration)
    migration_names = {item["source"]["canonical_name"] for item in migration.get("decisions", [])}
    audit_names = {item["canonical_name"] for item in audit.get("capabilities", [])}
    if migration_names != audit_names:
        raise ReviewError("audit and migration capability sets differ")

    decisions_by_name: dict[str, tuple[str, str]] = {}
    for audit_row in audit["capabilities"]:
        name = audit_row["canonical_name"]
        recommendation = recommendations.get(name)
        if recommendation is None:
            if audit_row.get("proposed_disposition") != "keep":
                raise ReviewError(f"{name}: consequential decision is missing")
            decision = "keep"
            rationale = "Batch-confirmed unchanged keep under Maroun's Approve all review."
        else:
            decision = recommendation["decision"]
            rationale = recommendation["rationale"]
        audit_row["review_state"] = "approved"
        audit_row["review_decision"] = decision
        audit_row["review_rationale"] = rationale
        decisions_by_name[name] = (decision, rationale)

    audit["human_approval"] = "approved"
    audit["approval"] = {
        "reviewed_by": review["reviewed_by"],
        "reviewed_at": review["reviewed_at"],
        "approval_statement": review["approval_statement"],
        "scope": review["scope"],
        "review_artifact": "registry/migrations/2026-07-19-estate-refactor-review.json",
    }

    for migration_row in migration["decisions"]:
        name = migration_row["source"]["canonical_name"]
        decision, rationale = decisions_by_name[name]
        migration_row["review_decision"] = decision
        migration_row["review_rationale"] = rationale
        migration_row["review_state"] = "reviewed" if decision in APPLY_PREREQUISITE_DECISIONS else "approved"
        migration_row["lifecycle"]["to"] = DISPOSITION_LIFECYCLE[decision](migration_row["lifecycle"]["from"])
        recommendation = recommendations.get(name, {})
        if decision == "merge":
            target = recommendation["merge_target"]
            migration_row["merge_target"] = target
            migration_row["compatibility_alias"] = {"alias": name, "canonical_target": target}

    migration["status"] = "reviewed-awaiting-apply-prerequisites"
    migration["human_approval"] = "approved"
    migration["source"]["audit_digest"] = digest(audit)
    migration["approval"] = audit["approval"]

    counts = Counter(decision for decision, _rationale in decisions_by_name.values())
    receipt = {
        "schema_version": "capability-migration-review-receipt/v1",
        "migration_id": migration["migration_id"],
        "status": "recorded",
        "scope": review["scope"],
        "reviewed_by": review["reviewed_by"],
        "reviewed_at": review["reviewed_at"],
        "approval_statement": review["approval_statement"],
        "decision_counts": dict(sorted(counts.items())),
        "audit_digest": digest(audit),
        "migration_digest": digest(migration),
        "source_mutation_authorized": False,
        "runtime_publication_authorized": False,
        "scheduler_enablement_authorized": False,
        "next_gate": "destination-and-consumer-proof",
    }
    return audit, migration, receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--migration", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--receipt-out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        audit = load_object(args.audit, "audit")
        migration = load_object(args.migration, "migration")
        review = load_object(args.review, "review")
        audit, migration, receipt = record_review(audit, migration, review)
        args.audit.write_text(canonical_json(audit), encoding="utf-8")
        args.migration.write_text(canonical_json(migration), encoding="utf-8")
        args.receipt_out.parent.mkdir(parents=True, exist_ok=True)
        args.receipt_out.write_text(canonical_json(receipt), encoding="utf-8")
        print(canonical_json({"status": "recorded", "receipt": args.receipt_out.as_posix()}), end="")
        return 0
    except (ReviewError, OSError, KeyError, TypeError) as error:
        print(f"capability review recording failed closed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
