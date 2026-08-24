# Weekly Stack intelligence operations

The weekly campaign is a deterministic, review-only coordinator. It joins
source/bookmark intake, design-packet preparation, source-scoped retrieval,
candidate/evaluation, a read-only link to the latest Stack maintenance receipt,
and an owner-local report/receipt. `scripts/run-stack-weekly-intelligence.py`
uses `scripts/stack-run-state.py` through its `WorkflowStore`; there is no
second database or campaign control plane.

## Boundaries

- Provider egress is denied by default. The analysis budget in
  `config/weekly-intelligence.json` records a planning limit and never grants
  spend or a provider call.
- Raw/private source material stays in the caller's source system. Tracked
  artifacts and campaign receipts contain opaque IDs, digests, safe
  classifications, and owner-local relative paths only.
- The coordinator never calls `stack-maintenance.py`, imports maintenance
  output, acquires its lease, publishes, installs, merges, reindexes, or
  launches an upstream/provider fallback.
- Maintenance is a distinct daily workflow. Hermes collection/curation is a
  distinct Monday intake-only workflow. The weekly campaign is a distinct
  Saturday coordinator.

## Future scheduler contract

The future scheduler contract is Saturday at 09:00 local time in
`America/New_York`. It is represented in config with `enabled: false` and
requires a separately approved, persisted contract before enablement. This
repository does not install, enable, disable, or alter a scheduler. Scheduler
existence alone is not health evidence: an eight-day health pass requires
enabled-state proof, a matching persisted contract and approval, and a
terminal campaign receipt inside the eight-day window.

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

The command prints a safe receipt summary. A nonzero exit means the receipt is
`blocked`, `partial`, or `failed`; inspect the owner-local receipt and use its
safe restart guidance.
