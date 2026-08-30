# Design intelligence loop

Stack turns approved private bookmark evidence into cited design guidance and
evaluated capability improvements. It does not copy raw X posts into the
repository, create a second search index, or fine-tune model weights. The
approved automatic tail may update one existing Stack-owned skill/reference
candidate per week only after every bounded evaluation, review, merge,
publication, discovery, and rollback gate passes.

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
only the private GBrain source through its approved transport and requires an
owner-local inventory of the existing native source so apply is always
missing-only. The post-import canary parses a source-scoped structured search
result and requires the exact bookmark identity and slug. It does not write
Stack skills, trigger a reindex, embed, or choose a paid fallback.

## Card and digest production

`scripts/build-design-intelligence-packet.py` consumes a safe U15 observation
plus its owner-local raw companion. It emits source/delta state, cited design
cards, facts separated from critique and recommendations, reusable principles,
suitable contexts, failure modes, accessibility and motion concerns,
implementation cues, uncertainty, clustered themes, contradictions, and a
quarantined candidate summary or explicit no-action result.

The packet builder remains deterministic and local. The scheduled Sol/high
automation performs the quality critique from minimized, cited design evidence
after collection. Its bounded three-context Codex budget authorizes critique,
candidate authoring, and independent review; it does not authorize a provider
client, paid fallback, or raw private payload persistence.

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

The production text runner is explicitly enabled only with `--live-gbrain`, a
target manifest, and an expiring owner-local source grant. It pins the audited
GBrain CLI version, source/index/freshness receipt, bookmark locator scopes,
and `gbrain-keyword-fts-no-provider-v1` contract. Only version, source status,
and conservative keyword search commands are permitted; provider calls,
embedding, image search, import, reindex, configuration changes, and paid
fallbacks are denied. Two reads against the same index are intersected and
canonically ordered so unstable backend-only results do not become retrieval
truth. Missing image retrieval or a stale/sparse index is labeled degraded.

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
disagreement reject the candidate. Passing evaluation is necessary but not
sufficient: the automatic tail also requires the full repository tests, a
fresh independent `ship` review, green pull-request checks, merge verification,
and atomic runtime publication with discovery and rollback receipts.

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

The coordinator defaults to unconfigured stages. Its explicit
`--local-adapter-config` path can bind a sealed source snapshot/ledger, target
manifest, retrieval request, and source grant. Live text retrieval re-attests
the current source before campaign no-action reuse, and index version,
freshness date, grant digest, egress contract, and CLI version participate in
the campaign fingerprint. A week with no selected material skill/reference
candidate records `no_candidate_selected`; the full evaluator remains mandatory
once a candidate is selected. See the
[readiness reconciliation](weekly-intelligence-readiness.md).

The Codex scheduler contract is Saturday at 09:00 local time. The live
entrypoint refuses to reconcile or import until that exact active contract is
persisted and a current canonical maintenance receipt is linked. Existing
Hermes collection/curation stays intake-only, and upstream maintenance remains
separate. Authorization contract
`weekly-design-auto-promotion-approved-v1` permits the scheduled Sol/high tail
to advance at most one existing Stack-owned skill/reference change without a
recurring human review. Weak evidence becomes `no_action`, failed gates become
`rejected_no_queue`, and operational outages become `retry_with_alert`.
After enablement, every eight-day window must
contain a terminal non-duplicate campaign receipt or a visible alert with the
blocking stage, last success, age, and safe restart.

See [`weekly-intelligence-operations.md`](weekly-intelligence-operations.md) for
the operating and recovery contract.
