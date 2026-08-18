# Stack maintenance reconciliation packet

This is a reusable shape for an owner-only, read-only baseline packet. Copy it
to approved owner-only storage before filling it. Do not commit a completed
packet, current PR inventory, private absolute path, raw prompt/configuration,
secret, or live receipt to Stack.

## Packet metadata

- Packet ID: `PACKET_ID`
- Mode: `read_only_baseline`
- Captured by: `ACTOR_OR_AUTOMATION_ID`
- Captured at (owner-only receipt field): `UTC_TIMESTAMP`
- Input fingerprint (canonical SHA-256): `INPUT_FINGERPRINT`
- Catalog digest: `CATALOG_DIGEST`
- Policy digest: `POLICY_DIGEST`
- Owner-only receipt ID: `RECEIPT_ID`
- Terminal classification: `no_action | blocked | awaiting_approval`

Canonicalization rules:

- Keep the fields and table columns in this order.
- Sort inventory rows by item type, then stable item identifier.
- Hash canonical field values, not observation time, presentation order, or
  redacted display text.
- Use repository-relative paths only; use a stable owner-only reference for
  any external receipt or preservation artifact.
- A missing value is `MISSING`, not an empty value or an inferred pass.

## Safety and source-of-truth checks

| Check | Evidence or digest | Result | Stop condition |
| --- | --- | --- | --- |
| Supported automation pause control recorded | `CONTROL_RECEIPT_ID` | `PASS \| FAIL \| MISSING` | Inactive state cannot be proved |
| Current task boundary and approval authority recorded | `AUTHORITY_REFERENCE` | `PASS \| FAIL \| MISSING` | Authority is ambiguous |
| Source identity and immutable refs verified | `SOURCE_IDENTITY_AND_REFS` | `PASS \| FAIL \| MISSING` | Pin or provenance fails |
| Active checkout and all worktrees inspected | `WORKTREE_SCAN_DIGEST` | `PASS \| FAIL \| MISSING` | Any worktree is unaccounted for |
| Every automation PR and branch inventoried | `AUTOMATION_INVENTORY_DIGEST` | `PASS \| FAIL \| MISSING` | Inventory is incomplete |
| Secrets and private configuration unread | `REDACTION_CHECK_ID` | `PASS \| FAIL \| MISSING` | Sensitive data entered packet |
| No non-disposable mutation performed | `MUTATION_CHECK_ID` | `PASS \| FAIL \| MISSING` | Any write, switch, prune, cleanup, or close |

The repository catalog, `upstreams.lock.json`, Git/hosting state, and the
runtime publication contract are the sources of truth. Generated receipts are
evidence only. If a receipt disagrees with a source-of-truth system, stop and
record the contradiction.

## Automation configuration and run evidence

Record only stable identifiers and digests. Never copy the raw prompt, private
configuration, secret, or owner-local path.

| Field | Recorded value or digest | Evidence reference | Before/after requirement |
| --- | --- | --- | --- |
| Automation identity | `AUTOMATION_ID` | `CONFIG_EVIDENCE_ID` | Identity unchanged during baseline |
| Active state | `inactive \| active \| unknown` | `CONTROL_RECEIPT_ID` | `inactive` for U1 |
| Supported pause result | `PAUSED \| NOT_PAUSED \| UNKNOWN` | `CONTROL_RECEIPT_ID` | `PAUSED` |
| Project/target identity | `PROJECT_ID_OR_DIGEST` | `CONFIG_EVIDENCE_ID` | Record, do not infer |
| Cadence/model/effort | `CONFIG_DIGEST` | `CONFIG_EVIDENCE_ID` | Record, do not change |
| Prompt digest and context digest | `PROMPT_DIGEST` / `CONTEXT_DIGEST` | `RUN_EVIDENCE_ID` | Hash only |
| Latest run identity and outcome | `RUN_ID` / `OUTCOME` | `RUN_RECEIPT_ID` | Preserve run evidence |
| Durable memory/thread state | `MEMORY_OR_THREAD_DIGEST` | `RUN_EVIDENCE_ID` | Append-only; no archival mutation |

## Dirty vendor fingerprint

The dirty legacy GStack checkout is a protected evidence surface. Do not
stash, reset, clean, overwrite, switch, or use it as a trusted source.

| Field | Recorded value or digest | Verification |
| --- | --- | --- |
| Checkout identity and repository-relative location | `VENDOR_ID` / `RELATIVE_PATH` | `SOURCE_IDENTITY_CHECK_ID` |
| HEAD SHA | `VENDOR_HEAD_SHA` | `GIT_STATE_CHECK_ID` |
| Official upstream ref/pin | `UPSTREAM_REF` / `LOCKED_PIN` | `UPSTREAM_CHECK_ID` |
| Origin identity | `ORIGIN_IDENTITY_DIGEST` | `REMOTE_CHECK_ID` |
| Status digest and changed-path count | `STATUS_DIGEST` / `COUNT` | `GIT_STATE_CHECK_ID` |
| Unique-content fingerprint | `UNIQUE_CONTENT_DIGEST` | `CONTENT_REVIEW_ID` |
| Owner-only patch or overlay reference | `PRESERVATION_REF` | `PRESERVATION_DIGEST` |
| Preservation disposition | `preserve \| hold \| missing` | `PRESERVATION_CHECK_ID` |
| Restoration approval | `APPROVAL_ID_OR_NOT_REQUESTED` | Exact-target binding required |

The preservation artifact and its verification digest must exist before any
separately approved restoration to the official upstream state. The new runner
must not retain this checkout as a source or workaround.

## Stack checkout and worktrees

Use repository-relative paths and stable worktree IDs. Include the active
checkout and every secondary worktree, not only worktrees related to automation.

| Worktree ID | Repo-relative path | Branch/ref | HEAD SHA | Dirty/status digest | Owner/protected? | Before/after result |
| --- | --- | --- | --- | --- | --- | --- |
| `ACTIVE_CHECKOUT` | `RELATIVE_PATH` | `BRANCH_OR_REF` | `HEAD_SHA` | `STATUS_DIGEST` | `OWNER / PROTECTED` | `MATCH \| DRIFT \| MISSING` |
| `SECONDARY_<ID>` | `RELATIVE_PATH` | `BRANCH_OR_REF` | `HEAD_SHA` | `STATUS_DIGEST` | `OWNER / PROTECTED` | `MATCH \| DRIFT \| MISSING` |

No row authorizes prune, branch switch, cleanup, stash, reset, or writes to an
active worktree. An active worktree is a protected exclusion.

## Automation PR and branch inventory

Inventory every automation pull request and every local or remote automation
branch before any cleanup decision. Do not list current live rows in this
tracked template; the owner-only packet supplies them at run time.

| Item ID | Type | Automation match | State/base/head SHAs | Content fingerprint | Unique valid content? | Proposed disposition | Before/after result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ITEM_ID` | `PR \| local_branch \| remote_branch` | `yes \| no \| unknown` | `STATE / BASE / HEAD` | `CONTENT_DIGEST` | `yes \| no \| unknown` | `preserve \| replace \| no_change \| hold \| excluded` | `MATCH \| DRIFT \| MISSING` |

Every item gets exactly one disposition, including duplicate, superseded,
blocked, no-change, and excluded items. A name match is not lineage proof;
record ancestry and exact SHAs. If more than one canonical maintenance PR,
unsafe ancestry, or ambiguous lineage exists, stop before preparation.

## Protected exclusions

These exclusions are fixed safety boundaries, not cleanup suggestions.

| Exclusion | Required treatment | Evidence |
| --- | --- | --- |
| PR #23 | Preserve; no close, edit, or branch deletion | `PR23_BEFORE_DIGEST` / `PR23_AFTER_DIGEST` |
| Non-automation branches | Preserve; no branch mutation | `BRANCH_EXCLUSION_DIGEST` |
| Active worktrees | Read-only; no prune, switch, stash, reset, or cleanup | `WORKTREE_SCAN_DIGEST` |
| Secrets and private configuration | Do not read, copy, or disclose | `REDACTION_CHECK_ID` |
| App-managed plugin sources | Do not write or publish through this lane | `PLUGIN_BOUNDARY_CHECK_ID` |

If PR #23 appears in the live inventory, include it as one `excluded` item and
record exact before/after fingerprints. This template intentionally contains no
current live PR inventory.

## Unique-content disposition

For each inventory item, reconcile unique valid content before proposing any
cleanup. Preserve it in an isolated replacement candidate or owner-only
artifact when needed; never discard it because a PR or branch is old.

| Item ID | Content digest | Classification | Preservation/replacement reference | Disposition rationale | Approval binding |
| --- | --- | --- | --- | --- | --- |
| `ITEM_ID` | `CONTENT_DIGEST` | `unique \| duplicate \| invalid \| unknown` | `CANDIDATE_OR_ARTIFACT_REF` | `RATIONALE` | `APPROVAL_ID_OR_NOT_REQUESTED` |

Allowed dispositions are `preserve`, `replace`, `no_change`, `hold`, and
`excluded`. `unknown` content or an incomplete replacement blocks cleanup.

## Approval binding

Cleanup is a separately approved batch. Approval must bind exact targets and
the packet that produced them; it cannot be inferred from a receipt or a
general maintenance approval.

- Approval ID: `APPROVAL_ID`
- Packet digest: `PACKET_DIGEST`
- Exact target item IDs: `ITEM_IDS`
- Exact recorded base/head SHAs: `TARGET_SHA_BINDINGS`
- Permitted actions: `ACTIONS`
- Explicit exclusions: `PR23_AND_PROTECTED_EXCLUSIONS`
- Approver and approval time (owner-only): `APPROVER / UTC_TIMESTAMP`
- Live-state recheck ID immediately before action: `RECHECK_ID`
- Binding result: `MATCH \| DRIFT_CANCELLED \| MISSING`

Any target SHA, ancestry, worktree ownership, or protected-state drift cancels
the batch. No cleanup occurs while the binding is missing, stale, or ambiguous.

## Before/after checks

For a U1 baseline, every after fingerprint must match its before fingerprint.
Do not report a pass when an after-check is missing.

| Surface | Before identity/status digest | Permitted U1 action | After identity/status digest | Result |
| --- | --- | --- | --- | --- |
| Active Stack checkout | `BEFORE_DIGEST` | Read-only inspection | `AFTER_DIGEST` | `MATCH \| DRIFT \| MISSING` |
| Every secondary worktree | `BEFORE_DIGEST` | Read-only inspection | `AFTER_DIGEST` | `MATCH \| DRIFT \| MISSING` |
| Dirty legacy vendor | `BEFORE_DIGEST` | Fingerprint only | `AFTER_DIGEST` | `MATCH \| DRIFT \| MISSING` |
| PR #23 | `BEFORE_DIGEST` | Preserve | `AFTER_DIGEST` | `MATCH \| DRIFT \| MISSING` |
| Every proposed cleanup target | `BEFORE_DIGEST` | No cleanup in U1 | `AFTER_DIGEST` | `MATCH \| DRIFT \| MISSING` |

## Approved cleanup outcome

Fill this only after an exact-target approval and immediate live-state recheck.
An interrupted batch remains `partial`; completed targets are never inferred.

| Packet digest | Completed item IDs | Remaining item IDs | Protected exclusions | Classification |
| --- | --- | --- | --- | --- |
| `PACKET_DIGEST` | `COMPLETED_IDS` | `REMAINING_IDS` | `PROTECTED_IDS` | `prepared \| partial \| no_action` |

## Receipt summary and closeout

Append a redacted, owner-only receipt with these R10 fields:

| Receipt field | Value or digest |
| --- | --- |
| Run identity and input fingerprint | `RUN_ID` / `INPUT_FINGERPRINT` |
| Provider refs | `PROVIDER_REFS_DIGEST` |
| Catalog and policy digests | `CATALOG_DIGEST` / `POLICY_DIGEST` |
| Checkout/worktree/vendor state | `CHECKOUT_STATE_DIGEST` |
| Changed-path digest | `CHANGED_PATH_DIGEST` |
| Checks | `CHECKS_DIGEST` |
| PR state | `PR_STATE_DIGEST` |
| Approval state | `APPROVAL_STATE_DIGEST` |
| Cleanup state | `CLEANUP_STATE_DIGEST` |
| Thread state | `THREAD_STATE_DIGEST` |
| Terminal classification | `no_action \| prepared \| awaiting_approval \| blocked \| partial \| failed \| published` |

U1 closeout checklist:

- [ ] The automation is inactive through the supported control.
- [ ] The packet accounts for every automation PR, branch, worktree, and the
  dirty vendor.
- [ ] PR #23 and all protected exclusions are explicit and unchanged.
- [ ] Unique valid content has a disposition and preservation evidence.
- [ ] Approval binding is absent or records exact targets; no action is implied.
- [ ] All before/after checks match and show no non-disposable mutation.
- [ ] The receipt is redacted, append-only, owner-only, and complete.
