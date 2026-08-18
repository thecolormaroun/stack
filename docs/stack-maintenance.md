# Stack maintenance runbook

This runbook defines the source-of-truth, safety, and approval boundaries for
Stack maintenance automation. It covers the read-only baseline reconciliation
and the later audit/prepare lane; it does not itself authorize a scheduler,
cleanup, merge, installation, runtime publication, or plugin change.

## Purpose and authority

Stack is the canonical owner of the maintenance runner, policy, source
inventory, tests, and runbook. A Codex automation record or compatibility
launcher is a thin delegate, not a second source of truth. The legacy updater
does not regain ownership during repair.

Use this authority order when evidence disagrees:

1. Maroun's current approval and task boundaries.
2. Git repository state, immutable upstream references, catalog manifests, and
   the runtime publication contract.
3. Owner-only receipts and generated evidence, which explain what was
   observed but cannot override canonical state or a failed verification gate.

The repository-owned catalog manifests are authoritative for capability
identity and lifecycle. `upstreams.lock.json` is authoritative for pinned
provider references. Git and the hosting service are authoritative for commit,
branch, worktree, and pull-request state. Runtime publication is proved only
by the receipt and target checks described in
[`docs/runtime-publication.md`](runtime-publication.md); a maintenance receipt
is not publication proof.

The reusable packet shape is
[`templates/stack-maintenance-reconciliation.md`](../templates/stack-maintenance-reconciliation.md).
Completed packets and structured receipts belong in owner-only storage outside
the repository. Tracked documentation contains no live PR inventory, private
absolute paths, raw prompts, raw configuration, secrets, or owner-local
receipt contents.

## Safety boundary

During repair and cleanup the current automation remains inactive. It may not
resume until the rollout proof is complete: two consecutive manual
audit/prepare runs use the same inputs, the second is a semantic true no-op,
and one run uses the final automation prompt and project context. A scheduler
must remain absent or inactive until that gate passes and an explicit approval
enables it.

An unattended run may perform only a read-only audit and preparation of one
review candidate. It may not merge, install, publish a runtime, write raw
Claude or Codex skill roots, mutate a plugin marketplace or app-managed plugin
source, repair the legacy vendor checkout, close a pull request, or delete a
branch. Those actions remain separate approval-gated operations.

Before any non-disposable write, preflight must inspect and record evidence
for:

- source identity and immutable provider references;
- the active checkout and every secondary worktree, including dirty state;
- every automation pull request and local or remote automation branch;
- owner-local receipt, lease, and policy authority; and
- the required tool authority for the requested operation.

If a protected checkout is dirty without a verified preservation artifact, the
clean base or source pin cannot be proved, more than one canonical maintenance
PR exists, a diff escapes its allowlist, a secret scan fails, or an exact
cleanup target lacks approval, stop before mutation and classify the packet as
blocked.

## U1 baseline reconciliation

U1 is a non-mutating evidence pass. The operator records the supported pause
control and its receipt, then copies the template into owner-only storage and
fills it from current source-of-truth systems. Do not create a second
automation record, edit the live scheduler by hand, switch branches, prune or
clean worktrees, stash or reset a checkout, or close/delete anything while
capturing the baseline.

The packet must account for all of the following:

- automation configuration and run evidence, using digests for prompts and
  private values rather than copying them;
- the dirty legacy GStack checkout's HEAD, upstream reference, status digest,
  change counts, and preservation artifact digest;
- the active Stack checkout and every secondary worktree, with repository-
  relative paths and before/after fingerprints;
- every automation PR and local or remote automation branch, including
  duplicate, superseded, blocked, and no-change items;
- protected exclusions: PR #23, non-automation branches, active worktrees,
  secrets/private configuration, and app-managed plugin sources; and
- a unique-content disposition, approval binding, and before/after check for
  every possible cleanup target.

The dirty vendor is evidence, not a trusted source. Preserve unique work as an
owner-only patch or overlay with a verification digest before any separately
approved restoration to the official pinned upstream state. The replacement
runner must not retain the legacy vendor checkout as a source or workaround.

## Reconciliation and approval rules

Inventory rows are deterministic: use the fixed field order in the template,
stable item identifiers, canonical SHA-256 fingerprints, and a stable sort.
Observation timestamps belong only in owner-only receipts and must not create
a tracked diff or change an input fingerprint. Every automation PR and branch
gets one row and one disposition, even when that disposition is `no_change`,
`hold`, or `excluded`.

Cleanup is a separately approved batch. An approval binds the packet digest,
exact item identifiers, recorded base/head SHAs, and the specific permitted
actions. Immediately before any approved cleanup, compare those exact targets
with live state; any drift cancels the batch. A blanket approval, a generated
receipt, or a matching name is not sufficient. PR #23 and all protected
exclusions remain untouched.

The before/after matrix must include the active checkout, every secondary
worktree, the dirty vendor, PR #23, and every proposed cleanup target. For U1,
the expected result is an exact match of identity and status digests. A missing
after-check is not a pass.

## Receipt and closeout

Append one redacted, owner-only structured receipt for each run. It records the
run identity, input fingerprint, provider refs, catalog and policy digests,
checkout state, changed-path digest, checks, PR state, approval state, cleanup
state, thread state, and terminal classification. It contains no secrets, raw
private configuration, or private absolute paths, and a later run appends a new
record rather than replacing history.

U1 is complete only when the automation is inactive, the packet accounts for
every named PR/branch/worktree and the dirty vendor, the preservation digest is
recorded, all protected exclusions are explicit, every unique-content decision
is covered, and read-only before/after fingerprints match. The packet is then
ready for a separately approved implementation or cleanup unit; it is not
itself authorization to mutate anything.

