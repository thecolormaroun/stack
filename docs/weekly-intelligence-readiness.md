# Weekly intelligence readiness reconciliation

Evidence date: 2026-08-29. Baseline: `codex/stack-weekly-intelligence` at
`d0f10ae`. This is a readiness record for the existing
[master plan](plans/2026-07-17-001-refactor-design-build-stack-plan.md), not a
replacement roadmap. Local corrections remain uncommitted. The implementation
has a fresh independent **SHIP** verdict and is pending branch delivery plus
the in-place Codex automation update.

## 2026-08-29 activation-candidate evidence

- Field Theory reconciliation read 1,246 observations into an owner-local
  sealed snapshot/ledger. The second read was a zero-delta identity/revision
  pass. Missing-only import found 713 pre-existing GBrain identities, imported
  533, then produced an indexed duplicate no-action receipt. Direct X/OAuth and
  paid embedding paths stayed disabled.
- Live retrieval now requires a separate expiring owner-local source grant,
  pins GBrain CLI `0.42.67.0`, and invokes `BrainEngine.searchKeyword`
  directly through Stack's pinned Bun adapter. The adapter never configures an
  AI gateway, hybrid search, embeddings, reranking, expansion, or query cache.
  It runs two independent reads, compares full candidate bytes, and re-attests
  the source afterward. Two identical live requests returned the same five
  cited result identities and response digest with zero provider calls.
- Manual campaign `weekly-live-canary-3` completed all six stages and ended
  `awaiting_approval` with health `pass`. An immediate identical campaign
  returned terminal `no_action`, reused exact persisted artifacts, and left the
  circuit at zero strikes.
- The current 310-card deterministic packet is quarantined but not materially
  specific enough to justify a skill/reference update. The evaluation stage
  therefore records `no_candidate_selected`; no synthetic feedback, patch,
  promotion, installation, or publication is represented as training.
- A maintenance audit is linked and current. It discovered upstream updates
  but remains a separate approval-bound workflow and made no pin/runtime change.

The remaining activation gate is branch delivery, the in-place update of the
existing weekly Stack automation, and a real automation wake receipt. The
coordinator now reads the persisted Codex automation TOML directly; it rejects
caller-authored scheduler booleans. Four-week operating history cannot exist
at activation time and remains follow-up health evidence.

## Verified local evidence

- The pre-change repository suite passed 334 tests. Regression tests reproduce
  and close cross-campaign checkpoint reuse, incomplete maintenance receipts,
  missing retrieval target bindings, error-as-empty retrieval, aggregate-only
  evaluation scores, stale result-to-candidate bindings, duplicate repetitions,
  unverified retrieval inputs, ignored CLI JSON inputs, and tampered checkpoint
  artifacts. The final verification count is recorded at closeout below.
- A read-only pass over the active Field Theory SQLite source enumerated 1,246
  observations, with no duplicate identities or cursor error. Two reads had
  identical identity/revision sets. This proves local database enumeration,
  not complete or fresh capture from X. Media coverage was partial; optional
  API parity was not configured. No source watermark or record was changed.
- Feeding those observations directly into the existing deterministic packet
  builder produced 315 unapproved cards and 1,246 dispositions in memory.
  Its privacy checks passed, retrieval-truth remained false, and provider and
  analyzer call counts were zero. No private packet or raw row was persisted.
  This proves a local source-to-packet handoff, not visual critique quality.
- The maintenance reader validated the existing persisted receipt observed at
  `2026-08-23T20:06:16Z` and linked its exact digest. It did not launch
  maintenance or acquire its lock. This receipt will age out; this observation
  does not establish ongoing maintenance health.
- The live weekly state directory and `STACK_DESIGN_EVAL_ROOT` were absent at
  the initial check. `GBRAIN_ACTIVE_EMBEDDING_CONTRACT` was unset. No live
  scheduler, embedding, evaluation, or runtime-publication proof follows.

## Independent review

The first post-live final-review wave returned **fix-first**. Two fresh,
metadata-verified Terra/high reviewers independently found that generic GBrain
search could invoke embeddings, repeated search calls could be cache echoes,
grant expiry trusted a caller-backdated timestamp, the all-preexisting import
path could skip its index canary, and self-issued scheduler JSON could mark
health green. Stack now uses a direct uncached keyword adapter, wall-clock
grant expiry, a mandatory all-preexisting canary, and direct persisted
automation verification. These corrections require a new final verdict before
activation.

The initial bounded review used two independently dispatched, metadata-verified
Terra/high reviewers: correctness and the distinct source/privacy surface.
They found three P1 issues: target isolation, canonical maintenance receipt
validation, and run-scoped checkpoints. A third fresh Terra/high validator
confirmed all three. Target isolation was corroborated by both reviewers;
this is same-model, not cross-model corroboration.

The host sandbox was disabled despite read-only review instructions. The
initial reviewers' before/after tracked diff digest was identical; protected
untracked files were preserved. Review coverage was bounded, not the full
default persona roster. A subsequent single reviewer found no simplification
issues across reuse, quality, and efficiency lenses; these were three lenses
in one context, not three independent reviews.

Earlier quota preflights allowed Terra/Luna only, with a three-executor cap. The named
Luna and Terra complex-worker profiles were unavailable. Adapter implementation
used an explicitly selected and metadata-verified Terra/Max fallback. No
cross-provider review or paid fallback ran. The required fresh Sol gate cannot
be represented as satisfied by a Terra review.

An earlier post-implementation Terra/high reviewer returned **ship for local
preparation only**, with no actionable reproducible findings. It independently
ran the ten adapter tests and checked the diff. Native metadata confirmed its
role/model/effort and disabled sandbox; exact tracked-diff and new-source hashes
were identical before and after review. The final wave's quota telemetry was
unavailable, so preflight constrained it to one Terra/Luna executor. No Sol
override was granted. This was independent local review, not live acceptance,
and it was superseded by the later activation review below.

The first activation review wave returned **fix-first** from both fresh
Terra/high reviewers. Retrieval review found that authorization could expire
between reads and that an arbitrary configured database endpoint could be
connected before proving it local. Activation review found that mutable intake
preceded scheduler/maintenance validation, path checks erased symlink evidence,
and the subprocess environment inherited caller-controlled values. The
corrected implementation re-checks grant expiry before every subprocess,
allowlists the owner-local GBrain backend before connection, preflights the
persisted automation and canonical maintenance receipt before mutation, rejects
unexpected symlink ancestors, and pins the real account environment. These
fixes invalidate the earlier verdict and require a new final review.

The next recheck also returned **fix-first** on two narrower contract defects:
persisted automation validation did not yet walk every ancestor or reject a
group-writable TOML, and detailed retrieval failure causes were being placed in
the schema's bounded degradation enum. Stack now validates the whole lexical
automation path plus file write modes before mutation, and exposes a separate
schema-defined safe `reason_code`. Regression tests cover both scheduler
redirect modes and schema-conformant expiry/backend failures. These latest
fixes likewise require a fresh verdict.

The retrieval gate then found that Bun could auto-load a working-directory
`.env` between Python's config attestation and the helper connection. The live
transport now invokes Bun with env-file loading disabled, supplies only its
pinned environment, binds the exact owner-only configuration bytes by SHA-256,
and rechecks that binding around upstream config loading. A live two-read
keyword canary returned five source-scoped verified rows with byte-identical
output and zero provider configuration.

The next fresh ship gate found the same ambient-process risk in the bookmark
intake executable. Source writes and all-preexisting canaries now run through
the pinned Bun executable with env-file loading disabled, a fixed owner-local
working directory, a minimal environment, and the same local-backend config
attestation. Regression coverage injects hostile ambient GBrain/database,
`PATH`, and temporary-directory overrides and proves neither live path inherits
them. This correction invalidates the prior verdict and is awaiting one final
independent recheck.

That recheck found two final fail-closed defects: an `accepted` import marker
could become `no_action` before its current source canary indexed, and the
version/source-status attestation commands did not yet share the hardened Bun
boundary. A duplicate accepted marker now remains non-terminal and exits
nonzero until the current canary is indexed. Version and source-status reads
now also disable env files, use the minimal environment, and run from the fixed
owner-local GBrain directory. Tests reproduce the repeated-marker case and a
hostile caller working directory containing database overrides. These fixes
again require a fresh final verdict.

The replacement gate then required executable pinning in addition to the fixed
environment. Every GBrain subprocess now resolves the explicit Homebrew Bun
path to its current absolute owner-controlled executable, rejects missing,
relative, non-executable, or group/world-writable targets, and invokes only the
validated resolved path. Source-write, canary, version, and source-status tests
assert that exact executable; negative tests prove a bare `bun` is rejected
before any subprocess. The real pinned version command returned GBrain
`0.42.67.0` with env-file loading disabled.

The next gate extended that chain-of-trust to the script Bun executes. The
live adapters now accept only the installed default GBrain CLI path, re-resolve
and validate its owner-controlled executable bytes before each operation, and
pass only the validated target to Bun or the keyword helper. Public CLI path
overrides were removed. Negative tests prove arbitrary absolute scripts are
rejected before source writes, status reads, or keyword subprocesses.

The subsequent live-entrypoint review caught one stale `--cli` argument and a
remaining config race in direct GBrain operations. The emitted live import
command now matches the override-free parser. Version, source status, and
source write use a single pinned Stack wrapper that verifies the exact installed
GBrain package and version, copies the attested config bytes into an ephemeral
owner-only snapshot, loads an explicit local engine from that snapshot, and
rechecks the snapshot around the operation. The import remains `--no-embed`;
the snapshot is removed on exit. A real read-only wrapper canary returned the
expected GBrain version and the `x-bookmarks` source with 1,865 pages.

The latest review moved keyword retrieval onto that same frozen-config wrapper
and removed the separate live-config helper. The child rejects database,
GBrain, provider-key, token, secret, and provider-endpoint overrides before any
operation. Source status now emits only six attestation fields; local clone
validation happens inside the wrapper and returns `local-attested` without a
path or remote URL. Real canaries returned three source-scoped keyword rows,
zero unverified rows, and no residual config-snapshot directories.

The runtime-chain recheck then required the Bun identity itself to be exact,
not merely absolute and owner-owned. Both Python transports now require the
canonical Homebrew launcher to resolve to the installed `1.3.14` binary, and
the TypeScript child attests its own `process.execPath` before reading input.
Relative and absolute alternate executables are rejected before subprocess
dispatch. The real pinned version canary still returns GBrain `0.42.67.0`.

### Applied

- #1: Required per-result target bindings and disabled the uncontracted live
  transport; unauthorized or unverified records cannot supply evidence.
- #2: Reused the canonical persisted maintenance receipt validator and rejected
  future observations rather than accepting minimal self-declared receipts.
- #3: Scoped completed checkpoints to their run and bound every reused artifact
  to exact persisted bytes and the matching stage fingerprint.

### Actionable findings

The activation-wave findings above are implemented and locally verified. A
fresh independent verdict is still required because every implementation fix
invalidates the prior verdict.

### Coverage and verdict

Correctness, privacy/contracts, checkpoint reuse, evaluator bindings, artifact
publication safety, runtime isolation, and adapter simplicity were reviewed.
The final metadata-verified Terra/high reviewer returned **SHIP** with no
actionable P1/P2 findings. Quota policy did not allow the preferred Sol gate;
this is independent Terra/high acceptance, not cross-model corroboration.

## Requirements and implementation units

The table covers the weekly extension, R23-R44 and U14-U20. Earlier U1-U13
work is a dependency, not newly certified by this resume.

| Scope | Local status | Remaining evidence or work |
| --- | --- | --- |
| U14 / R41 routing | Executable resolver fixtures exist and pass | Installed Claude/Codex runtime parity is not proven by repository fixtures. |
| U15 / R23-R27, R40 | Provenance/reconciliation code; real local enumeration and zero-delta identity check | Approved live source contract, historical/folder/media reconciliation, fresh X capture, and private corpus synchronization. Direct X stays disabled. |
| U16 / R28-R29, R32 | Actual deterministic source-to-card handoff and quarantined packet | Independent visual/task critique evidence; model egress contract if model analysis is selected. |
| U17 / R30-R32 | Target/grant isolation, continuous wall-clock expiry, local-backend allowlist, direct keyword-only retrieval, full-byte stable reads, source re-attestation, citations and live canaries pass | Image retrieval remains deliberately unavailable; it never falls back to a paid provider. |
| U18 / R33-R36 | Isolated materializer and stricter candidate-bound evaluation contracts | Reviewed real harness, protected holdouts, independent task feedback and exact materialization authorization; proposal generation is not automatic promotion. |
| U19 / R37 | Existing discovery/maintenance proposal implementation; canonical receipt reuse | No new live upstream discovery or pin replacement was authorized or performed here. |
| U20 / R38-R39 | Shared WorkflowStore lifecycle, live local adapters, deterministic weekly entrypoint, changed/no-action campaigns, owner-local receipts, and final independent review verified | Delivery and the in-place external automation update remain. |
| R42 | Approval boundaries retained | Source sync/backfill, OAuth, spend, install, publication, push/merge, scheduler and promotion remain separate approvals. |
| R43 | Active repository scheduler contract and direct Codex automation verification tested; self-issued JSON is rejected | Update the existing automation in place and obtain a real wake receipt; then require a non-duplicate terminal receipt or alert each eight days. |
| R44 | Generated cards/results stay quarantined; unverified live extraction results rejected | Trusted source/runtime attestation and harness provenance remain prerequisites; self-declared flags are not independent proof. |

### Explicit architecture gates

- **Retrieval substrate falsification:** installed GBrain `SearchResult`
  (`src/core/types.ts`) has source scope and an `unverified` marker but no
  per-target authorization. Stack therefore binds live results only after a
  separate owner grant, restricts locators to the approved bookmark scopes,
  rejects unverified extractions, repeats uncached keyword reads, and requires
  identical candidate bytes. A successful empty response is not a positive
  retrieval-quality canary.
- **Model egress:** installed GBrain `search_by_image`
  (`src/core/operations.ts`) can call Voyage, and local CLI callers use their
  own provider credentials. Read scope is not zero-cost or no-egress proof.
  No such call was made. Text retrieval uses direct keyword search and does not
  configure or require an embedding provider.
- **Freshness:** document `effective_date` is not an index update timestamp.
  Placeholder model/index labels in the legacy CLI transport are not live
  attestation. Establish actual index age and execution versions in the live
  integration before accepting retrieval-quality evidence.
- **Candidate materiality:** all dimensions, candidate/materialization/manifest
  digest bindings and unique repetitions are mandatory. Existing effect-size,
  aggregate, variance and holdout thresholds remain unchanged. A feedback
  field saying `real` is still not proof of a real task; the harness and its
  captured evidence need separate review.
- **Workflow-store reuse:** the coordinator reuses the existing WorkflowStore
  class and schema in its own state instance. It does not share maintenance's
  database or lease. No new workflow engine was introduced.
- **U8 ordering:** the roadmap phase summary places U8 early, while its unit
  dependency table requires U1-U7 and U9-U13. Treat early U8 as draft runbooks
  only; operational completion follows those dependencies and U15-U19 before
  U20 activation. This resume does not mark U8 complete or rewrite plan intent.
- **OAuth lifecycle:** the optional X path validates a networkless policy
  contract only. Consent, token refresh/rotation/revocation, scope parity and
  provider limits have not been exercised. Keep it disabled; it is optional
  and must not become a prerequisite for the Field Theory path.
- **Private runtime attestation:** owner-only manifests and caller identity
  checks do not prove the installed runtime's identity, current authorization,
  expiry or revocation. An actual authorized target and negative isolation
  canary are required before private runtime delivery.

## Activation decision

The fresh final review returned `SHIP`. Deliver the branch, update the existing
`weekly-design-intelligence-loop` automation in place for Saturday
09:00 `America/Los_Angeles`, verify the exact persisted contract, and obtain a
real wake receipt. Source synchronization is approved for this local Field
Theory to x-bookmarks lane. Promotion/publication remains a separate decision.

## Closeout verification

- Sanitized full repository suite: **401 tests passed** (50.225 seconds).
- Focused weekly coordinator/adapter suites: **29 passed**; the fresh reviewer
  independently reran the ten adapter tests.
- Capability classification and registry checks passed: **141/141 complete**.
  Layout dry run, upstream metadata validation, sensitive-content scan, and
  `git diff --check` passed. Upstream metadata validation did not fetch or
  replace upstreams.
- The actual CLI integration persists a source snapshot and quarantined packet
  from a synthetic owner-local export, then records a partial receipt at the
  missing retrieval prerequisite. Offline transport tests run the real retrieval
  code; the evaluation adapter runs the real evaluator against synthetic harness
  fixtures and stops at `awaiting_approval`. None is live canary evidence.
- All three pre-existing tracked skill edits and six protected untracked files
  retained their exact hashes. HEAD remains `d0f10ae`; changes are uncommitted.
- Nothing was pushed, merged, installed, published, promoted, scheduled or
  enabled. No source record was marked processed. No live retrieval, OAuth,
  provider fallback, credential rotation or log cleanup was performed.
- GBrain durable update remains unattempted because the active embedding
  contract is unavailable; no paid fallback was used.

Safe local implementation is handed off. Resume at the Sol acceptance and
approved live contract/canary boundaries, not scheduler enablement.
