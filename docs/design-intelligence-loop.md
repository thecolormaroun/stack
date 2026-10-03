# Design intelligence loop

Stack turns approved private bookmark evidence into cited design guidance and
evaluated capability improvements. It does not copy raw X posts into the
repository, create a second search index, or fine-tune model weights. The
approved automatic tail may update existing Stack-owned skill/reference
candidates without an arbitrary weekly count or byte ceiling, only after every evaluation, review, merge,
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

Evidence identity uses `source-revision-content-v2`: it binds the source,
canonical bookmark, native revision digest, and observed content digest.
Classification or enrichment changes at an unchanged source timestamp append
a new observation; they never invent a native revision or overwrite old rows.
Existing v1 evidence remains readable by its original ID. The first v2 intake
adds a current observation for each captured row, even where an identical v1
row already exists; later identical captures are idempotent. Zero-delta checks
compare content as well as native revision, not opaque ID format alone.

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

The separate `scripts/run-design-intelligence-evaluation.py` collector executes
a reviewed, SHA-256-bound local HTML manifest. It records viewport screenshots,
accessibility snapshots, overflow measurements, page-error counts, and explicit
primary-action assertions for baseline and candidate. It reuses `WorkflowStore`
leases and verified checkpoints; input or artifact drift blocks resume. A live
owner-local execution lock prevents overlapping collectors even if a lease
expires during a suspended or slow browser command. The collector renews its
owner-checked lease before browser commands and checkpoints, and only repairs
an exact empty planned run interrupted before its child was added. Outputs
remain owner-local and include `evaluation_status: not_evaluated` and
`human_task_usefulness: pending`. This is objective evidence collection, not a
judge, score generator, or promotion authorization.

The collector currently accepts only `content_scope: synthetic_non_private`.
Its `self-contained-data-url-csp-and-abort-external-requests` policy requires
HTML of at most 64 KB and an empty external asset list. It renders the pinned
HTML from a deterministic data URL with a restrictive CSP, and installs
HTTP(S) and file request abort routes before navigation. External references
inside the HTML cannot load; inline code and data resources are covered by the
HTML digest. The collector source digest, executable helper digests, and policy
revision are bound into run records and final receipts, so prior captures cannot
resume under changed execution code. Browser commands invoke the pinned resolved
executable and recheck its digest before execution. This is not whole-browser or daemon egress isolation, so
private-source HTML is rejected. The checked-in
browser-smoke fixtures exercise the collector without private content; they
are not frozen quality-evaluation or human-usefulness evidence.

The weekly local adapter can opt into this collector with a reviewed manifest
and candidate/materialization digest bindings. It verifies all frozen split
cases before execution and retains collector output under a canonical digest
that is independent of weekly run IDs and score-result files. Each campaign
links the state-relative receipt path and canonical receipt digest. Candidate
workflow, overflow, page-error, or incomplete-observation evidence blocks
immediately; a baseline workflow failure may remain comparison evidence when
candidate workflow, overflow, and page-error observations report no failure.
Those measurements remain render-binding-unverified. Both the inner collector
lease and outer campaign lease stay owner-checked, and completed variants resume
without replay.
Missing or partial score results remain retryable without opening a failure
circuit. The collector has no reviewed producer that binds rendered HTML assets
to the candidate packet, so collected candidate measurements remain explicitly
render-binding-unverified. Complete receipt-bound scores stop at
`candidate_evaluation_render_binding_unavailable`; they do not reach the
evaluator. This wiring is disabled in the live configuration until a real
reviewed harness is supplied. It does not manufacture fixtures, scores,
reviewer identity, human task feedback, or a passing candidate.

```sh
python3 scripts/materialize-capability-change.py --help
python3 scripts/evaluate-design-intelligence-candidate.py --help
python3 scripts/run-design-intelligence-evaluation.py --help
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
to advance every independently material existing Stack-owned skill/reference
change sequentially without recurring human review. Weak evidence becomes `no_action`, failed gates become
`rejected_no_queue`, and operational outages become `retry_with_alert`.
After enablement, every eight-day window must
contain a terminal non-duplicate campaign receipt or a visible alert with the
blocking stage, last success, age, and safe restart.

See [`weekly-intelligence-operations.md`](weekly-intelligence-operations.md) for
the operating and recovery contract.
