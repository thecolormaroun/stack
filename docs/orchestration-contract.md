# Orchestration contract

Stack gives Claude and Codex one local control-plane contract. A workflow run is keyed by a stable, canonical project identity, while plans, patches, handoffs, review packets, QA evidence, branches, and worktrees remain in that project. The control database contains only coordination metadata and artifact paths.

`scripts/stack-run-state.py` is the reference adapter. Its database defaults to `~/.local/state/stack/runs.sqlite3`; adapters and tests pass `--db` (or `STACK_RUN_STATE_DB`) to select an owner-local database. It has no dependencies beyond Python's standard library and never invokes an agent, changes a repository, or performs an external mutation.

Before opening SQLite, the adapter creates or verifies the immediate state
directory as current-user-owned mode `0700`, rejects symlinked state directories
or databases, and creates or verifies the database as a current-user-owned
regular file at mode `0600`. SQLite WAL and shared-memory sidecars are also
owner-only `0600`. Ownership or mode drift fails closed instead of opening the
store.

## Lifecycle and ownership

Runs move from `planned` to `dispatched`, then `implemented`, `reviewed`, `verified`, `awaiting_approval`, `shipped`, and `receipted`. A failed child makes the run `blocked`; `resume` returns a blocked or unreceipted cancelled run to `dispatched`. Cancellation releases outstanding leases. `receipted` is immutable.

Every child declares an owner, model role, workspace, optional worktree, and checkpoints. Only the run owner adds children. Fan-out is capped at the run's `max_children` (1–16), and nested child fan-out is rejected. A child in `completed` state can never be claimed or duplicated.

Claims use `BEGIN IMMEDIATE` SQLite transactions. A claim is exclusive, has an expiry, and transactional recovery changes only expired `leased` rows back to `pending`; completed rows are untouched. A worker must hold its lease to checkpoint or finish a child.

## Gates and approval

Review, QA, and ship are distinct gates, each requiring evidence. The ship gate cannot pass if any child failed or either review/QA is not passed. `ship` additionally requires explicit approval for approval-required runs. This contract records approval; it does not grant permission to push, merge, deploy, buy, schedule, or mutate any external system.

Only `shipped` and `cancelled` runs can write the one terminal receipt. The receipt stores a JSON snapshot of the run, children, checkpoints, gates, approval state, failures, workspace/worktree references, and terminal state. It is local metadata, not a replacement for project artifacts.

Example local dry run:

```sh
STACK_RUN_DEMO_DIR="$(mktemp -d)"
python3 scripts/stack-run-state.py --db "$STACK_RUN_DEMO_DIR/runs.sqlite3" create run-1 project:example owner /path/to/project
python3 scripts/stack-run-state.py --db "$STACK_RUN_DEMO_DIR/runs.sqlite3" add-child run-1 build implementer codex owner /path/to/project
```
