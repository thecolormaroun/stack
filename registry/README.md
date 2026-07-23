# Capability registry

`skills/**/capability.json` is the authoritative, capability-local contract. `capabilities.json` is generated output; do not edit it directly.

Build or verify it from the repository root:

```sh
python3 scripts/build-capability-registry.py
python3 scripts/build-capability-registry.py --check
```

The catalog is deterministic: it contains no build timestamp, machine path, or runtime compiler output. `--check` fails if a local manifest changed without rebuilding the aggregate.

## Inclusion boundary

An active Stack capability must materially improve designing or building software. Orchestration belongs only when it directly supports planning, delegating, reviewing, verifying, or shipping that work. General personal operations, finance, household, shopping, file-organization, and knowledge-management workflows remain outside this product identity unless they meet that direct support test.

Seeded entries are deliberately `candidate` with `audit_status: pending` and `hold-pending-evidence`. They are inventory records, not a keep, archive, move, activation, or runtime-publication decision. Only a reviewed, validated `active` capability may name a publish target.

Private overlays use opaque identifiers only. Private paths, URLs, titles, excerpts, and payloads must never appear in this public registry or generated catalog.
