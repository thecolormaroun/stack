---
name: stack-sync
description: |
  Audit Stack upstream maintenance, prepare one isolated review candidate, or
  verify package/runtime readiness without touching active work.
---

# stack-sync

Resolve the Stack checkout from `STACK_REPO` or the current Git root:

```bash
STACK_REPO_DIR="${STACK_REPO:-$(git rev-parse --show-toplevel)}"
cd "${STACK_REPO_DIR}"
```

Run only the maintenance tools shipped by this repository:

1. `python3 scripts/stack-maintenance.py audit --observe-upstreams` performs
   the unattended source audit and writes an owner-only receipt. Pass a
   protected vendor path only with its current verified hold artifact.
2. `python3 scripts/sync-upstreams.py` verifies immutable metadata, the
   repository bundle digest, and last-known-good pins without downloading or
   staging anything.
3. `python3 scripts/stack-doctor.py` checks family, command, package, and runtime
   readiness.
4. `python3 scripts/bootstrap-stack.py` performs the read-only bootstrap gate.

For a scheduled maintenance run, do not ask the operator routine questions.
Run the audit, report the receipt, and stop with the exact classified blocker
when safety or provenance is ambiguous. If the audit reports upstream drift,
do not author or edit proposal bytes. Give the exact persisted owner-only audit
receipt to `prepare`:

```bash
PROPOSAL_DIR="$(mktemp -d "${TMPDIR:-/tmp}/stack-maintenance-proposal.XXXXXX")"
STAGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/stack-maintenance-stage.XXXXXX")"
python3 scripts/stack-maintenance.py prepare \
  --audit-receipt "${AUDIT_RECEIPT}" \
  --proposal-dir "${PROPOSAL_DIR}" \
  --stage-dir "${STAGE_DIR}" \
  --github
```

The runner checks that the receipt came from its receipt store, clones the
receipt's exact audited Stack base, and invokes that base's checked-in
`scripts/materialize-maintenance-proposal.py` itself. External proposal
manifests are not accepted. The materializer follows only the curated import
rules in
`registry/maintenance-imports.json` and emits a receipt-bound,
content-addressed manifest. The runner then validates payload hashes, the diff
allowlist, complete repository gates, and canonical PR lineage before any
remote write. If an upstream change requires a new import rule, license
decision, capability activation, deletion, or other judgment not already
encoded in Stack, leave it `awaiting_approval`; do not invent policy.

If the user explicitly requests installation, use the documented
`scripts/bootstrap-stack.py --install` flow with explicit deployment, staging,
and receipt directories. That path owns the deployment-local `.stack-packages`
cache and atomic runtime install. Do not emulate the former external workspace
scripts; they are not part of this repository.

## What this skill owns

- repository and package-integrity verification
- owner-only receipts, lease/circuit handling, and upstream drift audit
- isolated proposal validation and one canonical draft maintenance PR
- exact-commit, deterministic materialization of existing curated imports
- clean-clone bootstrap readiness
- explicit, approval-aware runtime installation
- reporting missing packages, drift, or failed health gates

## Output

Report the receipt identity, terminal classification, semantic input/output
digests, exact PR state when present, Stack checkout used, and any blocker.
Archive the task only when the receipt says `archive_eligible`; keep
`awaiting_approval`, `blocked`, `partial`, and `failed` tasks visible. A
read-only verification or prepared PR is not an installation.
