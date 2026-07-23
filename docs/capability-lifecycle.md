# Capability lifecycle

Lifecycle is distinct from artifact type. A skill, reference pack, router,
upstream package, or private overlay can be a candidate or active without
changing what it is.

## States and evidence

1. **Collected** — an intake item has a canonical identity, revision or digest,
   capture time, and source-coverage status in the owner-local ledger.
2. **Triaged** — relevance, artifact type, overlap, provenance, license, and
   confidence are assessed; the public packet keeps only opaque identifiers.
3. **Proposed** — a bounded candidate packet names the smallest durable change
   and proof requirement.
4. **Validated** — applicable structural, behavioral, visual, or workflow
   evaluation evidence exists.
5. **Approved** — a human-reviewed Stack change records the catalog transition.
6. **Published** — compilation, target installation, and discovery verification
   have succeeded for every declared target.
7. **Receipted** — the intake or capability links its disposition, source
   commit, validation evidence, target results, registry digest, and timestamp.

The catalog lifecycle values are `candidate`, `active`, `deprecated`,
`archived`, and `external`. A capability is eligible for runtime compilation
only when it is reviewed, validated, `active`, and names its supported runtime
and publish target.

## Audit dispositions

| Decision | Catalog result | Required companion evidence |
| --- | --- | --- |
| Keep | `active` | Current capability and validation evidence. |
| Merge | Target `active`; former entry `deprecated` | Compatibility alias and provenance transfer. |
| Demote | `active` reference-pack | Consumer check before callable routing is removed. |
| Move | `external` | Approved destination and destination receipt. |
| Archive | `archived` | Explicit removal decision and rollback reference. |
| Hold pending evidence | `candidate` | Named gap and next review trigger. |

Automation can collect, classify, and prepare evidence. It cannot activate,
merge, install, or publish a capability. Human review and required evaluation
are separate gates; approval to activate does not skip publication verification.

## Isolated candidate evaluation

`scripts/evaluate-capability-candidate.py` evaluates an exact Git commit only
after a separate authorization binds an approved provenance review and approved
evaluation-execution review to the candidate packet digest, source pin, and a
repository-owned evaluation profile. Candidate-provided commands are never
run. The evaluator exports the pinned commit into a disposable workspace,
rejects links and executable files, removes ambient credential variables, and
uses the macOS sandbox to deny network access, the parent workspace, and writes
outside that workspace. Each run proves those denials before returning a
bounded receipt. The receipt still leaves activation prohibited until the
evaluation result and publication are separately reviewed.

## Periodic reassessment

Use [`templates/periodic-reassessment.md`](../templates/periodic-reassessment.md)
to reassess active and held capabilities. Low usage, overlap, upstream
abandonment, failed validation, and out-of-scope identity are independent
signals. Low usage alone never auto-archives; any archive, move, demotion, or
merge remains a reviewed disposition with recovery evidence.

Audit dispositions are proposals, not forced outcomes. A reviewer records a
separate final `review_decision`; changing the proposal requires a rationale and
the lifecycle target must match the final decision. For a symmetric overlap
pair, review must select one canonical keep and one merge target rather than
retiring both sides.
