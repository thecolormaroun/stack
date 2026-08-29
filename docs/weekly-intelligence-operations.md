# Weekly Stack intelligence operations

The weekly campaign is a deterministic, review-only coordinator. It joins
source/bookmark intake, design-packet preparation, source-scoped retrieval,
candidate/evaluation, a read-only link to the latest Stack maintenance receipt,
and an owner-local report/receipt. `scripts/run-stack-weekly-intelligence.py`
uses `scripts/stack-run-state.py` through its `WorkflowStore`. It reuses the
existing lifecycle implementation, with a campaign-local `runs.sqlite3`
instance; it does not share the maintenance workflow's lease or database.

## Boundaries

- Provider/model egress is denied. The analysis budget in
  `config/weekly-intelligence.json` records a planning limit and never grants
  spend or a provider call. The live retrieval exception is a local-subprocess
  keyword-read contract, not model/provider egress; it allowlists the exact
  GBrain CLI version and command shapes and reports `provider_calls: 0`.
- Raw/private source material stays in the caller's source system. Tracked
  artifacts and campaign receipts contain opaque IDs, digests, safe
  classifications, and owner-local relative paths only.
- The coordinator imports only the maintenance receipt validator. It never
  executes maintenance, copies raw maintenance output, acquires its lease,
  publishes, installs, merges, reindexes, or
  launches an upstream/provider fallback.
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
python3 scripts/run-stack-weekly-intelligence.py \
  --state-dir "$HOME/.local/state/stack/weekly-intelligence" \
  --source-manifest /path/to/manifest.json \
  --source-delta /path/to/delta.json
```

The active weekly entrypoint is `python3 scripts/run-stack-weekly-live.py`. It
first verifies the exact persisted active automation and a current canonical
maintenance receipt. It exits before spawning any reconciliation or import
subprocess when either preflight fails. After preflight it reconciles the
current local Field Theory database into the owner-local ledger, imports only
missing `x-bookmarks` with embeddings disabled, and then runs the local adapter
route above. Direct X/OAuth, paid provider fallback, skill promotion, and
runtime publication remain disabled.

The entrypoint pins the real account home, a minimal executable search path,
and its owner-only temporary directory. Its source, state, executable, and
output paths reject unexpected symlink ancestors, ownership drift, and unsafe
write modes before any mutable subprocess is launched.

The command prints a safe receipt summary. A nonzero exit means the receipt is
`blocked`, `partial`, or `failed`; inspect the owner-local receipt and use its
safe restart guidance.

Without an adapter configuration this example stops at
`source_intake_adapter_not_configured`. The explicit local preparation route is:

```sh
python3 scripts/run-stack-weekly-intelligence.py \
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
