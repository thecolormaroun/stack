# Stack refactor completion audit

Date: 2026-07-18

Verdict: **not yet at Definition of Done**. Maroun approved every audit
recommendation on 2026-07-19, the native-owner migration is applied, and the
first live apply-mode collection and curation proofs now exist. Evidence-backed
activation, runtime publication, and live scheduling retain separate gates. This document
distinguishes implemented mechanisms from completed product outcomes so green
tests are not mistaken for deployment approval.

## Current proof

- The pre-migration catalog contained 145 capabilities. The verified
  post-migration catalog contains 136: nine native-integrated operational
  capabilities were removed and four duplicate implementations became
  deprecated compatibility sources.
- The estate audit covers 810 of 810 tracked artifacts, 145 capabilities, 97
  collections, and 52 nested callable entrypoints.
- The audit remains non-mutating and records `human_approval: approved` plus a
  scoped approval receipt. All 145 capabilities have final review outcomes:
  132 keep, 4 merge, and 9 move.
- The corrected audit uses capability identity metadata rather than incidental
  safety text. Its two bounded decision packets contain 23 item-level choices:
  9 approved moves, four canonical merge winners with four deprecated aliases,
  and 6 approved orchestration-support keeps. Another 122 capabilities were
  batch-confirmed as unchanged keeps.
- A live read-only collection run observed 1,157 Field Theory items, 342 Arc
  items, 14 public GitHub stars, 17 verified public repositories derived from
  bookmark content, and 311 Hermes link rows. The receipt correctly remained
  partial because some linked repositories were inaccessible; it advanced no
  cursor and mutated no source corpus.
- The live Hermes link database was backed up, upgraded through the versioned
  migration, and restricted to owner-only mode before the successful dry run.
- Collection and curation wrappers are installed owner-only. Hermes reports no
  scheduled jobs; its gateway is stopped.
- The first owner-local collection apply recorded 1,648 canonical items from
  1,843 observations. Its immediate rerun created zero new canonical items and
  recorded only three genuinely changed GitHub revisions. Partial linked-repo
  coverage remained explicit.
- The corrected live curation materializer groups cross-source observations by
  canonical identity, retains policy-sensitive group pins, derives redacted
  relevance/repository/license posture, and presented exactly three of 1,648
  candidates. The apply receipt marked only those three; the next dry run had
  zero pin overlap and retained the remaining 1,642 for later bounded packets.
  One grouped explicit Hermes submission updated its original inbox row to
  `proposed`; scheduled-source rows did not attempt Hermes callbacks.
- The fixed-policy candidate evaluator now exports an exact Git commit into a
  disposable macOS sandbox and proves network, ambient-credential,
  parent-workspace, private-mount, and outside-write denial before emitting a
  redacted result. Candidate commands are never executed and activation remains
  separately review-gated.
- A synthetic private reference pack was compiled and resolved by the
  owner-local `codex-local` target, excluded from an unauthorized target, and
  represented publicly only by an opaque verification receipt and digest.
- Runtime compilation now supports bounded canonical compatibility aliases and
  fails on alias collisions, allowing approved merges to preserve old names
  without compiling deprecated implementations.
- Estate `keep` and runtime `active` are now separate states. The migration no
  longer converts every reviewed keep into an unvalidated active capability.
- The post-migration audit covers 783 of 783 present artifacts and all 136
  callable entries. Deleted tracked paths are excluded rather than resurfacing
  as phantom capabilities.
- Verification passes: 108 Stack tests, 92 Stack subtests, 15 focused Hermes
  tests, deterministic catalog validation, syntax checks, and the public
  sensitive-content scan.

## Requirement audit

| Requirement | Status | Authoritative evidence | Remaining gate |
|---|---|---|---|
| R1 Product identity | Realized in the source estate | `README.md`, architecture, approved 132/4/9 map, native integration receipt, and 136-capability post-audit | Select validated capabilities for active runtime publication; do not activate the whole kept estate by default. |
| R2 Complete estate audit | Complete and approved | `capability-audit.json` reports 100% coverage and final reviewer state | None; post-migration re-audit remains downstream. |
| R3 Explicit disposition | Complete; native move integration verified | Audit, two bounded packets, review decision artifact, native-owner integration receipt, and per-move consumer receipts | Apply source removals together with the reviewed merges, then run the post-migration audit. |
| R4 Canonical catalog | Implemented | Capability-local manifests, schema, generated aggregate, reproducibility test | Approved entries still need reviewed lifecycle/runtime metadata. |
| R5 Artifact separation | Implemented and applied | Lifecycle docs, private-overlay proof, native-owner receipt, source removals, compatibility tombstones, and post-audit | Activation/publication remains separate. |
| R6 Bookmark sources | Implemented and live-read verified | Field Theory, Arc, GitHub stars, derived GitHub repositories, and Hermes adapter receipt | Inaccessible linked repositories remain visible as partial coverage rather than silently accepted. |
| R7 Incremental/idempotent intake | Implemented and live-apply verified | Transactional cursor tests plus first apply/rerun receipts with zero new canonical duplicates and material-change re-entry | Inaccessible linked repositories correctly keep source coverage partial. |
| R8 Relevance/dedupe/priority | Implemented and live verified | Canonical grouping, policy-sensitive pins, repository/license/relevance derivation, bounded three-item apply receipt, deferred queue | Candidate review/evaluation remains human-gated by design. |
| R9 Review-gated promotion | Implemented and sandbox-proven with a reviewed fixture | Candidate preparation rejects execution privileges; fixed-policy evaluator proves isolation; catalog compiles candidates out | A real intake candidate still requires its own human provenance and evaluation authorization. |
| R10 Publication proof | Mechanism implemented | Attested compile/install, verifier, rollback, and Hermes receipt-chain tests | No active catalog or declared live targets exist to cut over. |
| R11 Privacy/source trust | Implemented and live-fixture verified | Owner-only ledger/DB, authorized local private-overlay proof, redacted receipts, sensitive-content scan | Adding actual proprietary packs remains an explicit owner-local opt-in, not a public-repository step. |
| R12 Continuous pruning | Documented and templated | `templates/periodic-reassessment.md` | First post-migration reassessment cannot occur before migration. |

## Implementation-unit audit

| Unit | Status | What proves it | What prevents completion |
|---|---|---|---|
| U1 Catalog | Complete mechanism and migrated source estate | Schema, 136 local manifests, aggregate builder/tests, post-migration receipt | Evidence-backed activation metadata remains intentionally selective. |
| U2 Estate audit | Complete and approved | Deterministic 810-artifact audit, calibration digest, review artifact, and approval receipt | None before post-migration re-audit. |
| U3 Migration | Complete | Approved 132 keep / 4 merge / 9 move map, native-owner receipt, deprecated compatibility sources, rebuilt catalog, and 100% post-audit | None; later activation is U4, not an implicit migration side effect. |
| U4 Runtime publication | Complete mechanism, no cutover | Deterministic compiler, compatibility aliases, attestation, atomic installer, required verifier, rollback tests | Empty live target config and no active post-migration catalog; Codex/Claude/Hermes discovery smoke remains pending. |
| U5 Intake | Complete through first manual apply cycle | Live collection apply/rerun, canonical grouping, mutable-policy pins, bounded curation apply, partial-source receipts | Recurring scheduling is intentionally absent. |
| U6 Evaluation/activation | Evaluation mechanism complete; real candidate review pending | Exact-pin export, real macOS sandbox-denial probes, bounded receipt, and malicious executable fixture | A real intake candidate still needs human provenance/execution review; activation waits for the post-migration active catalog. |
| U7 Hermes | Manual lifecycle integration complete; scheduling intentionally absent | Migrated DB, owner-only wrappers, collection/curation apply receipts, explicit-link `proposed` callback, no cron jobs | Gateway stopped; explicit scheduling approval missing. |
| U8 Governance | Complete mechanism | README, architecture/lifecycle/intake/runtime/private docs and reassessment template | Must be refreshed after actual migration/cutover. |
| U9 Private overlay | Complete and owner-local live-fixture verified | Authorized compile/resolution, unauthorized exclusion, owner-only modes, revocation/leak tests, and `artifacts/private-overlay-verification/2026-07-18.json` | Real proprietary material can be added later without changing the public contract. |

## Definition-of-Done blockers

1. A deliberately small first set of kept design/build capabilities must receive
   real validation evidence and active lifecycle metadata; review alone is not
   activation proof.
2. Codex/Claude/Hermes runtime targets must be declared,
   compiled, installed, discovered, and receipted against one catalog digest and
   Stack commit.
3. After audit approval, an authorized real candidate and active catalog
   transition must be carried through evaluation, publication, and receipt to
   prove the integrated promotion path rather than only its isolated stages.
4. After successful live manual collection and curation receipts, Maroun must
   explicitly approve scheduler enablement; only then may the gateway/jobs be
   enabled and next-run times verified.

Until those gates pass, the correct state is: native-owner migration complete,
manual ingestion live and review-only, kept capabilities still candidate unless
individually validated, runtime targets empty, and live schedules absent.
