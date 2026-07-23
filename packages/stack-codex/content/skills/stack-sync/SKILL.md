---
name: stack-sync
description: |
  Verify Stack package integrity and runtime readiness from a Stack checkout,
  then optionally run Stack's explicit bootstrap/install path.
---

# stack-sync

Resolve the Stack checkout from `STACK_REPO` or the current Git root:

```bash
STACK_REPO_DIR="${STACK_REPO:-$(git rev-parse --show-toplevel)}"
cd "${STACK_REPO_DIR}"
```

Run only the maintenance tools shipped by this repository:

1. `python3 scripts/sync-upstreams.py` verifies immutable metadata, the
   repository bundle digest, and last-known-good pins without downloading or
   staging anything.
2. `python3 scripts/stack-doctor.py` checks family, command, package, and runtime
   readiness.
3. `python3 scripts/bootstrap-stack.py` performs the read-only bootstrap gate.

If the user explicitly requests installation, use the documented
`scripts/bootstrap-stack.py --install` flow with explicit deployment, staging,
and receipt directories. That path owns the deployment-local `.stack-packages`
cache and atomic runtime install. Do not emulate the former external workspace
scripts; they are not part of this repository.

## What this skill owns

- repository and package-integrity verification
- clean-clone bootstrap readiness
- explicit, approval-aware runtime installation
- reporting missing packages, drift, or failed health gates

## Output

Report the Stack checkout used, checks run, package health, whether an explicit
install was requested and completed, and any blocked follow-up. A read-only
verification is not an installation.
