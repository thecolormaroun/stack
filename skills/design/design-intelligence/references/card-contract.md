---
id: design-intelligence.card-contract
name: Design Card Contract
description: Source-faithful, owner-local card and weekly-packet rules for U16.
---

# Design Card Contract

The design card is the durable unit of U16 design intelligence. It is a
derived, versioned, quarantined artifact—not a second knowledge store and not
an input to the active skill until a later review and evaluation gate passes.

## Intake gate

The deterministic gate runs before any analyzer or provider decision:

1. Verify the U15 public observation shape and stable opaque identities.
2. Accept only `accepted` or `revised` completeness states.
3. Reject deleted, missing, rejected, unavailable, malformed, private, and
   personal/non-software observations as owner-local `no_candidate` or
   `quarantined` dispositions.
4. Treat instruction-like source text as quoted evidence. It cannot select a
   tool, change routing, grant approval, or publish an artifact.

Raw text, URLs, paths, media payloads, and restricted metadata remain in the
owner-local source boundary. Cards carry opaque evidence IDs and digests only.
The CLI may hydrate a public-safe U15 snapshot with `--ledger`; this is a
read-only identity join against the owner-local U15 observation ledger.
Missing raw companions are quarantined rather than guessed.

## Card fields

Every card keeps these concerns separate:

- `visible_facts`: directly observed or explicitly supplied facts.
- `interpretation_critique`: interpretation of those facts, with context.
- `reusable_principle`: the portable design lesson.
- `suitable_contexts`: where the principle is appropriate.
- `anti_pattern_failure_mode`: where it fails or should not be copied.
- `accessibility`: observed accessibility evidence and unknowns.
- `motion`: observed motion evidence and unknowns.
- `responsive_behavior`: observed responsive evidence and unknowns.
- `implementation_cue`: a bounded implementation translation.
- `uncertainty`: missing evidence, disagreement, or confidence limits.
- `evidence_citations`: opaque source identities, capture/revision times, and
  content/media/link digests for every surfaced claim.

Screenshot-only evidence may describe what is visible. It must not claim
unseen hover, transition, keyboard, responsive, or state behavior. Put those
limits in the relevant `unknown` or `uncertainty` arrays.

## Lineage and revision

Thread, article, and Arc duplicates collapse into one `lineage_id`, retaining
each source-specific evidence citation and a lineage graph. Conflicting
explicit claims stay as separate card revisions under the same lineage and
are reported in the packet's `contradictions` array.

The card revision is content-addressed by the lineage, claim, evidence set,
analysis, and derivation digests. Changes to prompt, model, sampling, policy,
configuration, or code produce a new `revision_id`; they never overwrite an
earlier card. `supersedes_revisions` records an owner-local prior packet when
one is supplied.

## Egress and promotion

Model egress is default-deny. The builder has no live provider client. An
injected fake analyzer can run only when the input carries an explicit
approved provider contract naming the provider, exact allowed fields,
`opaque-identities-and-digests-only` redaction, no retention, no training use,
and opaque-only log redaction. The fake receives only the allowlisted
opaque/digest context. Its output is
whitelisted to card analysis fields; it cannot set status, routing, approval,
or publication state.

Generated cards, critique, reusable patterns, retrieval updates, and candidate
changes remain `quarantined`/`pending_quarantined`. The packet is written only
to an owner-local output path outside the public repository. It never mutates a
skill, reference, source corpus, retrieval index, or promotion state.
