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

## U2 maintenance state machine

The versioned runner is `scripts/stack-maintenance.py`. Its `audit` mode is
read-only. Its `prepare` mode may clone a disposable clean candidate and run
the complete readiness gates. Only the explicit `--github` boundary may create
or reuse one draft PR; neither mode mutates a caller checkout, writes a runtime,
merges, or publishes a plugin. The source and candidate units consume the same
receipt contract rather than adding a second state store.

The policy in [`config/stack-maintenance.json`](../config/stack-maintenance.json)
and the complete target inventory in
[`registry/maintenance-sources.json`](../registry/maintenance-sources.json)
are loaded fail-closed. Every legacy target has one explicit disposition:
catalog-managed provider, repository-owned capability, report-only
external/plugin, or retired legacy target. A missing target, duplicate target,
unknown disposition, mutable policy mode, or incomplete authority declaration
is a terminal `failed` result.

Owner-local state is initialized only at the configured state directory. The
state and receipt directories are mode `0700`; each JSON receipt is mode
`0600`. Receipts are created with exclusive creation and are never replaced.
Each record includes the run identity, semantic input fingerprint, provider-ref
digests, catalog and policy digests, checkout/changed-path/PR/approval/cleanup/
thread state, checks, and one terminal classification defined by
[`registry/stack-maintenance-receipt.schema.json`](../registry/stack-maintenance-receipt.schema.json).
Observation time is receipt metadata only and is excluded from the input
fingerprint, so repeated unchanged runs do not create timestamp-driven input
churn.

One task-scoped lease and a kernel-backed liveness lock protect the source,
runtime, and PR lane. The lock is held for the complete process lifetime, so a
long run cannot be displaced merely because the lease timestamp expires. An
active lease or live lock produces `blocked` with `duplicate_active_run` and
performs no disposable write. After the prior process exits, an expired lease
is recoverable only when both its owner and input fingerprint match; a mismatch
remains `blocked` with `stale_lease_mismatch` until an explicit
`audit --manual-audit` validates recovery. Manual recovery flags are rejected
in `prepare` mode, so recovery cannot cross into materialization or GitHub
mutation before a successful audit re-establishes the safety baseline.
Three consecutive non-transient blockers with the same fingerprint open the
local circuit, including persistent import, license, deletion, and candidate
staging failures. Scheduled invocations exit cheaply with `circuit_open`; a
successful manual audit clears the circuit and appends a new receipt without
rewriting prior records.

For example, an isolated proof run is:

```sh
python3 scripts/stack-maintenance.py audit --state-dir "$STACK_MAINTENANCE_STATE_DIR"
```

If state initialization is unsafe or cannot be persisted, the runner fails
closed and emits one redacted structured terminal record on stderr with
`receipt_persisted: false`; it never selects a fallback filesystem path.

## U3 source audit and candidate staging

The source audit resolves every legacy target through
[`registry/maintenance-sources.json`](../registry/maintenance-sources.json).
Catalog-managed rows must name a provider in `registry/upstreams.json`, match
the immutable value in `upstreams.lock.json`, retain the last-known-good pin,
and declare the exports they are allowed to consume. Repository-owned rows
are checked-in Stack content. Report-only plugin rows are recorded with an
empty command list; they never invoke a plugin, marketplace, or raw skill-root
command. Retired rows remain visible so a removed legacy target cannot be
silently reintroduced.

Every catalog provider is represented, including the Matt and David imported
collections and the Stack-owned Codex bundle that the legacy task omitted.
`--observe-upstreams` reads each public Git provider's current `HEAD` and
reports drift without promoting that mutable observation to a trusted pin.
Observed drift is `awaiting_approval` until the isolated candidate and PR gates
validate it; an unchanged observation remains a deterministic `no_action`.

The audit verifies the caller's public `origin` host, repository, and
`origin/main` identity but
does not require the caller checkout to be clean. A dirty protected vendor is
an exact blocker unless an owner-approved hold is bound to its current head and
status digest. The same preflight enumerates every linked worktree and records
its path identity as a digest plus its branch, head, status digest, and dirty
entry count; machine paths and changed filenames never enter the receipt.
Provider checkout evidence is read-only and cannot become a new
trusted pin. Mutable refs, origin mismatches, missing exports, unregistered
targets, missing declared paths, and symlinks fail closed.

`scripts/stack-maintenance.py prepare` is the only scheduled proposal entry
point. It accepts a persisted owner-only audit receipt, clones the receipt's
exact `origin/main` SHA, and invokes that base's checked-in
`scripts/materialize-maintenance-proposal.py` itself. External manifests are
rejected. The materializer fetches each exact observed commit and follows the
curated existing-import rules in
`registry/maintenance-imports.json`. It never discovers or activates new
skills. Every fetched license must match the exact reviewed SHA-256 digest in
the provider registry; matching a license phrase is not sufficient. Missing
mappings, changed licenses, file, directory, or dangling symlinks, upstream
deletions, or renames fail closed for review.

`prepare` creates a disposable candidate clone outside the caller checkout
from that recorded `origin/main` SHA. Only explicit policy-allowlisted files
with receipt-bound manifest hashes can be proposed, and candidate content is
checked for private machine paths and secrets. Before any push, the candidate
runs immutable-metadata, capability, layout, bootstrap, doctor, complete test,
sensitive-content, and diff gates. JSON provenance fingerprints ignore
observation-only fields such as `checked_at`, so a timestamp refresh is a true
no-op. Candidate output remains local evidence for the canonical PR lane; U3
does not merge, install, or publish it.

## U4 canonical draft-PR lane

`prepare_canonical_pr` is the only remote-candidate path. It identifies the
candidate by branch `automation/stack-maintenance` and marker
`stack-maintenance/v1`, then verifies the recorded `origin/main` SHA, one
expected commit, remote merge base, the hosting service's current changed-path
set, the allowlist, and both path and blob-content digests. Reuse is allowed
only when the remote draft content is byte-equivalent to the generated
candidate; same-path stale content blocks rather than reporting success.
It commits only an explicit path list in the disposable checkout and requires
local readiness checks while the stage is clean before calling the injected
GitHub boundary.

Exactly one safe open candidate is reused; no candidate creates one draft PR.
If a successful canonical-branch push is followed by a transient PR-creation
failure, the next run resumes PR creation only after proving the branch's base,
single-commit ancestry, changed-path digest, and blob-content digest against
the regenerated or retained candidate. Multiple candidates, an unverifiable
branch without its PR, unexpected lineage, a changed remote head, an unrelated
path, or a missing marker blocks before remote mutation. Optional labels do not
participate in identity or convergence. The adapter never force-pushes or
targets `main`. If push or PR creation fails, the receipt is `partial` and the
stage remains available for recovery.

## U5 protected vendor hold

The legacy GStack checkout is no longer an input authority or update path. Its
151-file dirty state was captured in an owner-only binary patch and proved in a
disposable checkout to match upstream commit
`9fd03fae9e74f5daa7a138366aca8f86c7367c5c` exactly, with no untracked or
unique uncommitted content. The original checkout remains untouched under a
verified hold; unrelated catalog audit and candidate preparation can proceed.

`validate_vendor_preservation` binds the exact checkout identity, HEAD, status
digest, patch digest, manifest digest, and reconstruction proof. The audit
accepts a dirty vendor only when `--vendor-path`, `--vendor-hold`, and
`--vendor-manifest` name that complete owner-only evidence set; a synthetic
in-memory hold is not accepted. A changed or incomplete artifact fails closed.
`build_vendor_restoration_plan` can describe
only that exact target and requires a token derived from the current evidence;
it never performs restoration and scheduled execution is forbidden. No stash,
reset, restore, fast-forward, or vendor deletion is part of the recurring task.

## U6 backlog reconciliation

`build_reconciliation_packet` classifies each pull request and branch by exact
base/head identity, content class, disposition, preservation evidence, and
permitted cleanup action. Mixed history is split into content groups so a
duplicate automation snapshot cannot make unrelated commits eligible for a
replacement candidate. Unique content is never eligible for cleanup until a
reachable branch or verified recovery artifact preserves it.

Protected items use the `excluded` disposition and carry no cleanup actions.
The approval token binds the canonical packet digest and every recorded head;
`build_cleanup_plan` rejects a changed or missing live head before any remote
operation. Cleanup execution remains outside scheduled code. Its result is
classified from the exact completed set, so an interrupted batch remains
`partial` with explicit remaining targets rather than being reported as a
successful cleanup.

## U7 scheduled operation

The saved Codex task is a thin delegate to this repository and the versioned
`stack-sync` skill. Its routine entry point is
`python3 scripts/stack-maintenance.py audit --observe-upstreams`; a generated
candidate comes only from the receipt-bound `prepare` flow, which runs the
exact-base materializer itself, uses a fresh disposable proposal directory and
stage, and crosses the explicit `--github` boundary. The CLI refuses GitHub
access without an actionable audit receipt bound to the current `origin/main`
SHA and exact observed provider commits.

Every persisted receipt contains a semantic output digest that excludes run ID
and observation time. Two unchanged runs therefore prove equal input and
output digests while appending distinct receipts. `no_action` and `prepared`
receipts are marked `archive_eligible`; `awaiting_approval`, `blocked`,
`partial`, and `failed` receipts are marked `keep_visible`.

The existing automation record is migrated in place only after proof. Its
target is the Stack project, its cadence is Monday at 09:00 local time, and its
executor is `gpt-5.6-luna` at maximum reasoning. The compatibility launcher is
a thin delegate and contains no source update, install, plugin, branch, or PR
logic. Automatic merge, runtime publication, vendor restoration, and cleanup
remain outside scheduled authority.

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
