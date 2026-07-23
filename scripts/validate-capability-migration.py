#!/usr/bin/env python3
"""Validate a reviewed, one-time Stack capability migration map without mutating source."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


class MigrationError(ValueError):
    """Raised when a migration map cannot safely proceed."""


LIFECYCLE_TRANSITIONS = {
    "candidate": {"candidate", "active", "deprecated", "archived", "external"},
    "active": {"active", "deprecated", "archived", "external"},
    "deprecated": {"deprecated", "archived", "external"},
    "archived": {"archived"},
    "external": {"external"},
}
DISPOSITION_LIFECYCLES = {
    # Estate disposition and runtime activation are separate gates. "Keep"
    # means the capability belongs in Stack; it must not turn an unvalidated
    # candidate into an active runtime entry as a side effect of the audit.
    "keep": lambda source: source,
    "hold": lambda source: source,
    "demote": lambda source: "candidate",
    "merge": lambda _source: "deprecated",
    "move": lambda _source: "external",
    "archive": lambda _source: "archived",
}
REVIEW_STATES = {"unreviewed", "reviewed", "approved"}
TARGETED_DISPOSITIONS = {"merge", "move"}
REVIEW_DISPOSITIONS = set(DISPOSITION_LIFECYCLES)


def canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MigrationError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise MigrationError(f"{path} must contain a JSON object")
    return value


def catalog_by_skill_path(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for capability in catalog.get("capabilities", []):
        source = capability.get("source", {})
        path = source.get("skill_path") if isinstance(source, dict) else None
        if not isinstance(path, str):
            continue
        if path in records:
            raise MigrationError(f"catalog collision for source {path}")
        records[path] = capability
    return records


def build_draft_map(audit: dict[str, Any], catalog: dict[str, Any], *, audit_path: str, catalog_path: str) -> dict[str, Any]:
    """Create the deterministic, deliberately unapproved U3 decision surface."""
    catalog_sources = catalog_by_skill_path(catalog)
    decisions = []
    for record in sorted(audit.get("capabilities", []), key=lambda item: (item["canonical_name"], item["skill_path"])):
        source = catalog_sources.get(record["skill_path"])
        if source is None:
            raise MigrationError(f"audit source is not registered in catalog: {record['skill_path']}")
        disposition = record["proposed_disposition"]
        lifecycle_from = source["lifecycle"]
        decisions.append({
            "source": {
                "canonical_name": record["canonical_name"],
                "skill_path": record["skill_path"],
                "manifest_path": record.get("manifest_path"),
            },
            "proposed_disposition": disposition,
            "proposed_destination": record["destination"],
            "reason": record["reason"],
            "review_state": "unreviewed",
            "review_decision": None,
            "review_rationale": None,
            "lifecycle": {"from": lifecycle_from, "to": DISPOSITION_LIFECYCLES[disposition](lifecycle_from)},
            "destination_target": None,
            "merge_target": None,
            "compatibility_alias": None,
            "consumer_receipt": None,
        })
    return {
        "schema_version": "capability-migration/v1",
        "migration_id": "2026-07-18-estate-refactor",
        "status": "draft",
        "human_approval": "not granted",
        "non_mutating": True,
        "source": {
            "audit_path": audit_path,
            "audit_digest": digest(audit),
            "audit_policy_digest": audit.get("policy", {}).get("digest"),
            "catalog_path": catalog_path,
            "catalog_digest": digest(catalog),
        },
        "capability_count": len(decisions),
        "decisions": decisions,
    }


def _duplicates(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def _effective_disposition(decision: dict[str, Any], index: int, errors: list[str]) -> str | None:
    proposed = decision.get("proposed_disposition")
    reviewed = decision.get("review_state") in {"reviewed", "approved"}
    final = decision.get("review_decision")
    if not reviewed:
        if final is not None:
            errors.append(f"decision {index} has a review_decision while unreviewed")
        return proposed
    if final not in REVIEW_DISPOSITIONS:
        errors.append(f"decision {index} requires a valid review_decision")
        return None
    if final != proposed and (not isinstance(decision.get("review_rationale"), str) or not decision["review_rationale"].strip()):
        errors.append(f"decision {index} override requires review_rationale")
    return final


def _require_review_details(decision: dict[str, Any], index: int, disposition: str | None = None) -> list[str]:
    errors: list[str] = []
    disposition = disposition or decision.get("review_decision") or decision["proposed_disposition"]
    source = decision["source"]["canonical_name"]
    if disposition == "move" and (not isinstance(decision.get("destination_target"), str) or not decision["destination_target"]):
        errors.append(f"decision {index} ({source}) missing destination_target")
    if disposition == "merge":
        target = decision.get("merge_target")
        if not isinstance(target, str) or not target:
            errors.append(f"decision {index} ({source}) missing merge_target")
        elif target == source:
            errors.append(f"decision {index} ({source}) merge_target cannot equal source")
        alias = decision.get("compatibility_alias")
        if not isinstance(alias, dict) or alias.get("alias") != source or alias.get("canonical_target") != target:
            errors.append(f"decision {index} ({source}) missing valid compatibility_alias")
    if disposition in TARGETED_DISPOSITIONS:
        receipt = decision.get("consumer_receipt")
        if not isinstance(receipt, dict) or not all(isinstance(receipt.get(field), str) and receipt[field] for field in ("receipt_id", "consumer", "status")) or receipt.get("status") != "verified":
            errors.append(f"decision {index} ({source}) missing valid consumer_receipt")
    return errors


def validate_migration(migration: dict[str, Any], audit: dict[str, Any], catalog: dict[str, Any], *, apply: bool = False) -> None:
    """Validate source coverage, review prerequisites, and safe catalog transitions."""
    errors: list[str] = []
    source = migration.get("source", {})
    expected_digests = {
        "audit_digest": digest(audit),
        "catalog_digest": digest(catalog),
        "audit_policy_digest": audit.get("policy", {}).get("digest"),
    }
    for key, expected in expected_digests.items():
        if source.get(key) != expected:
            errors.append(f"source {key} does not match current input")
    if migration.get("capability_count") != len(audit.get("capabilities", [])):
        errors.append("capability_count does not match audit")

    audit_records = {(row["canonical_name"], row["skill_path"]): row for row in audit.get("capabilities", [])}
    catalog_sources = catalog_by_skill_path(catalog)
    decisions = migration.get("decisions")
    if not isinstance(decisions, list):
        raise MigrationError("decisions must be a list")
    seen_sources: list[str] = []
    seen_names: list[str] = []
    targets: list[str] = []
    aliases: list[str] = []
    for index, decision in enumerate(decisions):
        source_record = decision.get("source", {})
        name, skill_path = source_record.get("canonical_name"), source_record.get("skill_path")
        if not isinstance(name, str) or not isinstance(skill_path, str):
            errors.append(f"decision {index} has invalid source")
            continue
        seen_names.append(name)
        seen_sources.append(skill_path)
        audit_record = audit_records.get((name, skill_path))
        if audit_record is None:
            errors.append(f"decision {index} has unregistered source {name} ({skill_path})")
            continue
        catalog_record = catalog_sources.get(skill_path)
        if catalog_record is None:
            errors.append(f"decision {index} source missing from catalog: {skill_path}")
            continue
        disposition = decision.get("proposed_disposition")
        if disposition != audit_record["proposed_disposition"]:
            errors.append(f"decision {index} disposition differs from audit")
        if decision.get("proposed_destination") != audit_record["destination"]:
            errors.append(f"decision {index} destination differs from audit")
        review_state = decision.get("review_state")
        if review_state not in REVIEW_STATES:
            errors.append(f"decision {index} has invalid review_state")
        effective_disposition = _effective_disposition(decision, index, errors)
        lifecycle = decision.get("lifecycle", {})
        lifecycle_from, lifecycle_to = lifecycle.get("from"), lifecycle.get("to")
        if lifecycle_from != catalog_record.get("lifecycle"):
            errors.append(f"decision {index} lifecycle.from differs from catalog")
        if lifecycle_to not in LIFECYCLE_TRANSITIONS.get(lifecycle_from, set()):
            errors.append(f"decision {index} has forbidden lifecycle transition")
        expected_to = DISPOSITION_LIFECYCLES.get(effective_disposition, lambda _: None)(lifecycle_from)
        if lifecycle_to != expected_to:
            errors.append(f"decision {index} lifecycle does not match reviewed disposition")
        # A reviewed disposition records the human decision while preserving a
        # later apply gate for destinations, compatibility aliases, and live
        # consumer receipts. Only apply-approved decisions must carry those
        # mutable-world prerequisites.
        if review_state == "approved" and effective_disposition in TARGETED_DISPOSITIONS:
            errors.extend(_require_review_details(decision, index, effective_disposition))
        if effective_disposition == "move" and isinstance(decision.get("destination_target"), str):
            targets.append("destination:" + decision["destination_target"])
        if effective_disposition == "merge" and isinstance(decision.get("merge_target"), str):
            targets.append("merge:" + decision["merge_target"])
        alias = decision.get("compatibility_alias")
        if isinstance(alias, dict) and isinstance(alias.get("alias"), str):
            aliases.append(alias["alias"])

    for duplicate in _duplicates(seen_sources):
        errors.append(f"source collision: {duplicate}")
    for duplicate in _duplicates(seen_names):
        errors.append(f"canonical name collision: {duplicate}")
    for duplicate in _duplicates(targets):
        errors.append(f"destination collision: {duplicate}")
    for duplicate in _duplicates(aliases):
        errors.append(f"compatibility alias collision: {duplicate}")
    if set(seen_sources) != set(catalog_sources):
        errors.append("migration decisions do not cover every catalog source exactly once")
    if set((name, path) for name, path in zip(seen_names, seen_sources)) != set(audit_records):
        errors.append("migration decisions do not cover every audit capability exactly once")

    if apply:
        if migration.get("status") != "approved" or migration.get("human_approval") != "approved":
            errors.append("apply requires explicit approved migration status and human approval")
        for index, decision in enumerate(decisions):
            if decision.get("review_state") != "approved":
                errors.append(f"decision {index} is not apply-approved")
            errors.extend(_require_review_details(decision, index, decision.get("review_decision")))
    if errors:
        raise MigrationError("\n".join(sorted(set(errors))))


def post_migration_actions(migration: dict[str, Any], post_catalog: dict[str, Any]) -> list[dict[str, str]]:
    """Return remaining actions; an already-applied matching state yields an empty list."""
    post_by_name = {item["canonical_name"]: item for item in post_catalog.get("capabilities", [])}
    remaining = []
    for decision in migration["decisions"]:
        name = decision["source"]["canonical_name"]
        expected = decision["lifecycle"]["to"]
        actual = post_by_name.get(name)
        if expected == "external":
            if actual is not None:
                remaining.append({"canonical_name": name, "action": "remove-externalized-catalog-entry"})
        elif actual is None or actual.get("lifecycle") != expected:
            remaining.append({"canonical_name": name, "action": "apply-catalog-transition"})
    return remaining


def dry_run_actions(migration: dict[str, Any]) -> list[dict[str, Any]]:
    actions = []
    for decision in migration["decisions"]:
        source = decision["source"]
        action = {
            "canonical_name": source["canonical_name"],
            "source": source["skill_path"],
            "proposed_disposition": decision["proposed_disposition"],
            "review_decision": decision.get("review_decision"),
            "proposed_destination": decision["proposed_destination"],
            "catalog_lifecycle": decision["lifecycle"],
        }
        if decision["proposed_disposition"] == "move":
            action["required_before_apply"] = ["destination_target", "consumer_receipt"]
        elif decision["proposed_disposition"] == "merge":
            action["required_before_apply"] = ["merge_target", "compatibility_alias", "consumer_receipt"]
        actions.append(action)
    return actions


def build_review_packet(migration: dict[str, Any], *, batch_index: int = 1, decision_cap: int = 20) -> dict[str, Any]:
    """Return the bounded item-level decision packet that can change source shape."""
    consequential = [
        decision
        for decision in migration["decisions"]
        if decision["proposed_disposition"] in {"move", "merge", "demote", "archive", "hold"}
    ]
    consequential.sort(
        key=lambda decision: (
            {"move": 0, "merge": 1, "demote": 2, "archive": 3, "hold": 4}[decision["proposed_disposition"]],
            decision["source"]["canonical_name"],
        )
    )
    if decision_cap < 1 or decision_cap > 20:
        raise MigrationError("review decision cap must be between 1 and 20")
    batch_count = max(1, (len(consequential) + decision_cap - 1) // decision_cap)
    if batch_index < 1 or batch_index > batch_count:
        raise MigrationError(f"review batch must be between 1 and {batch_count}")
    start = (batch_index - 1) * decision_cap
    selected = consequential[start:start + decision_cap]
    counts = Counter(decision["proposed_disposition"] for decision in migration["decisions"])
    fully_reviewed = all(decision.get("review_state") != "unreviewed" for decision in consequential)
    return {
        "schema_version": "capability-migration-review/v1",
        "migration_id": migration["migration_id"],
        "status": "review-recorded" if fully_reviewed else "awaiting-human-review",
        "human_approval": migration.get("human_approval", "not granted"),
        "audit_policy_digest": migration["source"]["audit_policy_digest"],
        "batch_index": batch_index,
        "batch_count": batch_count,
        "decision_cap": decision_cap,
        "consequential_decision_count": len(selected),
        "total_consequential_decision_count": len(consequential),
        "remaining_consequential_decision_count": max(0, len(consequential) - start - len(selected)),
        "held_pending_evidence_count": counts["hold"],
        "unchanged_keep_count": counts["keep"],
        "decisions": selected,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migration", type=Path)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--build-draft-out", type=Path, help="write a fresh non-mutating draft from the current audit and catalog")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Validate apply readiness only; never changes files.")
    parser.add_argument("--post-catalog", type=Path)
    parser.add_argument("--review-packet-out", type=Path)
    parser.add_argument("--review-batch", type=int, default=1)
    args = parser.parse_args()
    try:
        audit, catalog = load_json(args.audit), load_json(args.catalog)
        if args.build_draft_out:
            if args.migration or args.apply or args.post_catalog:
                raise MigrationError("--build-draft-out cannot be combined with migration/apply/post-catalog")
            migration = build_draft_map(
                audit,
                catalog,
                audit_path=args.audit.as_posix(),
                catalog_path=args.catalog.as_posix(),
            )
            validate_migration(migration, audit, catalog)
            args.build_draft_out.parent.mkdir(parents=True, exist_ok=True)
            args.build_draft_out.write_text(canonical_json(migration), encoding="utf-8")
        else:
            if not args.migration:
                raise MigrationError("--migration is required unless --build-draft-out is used")
            migration = load_json(args.migration)
        validate_migration(migration, audit, catalog, apply=args.apply)
        if args.review_packet_out:
            args.review_packet_out.parent.mkdir(parents=True, exist_ok=True)
            args.review_packet_out.write_text(canonical_json(build_review_packet(migration, batch_index=args.review_batch)), encoding="utf-8")
        if args.post_catalog:
            result: dict[str, Any] = {"remaining_actions": post_migration_actions(migration, load_json(args.post_catalog))}
        elif args.dry_run:
            result = {"dry_run": True, "actions": dry_run_actions(migration)}
        else:
            result = {"valid": True}
        print(canonical_json(result), end="")
        return 0
    except MigrationError as error:
        print(f"migration validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
