---
id: stack.capability-activation-packet-contract
name: Capability Activation Packet Contract
description: Redacted, review-gated contract for Stack capability candidate packets.
---

# Capability Activation Packet Contract

Candidate packets are decision aids, not activation requests. They may contain only opaque intake identifiers, source identifiers, source pins, scores, disposition, and redacted evidence summaries. They must not contain source URLs, titles, notes, excerpts, local paths, credentials, or raw observations.

## Bounded triage

Rank candidates by leverage, novelty, evidence, implementation cost, and evaluation cost. Put no more than the configured decision cap in `candidates`; keep every lower-ranked record in `deferred` with its opaque identifier, rank, and disposition. Do not silently drop overflow.

The only smallest-change dispositions are `no-action`, `evidence-attachment`, `reference-update`, `skill-update`, `new-candidate-skill`, and `upstream-import-update`. An unlicensed upstream repository is `blocked-import`, not an import disposition.

## Activation gates

Every proposed change remains blocked until a human completes provenance review and evaluation review. Evaluation uses an immutable source pin in a disposable sandbox with no ambient credentials, private-corpus mounts, or network access; it writes only bounded artifacts in a temporary workspace. Catalog activation and runtime publication require a separate human publication review and their own U4 receipt.

Candidate preparation never invokes install, merge, scheduler, runtime replacement, or catalog activation.
