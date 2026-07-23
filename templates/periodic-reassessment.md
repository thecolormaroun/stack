# Capability periodic reassessment

Review date: `YYYY-MM-DD`
Reviewer: `NAME`
Catalog digest: `SHA256`
Scope: `active | candidate | deprecated | external`

## Evidence snapshot

- Capability and manifest: `CANONICAL_NAME` / `skills/PATH/capability.json`
- Source commit and provenance: `COMMIT` / `SOURCE_IDENTITY`
- Last validation and result: `DATE` / `PASS | FAIL | MISSING`
- Runtime targets and latest receipt: `TARGETS` / `RECEIPT_ID`
- Overlap cluster or related entries: `NONE | NAMES`

## Signals (record independently)

| Signal | Evidence | Interpretation | Required follow-up |
| --- | --- | --- | --- |
| Low usage | `OBSERVATION` | A review prompt only; low usage alone is not auto-archive evidence. | Confirm continuing design/build value or schedule a targeted evaluation. |
| Overlap | `ENTRIES AND DIFFERENCE` | May justify merge, alias, demotion, or retained specialization. | Request item-level disposition review. |
| Upstream abandonment | `PIN, RELEASE, MAINTENANCE EVIDENCE` | May increase maintenance risk without proving removal. | Check license, fork/replace options, and validation. |
| Failed validation | `TEST OR SMOKE RECEIPT` | Blocks active runtime publication or requires remediation. | Hold, repair, or roll back with evidence. |
| Out-of-scope identity | `INCLUSION-TEST RESULT` | Useful work may belong in another system. | Propose a destination; do not delete without approval. |

## Proposed decision

- Proposed disposition: `keep | merge | demote | move | archive | hold-pending-evidence`
- Why this is the smallest safe change: `RATIONALE`
- Human review required: `YES | NO — explain batch-confirmation basis`
- Rollback or destination evidence: `REFERENCE`
- Next review trigger: `DATE OR CONDITION`

No row in this report activates, archives, moves, installs, or publishes a
capability automatically. Usage is one signal among several and never a
usage-only auto-archive rule.
