#!/usr/bin/env python3
"""Group untriaged observations into redacted canonical candidates."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
MATERIALIZATION_POLICY_VERSION = "canonical-group-v2"
INTAKE_ID_RE = re.compile(r"^intake_[A-Za-z0-9_-]{16,128}$")
DESIGN_TERMS = {
    "accessibility", "animation", "component", "css", "design", "figma", "frontend",
    "icon", "interaction", "interface", "layout", "motion", "product", "typography", "ui", "ux", "visual",
}
BUILD_TERMS = {
    "agent", "api", "architecture", "build", "code", "coding", "database", "debug", "developer",
    "engineering", "framework", "github", "library", "programming", "repository", "sdk", "software", "test", "tool",
}
TEXT_KEYS = {
    "article_text", "article_title", "description", "language", "name", "savedTitle",
    "text", "title", "topics",
}
SOURCE_PRIORITY = {
    "github-linked": 0,
    "github-stars": 1,
    "hermes-links": 2,
    "field-theory": 3,
    "arc-sidebar": 4,
}


def source_pin(raw_json: str, revision: str, policy_digest: str) -> str:
    return hashlib.sha256((raw_json + "\0" + revision + "\0" + policy_digest).encode()).hexdigest()


def canonical_group_pin(pins: list[str], curation_policy_digest: str = "") -> str:
    material = [MATERIALIZATION_POLICY_VERSION, curation_policy_digest, *sorted(set(pins))]
    return hashlib.sha256("\0".join(material).encode()).hexdigest()


def opaque(prefix: str, value: str) -> str:
    return prefix + hashlib.sha256(value.encode()).hexdigest()[:24]


def raw_text(raw: object) -> str:
    if not isinstance(raw, dict):
        return ""
    values: list[str] = []
    for key in TEXT_KEYS:
        value = raw.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(str(item) for item in value if isinstance(item, (str, int, float)))
    return " ".join(values).lower()


def relevance(observations: list[dict]) -> tuple[str, int]:
    text = " ".join(raw_text(row["raw"]) for row in observations)
    tokens = set(re.findall(r"[a-z][a-z0-9-]+", text))
    hits = len(tokens & (DESIGN_TERMS | BUILD_TERMS))
    if hits:
        return "relevant", hits
    return ("irrelevant", 0) if text.strip() else ("unknown", 0)


def normalized_license(raw: object) -> str | None:
    if isinstance(raw, str) and raw.strip() and raw.strip().upper() not in {"NOASSERTION", "OTHER"}:
        return raw.strip()
    if isinstance(raw, dict):
        for key in ("spdx_id", "spdx", "key", "name"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip() and value.upper() not in {"NOASSERTION", "OTHER"}:
                return value.strip()
    return None


def repository_license(observations: list[dict]) -> str | None:
    values = {
        value
        for row in observations
        if (value := normalized_license(row["raw"].get("license") if isinstance(row["raw"], dict) else None))
    }
    return next(iter(values)) if len(values) == 1 else None


def is_repository(canonical: str, observations: list[dict]) -> bool:
    if any(row["source_id"] in {"github-stars", "github-linked"} for row in observations):
        return True
    try:
        parts = urlsplit(canonical)
    except ValueError:
        return False
    segments = [part for part in parts.path.split("/") if part]
    return parts.hostname == "github.com" and len(segments) == 2


def grouped_rows(connection: sqlite3.Connection) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    rows = connection.execute("""
      SELECT c.canonical, c.intake_id, o.source_id, o.source_revision,
             o.content_digest, o.policy_digest, o.raw_json
      FROM observations o JOIN canonical_items c ON c.canonical = o.canonical
      ORDER BY c.canonical, o.id
    """)
    for canonical, intake_id, source_id, revision, content_digest, policy_digest, raw_json in rows:
        groups[canonical].append({
            "intake_id": intake_id,
            "source_id": source_id,
            "revision": revision,
            "content_digest": content_digest,
            "policy_digest": policy_digest,
            "raw_json": raw_json,
            "raw": json.loads(raw_json),
            "observation_pin": source_pin(raw_json, revision, policy_digest),
        })
    return groups


def materialize(
    ledger: Path,
    apply: bool = False,
    selected_pins: set[str] | None = None,
    curation_policy_digest: str = "",
) -> list[dict]:
    connection = sqlite3.connect(ledger)
    try:
        has_state = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='triage_materializations'"
        ).fetchone() is not None
        candidates: list[dict] = []
        pins: list[tuple[str, str]] = []
        for canonical, observations in sorted(grouped_rows(connection).items()):
            pin = canonical_group_pin([row["observation_pin"] for row in observations], curation_policy_digest)
            if has_state and connection.execute(
                "SELECT 1 FROM triage_materializations WHERE source_pin = ?", (pin,)
            ).fetchone():
                continue
            intake_id = observations[0]["intake_id"]
            if not isinstance(intake_id, str) or not INTAKE_ID_RE.fullmatch(intake_id):
                raise ValueError("ledger contains invalid intake_id")
            source_ids = sorted({row["source_id"] for row in observations})
            primary_source = min(source_ids, key=lambda value: (SOURCE_PRIORITY.get(value, 99), value))
            relevance_state, keyword_hits = relevance(observations)
            repository = is_repository(canonical, observations)
            evidence_ids = sorted({
                opaque("evidence_", row["source_id"] + "\0" + row["observation_pin"])
                for row in observations
            })
            candidate = {
                "intake_id": intake_id,
                "source_id": primary_source,
                "source_identity": "canonical:" + hashlib.sha256(canonical.encode()).hexdigest(),
                "source_pin": pin,
                "kind": "repository" if repository else "reference",
                "relevance": relevance_state,
                "evidence_count": len(evidence_ids),
                "evidence_ids": evidence_ids,
                "scores": {
                    "leverage": min(5, keyword_hits),
                    "novelty": 1,
                    "evidence": min(5, len(source_ids) + (1 if repository else 0)),
                    "implementation_cost": 2 if repository else 1,
                    "evaluation_cost": 2 if repository else 1,
                },
            }
            if repository:
                candidate["license"] = repository_license(observations) or "unknown"
            hermes_ids = {
                raw_id
                for row in observations
                if row["source_id"] == "hermes-links" and isinstance(row["raw"], dict)
                for raw_id in [row["raw"].get("intake_id")]
                if isinstance(raw_id, str) and INTAKE_ID_RE.fullmatch(raw_id)
            }
            if len(hermes_ids) == 1:
                candidate["hermes_intake_id"] = next(iter(hermes_ids))
            elif len(hermes_ids) > 1:
                raise ValueError("canonical item has conflicting Hermes intake identifiers")
            candidates.append(candidate)
            pins.append((pin, intake_id))
        if apply:
            if selected_pins is not None:
                pins = [row for row in pins if row[0] in selected_pins]
            with connection:
                connection.execute("""CREATE TABLE IF NOT EXISTS triage_materializations (
                  source_pin TEXT PRIMARY KEY, intake_id TEXT NOT NULL, materialized_at TEXT NOT NULL
                )""")
                connection.executemany(
                    "INSERT OR IGNORE INTO triage_materializations VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                    pins,
                )
        return candidates
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=ROOT / "config/capability-activation-policy.json")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--apply", action="store_true", help="mark emitted canonical candidate revisions as triaged")
    parser.add_argument("--packet", type=Path, help="with --apply, mark only the packet's presented candidates")
    args = parser.parse_args(argv)
    try:
        selected_pins = None
        if args.packet:
            if not args.apply:
                raise ValueError("--packet requires --apply")
            packet = json.loads(args.packet.read_text(encoding="utf-8"))
            selected_pins = {
                record["source_pin"]
                for record in packet.get("candidates", [])
                if isinstance(record, dict) and isinstance(record.get("source_pin"), str)
            }
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
        if not isinstance(policy, dict):
            raise ValueError("curation policy must be an object")
        policy_digest = hashlib.sha256(
            json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        candidates = materialize(args.ledger, args.apply, selected_pins, policy_digest)
    except (OSError, sqlite3.Error, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"materialization failed closed: {error}", file=sys.stderr)
        return 2
    encoded = json.dumps(candidates, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.write_text(encoded, encoding="utf-8")
    else:
        sys.stdout.write(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
