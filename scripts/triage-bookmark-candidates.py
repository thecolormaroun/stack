#!/usr/bin/env python3
"""Rank private bookmark observations into a redacted, review-only packet.

The input is owner-local evidence.  The output is safe to attach to a review:
it contains opaque identifiers and decision metadata only, never bookmark text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DISPOSITIONS = (
    "no-action", "evidence-attachment", "reference-update", "skill-update",
    "new-candidate-skill", "upstream-import-update",
)
PRIVATE_KEY_PARTS = ("url", "title", "note", "content", "excerpt", "path", "raw", "credential", "token")
INTAKE_ID_RE = re.compile(r"^intake_[A-Za-z0-9_-]{16,128}$")
SOURCE_PIN_RE = re.compile(r"^[0-9a-f]{40,64}$")


class TriageError(ValueError):
    pass


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def opaque(value: str) -> str:
    return "intake_" + hashlib.sha256(value.encode()).hexdigest()[:20]


def contains_private_field(value: object, prefix: str = "") -> list[str]:
    leaks: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            name = str(key).lower()
            location = f"{prefix}.{key}" if prefix else str(key)
            if any(part in name for part in PRIVATE_KEY_PARTS):
                leaks.append(location)
            leaks.extend(contains_private_field(child, location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            leaks.extend(contains_private_field(child, f"{prefix}[{index}]"))
    elif isinstance(value, str) and ("http://" in value or "https://" in value or value.startswith("/")):
        leaks.append(prefix or "value")
    return leaks


def score(candidate: dict[str, Any]) -> int:
    values = candidate.get("scores", {})
    if not isinstance(values, dict):
        return 0
    def number(key: str) -> int:
        value = values.get(key, 0)
        return int(value) if isinstance(value, (int, float)) else 0
    return number("leverage") + number("novelty") + number("evidence") - number("implementation_cost") - number("evaluation_cost")


def catalog_index(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = catalog.get("capabilities", [])
    if not isinstance(entries, list):
        raise TriageError("catalog capabilities must be a list")
    indexed: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if isinstance(entry, dict):
            identity = entry.get("provenance", {}).get("source_identity")
            if isinstance(identity, str):
                indexed[identity] = entry
    return indexed


def disposition(candidate: dict[str, Any], catalog: dict[str, dict[str, Any]], accepted_licenses: set[str]) -> tuple[str, str | None, dict[str, Any] | None]:
    identity = candidate.get("source_identity")
    if not isinstance(identity, str) or not identity:
        return "no-action", "missing-source-identity", None
    existing = catalog.get(identity)
    if candidate.get("relevance") == "irrelevant":
        return "no-action", "outside-design-build-scope", existing
    is_repository = candidate.get("kind") == "repository"
    if is_repository and candidate.get("license") not in accepted_licenses:
        return "blocked-import", "license-unacceptable", existing
    if existing:
        return ("evidence-attachment" if candidate.get("evidence_count", 0) else "no-action"), None, existing
    requested = candidate.get("requested_disposition")
    if requested in DISPOSITIONS:
        return requested, None, None
    if is_repository:
        return "upstream-import-update", None, None
    return "reference-update", None, None


def safe_record(candidate: dict[str, Any], rank: int, chosen: str, blocker: str | None, existing: dict[str, Any] | None) -> dict[str, Any]:
    identity = candidate.get("intake_id")
    if not isinstance(identity, str) or not INTAKE_ID_RE.fullmatch(identity):
        raise TriageError("candidate intake_id must be a strict opaque identifier")
    source_pin = candidate.get("source_pin")
    if not isinstance(source_pin, str) or not SOURCE_PIN_RE.fullmatch(source_pin):
        raise TriageError("candidate source_pin must be 40-64 lowercase hexadecimal characters")
    record: dict[str, Any] = {
        "rank": rank,
        "intake_id": identity,
        "source_id": str(candidate.get("source_id", "unknown")),
        "source_pin": source_pin,
        "disposition": chosen,
        "score": score(candidate),
        "review_state": "blocked-pending-human-review",
        "relevance": candidate.get("relevance", "unknown"),
    }
    hermes_intake_id = candidate.get("hermes_intake_id")
    if hermes_intake_id is not None:
        if not isinstance(hermes_intake_id, str) or not INTAKE_ID_RE.fullmatch(hermes_intake_id):
            raise TriageError("candidate hermes_intake_id must be a strict opaque identifier")
        record["hermes_intake_id"] = hermes_intake_id
    if blocker:
        record["blocker"] = blocker
    if existing:
        provenance = existing.get("provenance", {})
        record["existing_capability"] = existing.get("canonical_name")
        record["prior_provenance"] = provenance.get("source_identity")
        record["evidence_update"] = chosen == "evidence-attachment"
        evidence_ids = candidate.get("evidence_ids", [])
        if isinstance(evidence_ids, list) and all(isinstance(item, str) and item.startswith("evidence_") for item in evidence_ids):
            record["evidence_ids"] = sorted(set(evidence_ids))
    return {key: value for key, value in record.items() if value is not None}


def triage(candidates: list[dict[str, Any]], catalog: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    if not all(isinstance(candidate, dict) for candidate in candidates):
        raise TriageError("candidates must be objects")
    accepted = set(policy.get("accepted_licenses", []))
    indexed = catalog_index(catalog)
    ranked = sorted(candidates, key=lambda candidate: (-score(candidate), str(candidate.get("source_identity", ""))))
    records = []
    for rank, candidate in enumerate(ranked, start=1):
        chosen, blocker, existing = disposition(candidate, indexed, accepted)
        records.append(safe_record(candidate, rank, chosen, blocker, existing))
    cap = policy.get("decision_cap", 3)
    if not isinstance(cap, int) or cap < 1:
        raise TriageError("policy decision_cap must be a positive integer")
    packet = {
        "schema_version": 1,
        "packet_kind": "bookmark-candidate-review",
        "policy_digest": digest(policy),
        "decision_cap": cap,
        "review_gates": policy.get("review_gates", []),
        "no_change": not records,
        "candidates": records[:cap],
        "deferred": records[cap:],
    }
    leaks = contains_private_field(packet)
    if leaks:
        raise TriageError("public packet leak check failed: " + ", ".join(leaks))
    return packet


def hermes_callback_argv(script: str, record: dict[str, Any]) -> list[str]:
    """Return the future Hermes disposition CLI argv for one redacted record."""
    intake_id = record.get("hermes_intake_id")
    if not isinstance(intake_id, str) or not INTAKE_ID_RE.fullmatch(intake_id):
        raise TriageError("callback requires a strict opaque intake_id")
    disposition = record.get("disposition")
    outcome = "blocked" if disposition == "blocked-import" else "no-action" if disposition == "no-action" else "proposed"
    return [script, "disposition", "--intake-id", intake_id, "--state", outcome]


def hermes_callback_records(packet: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only explicit Hermes submissions backed by Hermes inbox rows."""
    records = packet.get("candidates", [])
    if not isinstance(records, list):
        raise TriageError("callback packet candidates must be a list")
    return [
        record for record in records
        if isinstance(record, dict) and isinstance(record.get("hermes_intake_id"), str)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True, help="owner-local candidate JSON list")
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=ROOT / "config/capability-activation-policy.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        candidates = load_json(args.candidates)
        if isinstance(candidates, dict):
            candidates = candidates.get("candidates", [])
        packet = triage(candidates, load_json(args.catalog), load_json(args.policy))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"triage failed closed: {error}", file=sys.stderr)
        return 2
    args.out.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
