# Weekly Stack intelligence operations

The weekly campaign has a deterministic collection coordinator and an approved
automatic promotion tail. The coordinator joins source/bookmark intake,
design-packet preparation, source-scoped retrieval,
candidate/evaluation, a read-only link to the latest Stack maintenance receipt,
and an owner-local report/receipt. `scripts/run-stack-weekly-intelligence.py`
uses `scripts/stack-run-state.py` through its `WorkflowStore`. It reuses the
existing lifecycle implementation, with a campaign-local `runs.sqlite3`
instance; it does not share the maintenance workflow's lease or database.

## Boundaries

- The deterministic collector and GBrain adapter deny provider egress. The
  analysis budget in `config/weekly-intelligence.json` authorizes at most three
  Codex contexts for critique, candidate authoring, and independent review; it
  never grants a paid external-provider call. The live retrieval exception is a local-subprocess
  keyword-read contract, not model/provider egress; it allowlists the exact
  GBrain CLI version and command shapes and reports `provider_calls: 0`.
- Raw/private source material stays in the caller's source system. Tracked
  artifacts and campaign receipts contain opaque IDs, digests, safe
  classifications, and owner-local relative paths only.
- The coordinator imports only the maintenance receipt validator. It never
  executes maintenance, copies raw maintenance output, acquires its lease,
  publishes, installs, merges, reindexes, or launches an upstream/provider
  fallback. The separate automatic tail owns only the exact evaluated
  Stack-owned skill/reference contract.
- Maintenance is a distinct daily workflow. Hermes collection/curation is a
  distinct Monday intake-only workflow. The weekly campaign is a distinct
  Saturday coordinator.

## Scheduler contract

The approved scheduler contract is Saturday at 09:00 local time in
`America/Los_Angeles`. Activation updates the one existing Codex automation in
place. The coordinator reads that automation's persisted TOML directly and
requires an exact match for its ID, active state, cadence, Stack project,
working directory, model, effort, execution environment, and canonical prompt
digest. Caller-supplied JSON cannot assert scheduler health. An eight-day
health pass also requires a terminal campaign receipt inside the eight-day
window.

The persisted automation remains anchored to the saved Stack project, while
execution uses the dedicated owner-local checkout at
`~/.local/share/stack/weekly-intelligence-source`. Each run requires that
checkout to be clean, non-symlinked, bound to the canonical Stack origin, and
detached at the freshly fetched `origin/main`. This keeps user-owned changes in
the saved checkout out of the unattended lane without weakening scheduler
identity. A missing or unsafe execution checkout fails as `retry_with_alert`;
the automation never cleans or switches the saved project checkout. Before any
private-source or campaign subprocess, the live entrypoint independently
requires that exact owner-private checkout, parses and allowlists its minimal
local Git configuration and rejects every active or symlinked repository hook
before the first Git process, ignores global/system Git configuration,
refreshes the canonical remote
tracking ref, rejects tracked paths hidden by `assume-unchanged` or
`skip-worktree`, rejects ignored files, and proves clean detached
`HEAD == origin/main`. The entrypoint and every Python child require isolated,
no-bytecode mode (`-I -B`) so a checkout artifact cannot shadow standard-library
imports before those checks run and a successful run cannot create ignored
bytecode that blocks the next one. Direct or shebang execution is unsupported;
the automation's exact interpreter invocation is part of the contract. A wrong root is
rejected before even a Git subprocess can run; a concurrent upstream advance
fails closed as a stale checkout for the next scheduled retry.

The active task uses `gpt-5.6-sol` at high reasoning. Deterministic collection
still runs first. Model work occurs only when material evidence exists; at most
one candidate can reach evaluation in a run.

## Inputs and idempotency

The semantic input fingerprint is the canonical SHA-256 of nonvolatile
configuration, source manifest and delta, model/prompt/evaluation config, and
the relevant latest maintenance receipt. Observation timestamps, run IDs, and
lease times are excluded. A second identical input writes only an owner-local
`no_action` receipt and does not invoke model-heavy adapters or create a new
WorkflowStore run.

If a semantic input changes, the source/delta, retrieval, candidate/evaluation,
or no-action path is represented in the child graph. Stage input fingerprints
permit unchanged model-heavy stages to be reused. Completed child checkpoints
survive failures; resuming a blocked/cancelled run reclaims only failed or
cancelled children before continuing pending graph work.
Completed children may reuse only their own run's matching checkpoint evidence.
New children may reuse another campaign's model-heavy output only when its
stage fingerprint matches. Maintenance links require the canonical persisted
receipt contract and reject future-dated observations.

## Failure and recovery

Receipts classify a run as `no_action`, `prepared`, `awaiting_approval`,
`blocked`, `partial`, or `failed`. A child failure leaves its checkpoints and
the WorkflowStore parent blocked; it does not imply publication. The receipt
contains a safe restart action and no raw stderr. Transient failures do not
strike the campaign circuit. Three identical non-transient blockers open the
campaign-owned circuit; later identical attempts exit cheaply until an
explicit manual clear.

`prepared` with reason `automatic_promotion_pending` transfers control to the
approved automatic tail. Weak candidates become `no_action`; policy or quality
failures become `rejected_no_queue`; unavailable operational dependencies
become `retry_with_alert`. These outcomes retain owner-local evidence without
creating a recurring human approval queue.

For missing, invalid, or stale maintenance evidence, the report links an
alert and gives the safe manual restart guidance. It never runs maintenance on
behalf of the weekly campaign. Use `--resume --run-id <id>` after repairing a
failed child, and use `--manual-clear` only after a human has reviewed the
circuit blocker.

## Owner-local state

Set `STACK_WEEKLY_INTELLIGENCE_STATE_DIR` to an owner-only state directory when
running manually; otherwise the runner uses
`~/.local/state/stack/weekly-intelligence`. The directory and receipts are
created mode `0700`/`0600`, reject symlinks and ownership/mode drift, and are
written through an atomic replace. The state database is the existing
`WorkflowStore` database at `runs.sqlite3`; it owns leases and checkpoints.

Example (manual, read-only coordination):

```sh
/opt/homebrew/bin/python3.11 -I -B scripts/run-stack-weekly-intelligence.py \
  --state-dir "$HOME/.local/state/stack/weekly-intelligence" \
  --source-manifest /path/to/manifest.json \
  --source-delta /path/to/delta.json
```

The active weekly entrypoint is
`/opt/homebrew/bin/python3.11 -I -B scripts/run-stack-weekly-live.py`. Direct,
shebang, or ambient-`python3` execution is unsupported. The entrypoint
first verifies the exact persisted active automation and a current canonical
maintenance receipt. It exits before spawning any reconciliation or import
subprocess when either preflight fails. After preflight it reconciles the
current local Field Theory database into the owner-local ledger, imports only
missing `x-bookmarks` with embeddings disabled, and then runs the local adapter
route above. Direct X/OAuth and paid provider fallback remain disabled. Skill
promotion and runtime publication are available only through authorization
contract `weekly-design-auto-promotion-approved-v1` after the checked-in
automatic gates.

The entrypoint pins the real account home, a minimal executable search path,
and its owner-only temporary directory. Its source, state, executable, and
output paths reject unexpected symlink ancestors, ownership drift, and unsafe
write modes before any mutable subprocess is launched.

The command prints a safe receipt summary with the exact owner-local campaign
receipt's relative path and digest. The automatic tail binds those fields and
never chooses a receipt by newest-file ordering. A nonzero exit means the
receipt is `blocked`, `partial`, or `failed`; inspect the owner-local receipt
and use its safe restart guidance.

Without an adapter configuration this example stops at
`source_intake_adapter_not_configured`. The explicit local preparation route is:

```sh
/opt/homebrew/bin/python3.11 -I -B scripts/run-stack-weekly-intelligence.py \
  --local-adapter-config /owner-local/weekly-inputs.json \
  --state-dir /owner-local/weekly-state \
  --maintenance-receipt /owner-local/maintenance-receipt.json
```

The owner-only configuration can select either an inline export or a sealed
snapshot/ledger pair. A live retrieval configuration also binds an owner-only
request, target manifest, and source grant:

```json
{
  "schema_version": 1,
  "source_snapshot": "/owner-local/source-snapshot.json",
  "source_ledger": "/owner-local/bookmarks-ledger.sqlite3",
  "retrieval_request": "/owner-local/retrieval-request.json",
  "target_manifest": "/owner-local/target-manifest.json",
  "retrieval_grant": "/owner-local/retrieval-grant.json",
  "retrieval_transport": "live-gbrain-text-v1"
}
```

The source document contains inline `items` or paginated `pages`, an explicit
source identity and capture timestamp. It must not redirect to another file,
database, URL, or executable. Source and configuration files must be outside
Stack, owned by the caller, with file/directory modes `0600`/`0700`; symlink
redirection fails closed. Input bytes and adapter/domain code digests bind the
campaign fingerprint, so editing the same pathname invalidates reuse.
The state directory may already exist, or its leaf can be created beneath an
existing owner-only parent; this route does not scaffold a broader state path.

Local preparation calls the actual reconciliation and packet builders and
stores their safe domain artifacts, not just lifecycle wrappers. Raw source
rows stay in memory; generated cards remain quarantined. The live transport
requires the request, target manifest, and source grant; it re-attests the
source/index before a no-action decision. Grant expiry is checked again before
every subprocess read, and the configured GBrain database endpoint must match
the audited owner-local backend allowlist before any engine connection.
Programmatic test transports are not exposed as a CLI enablement switch.

An optional `evaluation` object references `packet`,
`materialization_receipt`, `harness_root`, and `manifests`/`results` maps for
`development`, `holdout`, and `rotating_canary`. These must be existing,
owner-local, candidate-bound evaluation inputs. The adapter evaluates them;
it does not generate a patch, run an external harness, or promote a result.
When no material candidate is selected, the stage records an explicit
quarantined `no_candidate_selected` result and does not run the evaluator.
Once a candidate is selected, missing or insufficient evidence blocks
evaluation. See the
[readiness reconciliation](weekly-intelligence-readiness.md) for live
integration and approval gates.

## Automatic promotion and publication

The tail works from a clean isolated branch based on current `origin/main`,
never the user's primary checkout. It may change only existing
`skills/**/SKILL.md` or `skills/**/references/**/*.md`, with one candidate,
three files, and 32,768 bytes maximum per run. Material evidence, isolated
materialization, frozen design evaluation, full tests, a fresh independent
`ship` review, green pull-request checks, and merge verification are all
required before publication.

The materialization command must use `--automatic-weekly-design`. Its
authorization binds the exact coordinator run ID and receipt digest to
`weekly-design-auto-promotion-approved-v1`. The materializer independently
enforces replacement-only edits, existing Stack-owned skill/reference paths,
the three-file limit, the byte limit, checkout preservation, and the disposable
no-network clone. The terminal recorder repeats the path, digest, and limit
checks against the immutable base commit.

Publication runs only from a fresh clean checkout of verified merged
`origin/main` through
`/opt/homebrew/bin/python3.11 -I -B scripts/bootstrap-stack.py --install`,
followed by `/opt/homebrew/bin/python3.11 -I -B scripts/stack-doctor.py`. Both
Claude and Codex discovery and the owner-local rollback receipt must pass before
the outcome is `published`. Direct main
commits, vendor/imported changes, route/command edits, source mutation,
upstream-pin updates, credentials, paid fallback, and destructive cleanup are
outside this contract and still require separate approval.

Every automatic run ends by binding its collection receipt and terminal
decision into an owner-local promotion receipt. The recorder validates the
canonical full coordinator receipt and the complete gate set. A selected
candidate is eligible only when the campaign is `prepared` with reason
`automatic_promotion_pending`; a `no_action` campaign cannot later claim a
candidate. The recorder refuses contradictory claims such as publication
without a merged PR, both runtimes, or rollback proof, and it refuses retry or
rejection while a pull request remains open:

```sh
/opt/homebrew/bin/python3.11 -I -B scripts/record-weekly-design-promotion.py \
  --live-receipt /owner-local/weekly-state/live/live-receipts/run-id.json \
  --live-receipt-digest returned-live-binding-sha256 \
  --campaign-receipt /owner-local/weekly-state/receipts/run-id.json \
  --decision /owner-local/weekly-state/promotion-decisions/run-id.json \
  --out-dir /owner-local/weekly-state/promotion-receipts
```

The decision contains an exact `evidence` map for `candidate_packet`,
`materialization`, `evaluation`, `repository_tests`, `independent_review`,
`pull_request_ci`, `merge_verification`, `runtime_publication`, and
`rollback_receipt`. Each used entry supplies an owner-local JSON path and its
exact SHA-256 digest; unused entries are `null`. Passed gates require the
matching artifact. Publication additionally cross-checks candidate/base/edit
digests, real-task evaluation evidence, the tested/reviewed head, CI and merge
lineage, the installer's merged source commit and target verifiers, and the
rollback-state shape. Runtime proof must use the installer's immutable
`transactions/<transaction-id>/install.json` and `rollback.json` pair. Both
files share one transaction ID and directory; mutable root-level aliases are
operational pointers, not promotion evidence. The input files and output are mode `0600` below
owner-only mode-`0700` directories. Terminal receipts retain only digests and
safe states, never raw bookmark content or absolute source paths. The accepted
dispositions are `published`, `no_action`, `rejected_no_queue`, and
`retry_with_alert`; none creates a human approval queue.
