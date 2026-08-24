# Design intelligence loop

Stack turns approved private bookmark evidence into cited design guidance and
reviewable capability improvements. It does not copy raw X posts into the
repository, create a second search index, fine-tune model weights, or rewrite
active skills unattended.

## Ownership and data boundary

- Field Theory is the default X-bookmark source boundary.
- The private `x-bookmarks` GBrain source is the searchable knowledge authority.
- Stack owns source contracts, safe projections, design cards, retrieval policy,
  evaluation fixtures, and candidate-change machinery.
- Raw text, URLs, media, personal topics, paths, cursors, and credentials remain
  in owner-local `0700`/`0600` storage.
- Public Stack artifacts may contain reviewed software guidance and opaque
  evidence IDs, never the private source payload.

Direct X API parity is optional and disabled by default. It requires separate
read-only OAuth and provider-spend approval. Credentials must remain in an
OS-managed secret store; configuration, logs, packets, and receipts may keep
only a redacted secret reference. The normal weekly path works without it.

## Source reconciliation

Historical backfill and recurring deltas are separate modes. Backfill is
bounded and resumable; completeness requires terminal cursor evidence, count
and folder reconciliation where available, media/link status, deduplication
lineage, and a subsequent zero-delta pass. Missing or deleted source items are
receipted rather than silently omitted.

The source tools are dry-run by default:

```sh
python3 scripts/backfill-bookmark-history.py --help
python3 scripts/reconcile-bookmark-sources.py --help
python3 scripts/import-bookmark-deltas.py --help
```

An apply run requires the exact owner-local approval contract. Import targets
only the private GBrain source through its approved transport; it does not write
Stack skills, trigger a reindex, or choose a paid fallback.

## Card and digest production

`scripts/build-design-intelligence-packet.py` consumes a safe U15 observation
plus its owner-local raw companion. It emits source/delta state, cited design
cards, facts separated from critique and recommendations, reusable principles,
suitable contexts, failure modes, accessibility and motion concerns,
implementation cues, uncertainty, clustered themes, contradictions, and a
quarantined candidate summary or explicit no-action result.

The default analyzer is deterministic and local. An injected analyzer is used
only when an explicit provider-egress contract allowlists exact fields; a model
budget never grants provider authority by itself.

```sh
python3 scripts/build-design-intelligence-packet.py --help
```

## Design-time retrieval

`scripts/query-design-intelligence.py` accepts project, repository, route,
component, viewport, device, brief, code, markup, and screenshot context when
available. It verifies the trusted target manifest, performs source-scoped
exact/text/image retrieval against `x-bookmarks`, reranks deterministically, and
returns three to seven cited results with similarity reasons, freshness,
uncertainty, and model/index versions.

The live adapter exposes only read-only GBrain `search` and `search_by_image`.
Missing image retrieval or a stale index produces a labeled degraded response;
it never starts an import, reindex, configuration change, or paid fallback.

```sh
python3 scripts/query-design-intelligence.py --help
```

## Evaluated learning

“Training Stack” means proposing the smallest cited update to an existing
Stack-owned skill or reference, with narrowly necessary registry, test, and
documentation support. It does not mean weight training or prompt
self-modification.

`scripts/materialize-capability-change.py` requires a separate authorization
bound to the exact packet digest and base commit. It creates a deterministic
owner-local patch in a disposable checkout and proves that the active checkout
is unchanged. It has no branch, PR, merge, install, publication, network, or
active-evidence authority.

`scripts/evaluate-design-intelligence-candidate.py` compares the candidate with
a pinned baseline over frozen development, protected holdout, and rotating
owner-local canary fixtures. It requires at least four material development
wins, bounded variance, a minimum weighted improvement, real task-usefulness
feedback, and no structural, behavioral, visual, accessibility, privacy,
citation, mobile-width, overflow, workflow, critical-data, or HTML failure.
Per-fixture regressions cannot be averaged away.

Synthetic evidence can prove code paths but cannot promote a candidate. A
missing `STACK_DESIGN_EVAL_ROOT` is `blocked-eval`; unstable scores or rubric
disagreement require human review. Passing evidence stops at
`awaiting_approval`.

```sh
python3 scripts/materialize-capability-change.py --help
python3 scripts/evaluate-design-intelligence-candidate.py --help
```

## Weekly campaign

`scripts/run-stack-weekly-intelligence.py` reuses the shared `WorkflowStore`
for child leases and checkpoints. It links source intake, card production,
retrieval, candidate evaluation, the latest maintenance receipt, and a report
under one campaign identity. It never launches maintenance; the maintenance
writer and campaign have separate locks and receipts.

Semantic fingerprints skip unchanged model-heavy work. Completed child
artifacts survive partial failure, resume retries only the failed tail, and
three identical non-transient blockers open a circuit until manual review and
clear. Every owner-local stage receipt contains only digests and safe state.

The coordinator has no built-in provider or source adapter. Running it without
explicit trusted stage adapters fails closed as `adapter_not_configured`; test
adapters prove orchestration without pretending to be live evidence.

The future Codex scheduler contract is Saturday at 09:00 local time. It remains
disabled until separate approval, a persisted contract match, and run-now
proof. Existing Hermes collection/curation stays intake-only, and upstream
maintenance remains separate. After enablement, every eight-day window must
contain a terminal non-duplicate campaign receipt or a visible alert with the
blocking stage, last success, age, and safe restart.

See [`weekly-intelligence-operations.md`](weekly-intelligence-operations.md) for
the operating and recovery contract.
