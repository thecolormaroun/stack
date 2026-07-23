# Bookmark curation

Stack turns promising design/build material into reviewable evidence, not an
automatic skill factory. Supported read-only sources are Field Theory/X
bookmarks, Arc bookmark-like snapshots, the authenticated account's public
GitHub stars, public GitHub repositories linked by other sources, and explicit
Hermes link submissions. Private GitHub repositories are excluded unless a
separately authorized private overlay contract applies.

## Path from link to outcome

```text
source or Hermes link
  -> read-only collection / opaque intake ID
  -> relevance, provenance, license, dedupe, priority
  -> bounded human review packet
  -> evaluation and approval
  -> active catalog entry
  -> compiled runtime + target verification + receipt
```

An explicit Hermes link gets a durable intake ID, not a claim that Stack has
changed. Scheduled discoveries and manual links follow the same lifecycle and
must later connect to a no-action, blocked, proposed, or published receipt.

## Collection safety

`scripts/collect-bookmark-candidates.py` uses per-source cursors, canonical
identities, revisions/content digests, and policy digests to make reruns
incremental and idempotent. A stable URL with material source or policy change
returns to triage under the same source identity. A source failure is recorded
without claiming complete coverage or blocking unrelated sources.

Materialization groups all current observations for one canonical identity into
one candidate revision. Its immutable pin binds the observation set, collection
policy, curation policy, and materialization-contract version. Cross-source
duplicates become additional opaque evidence on the same candidate; a new
source revision or policy digest creates a new group pin and re-enters triage.
Repository kind, license posture, and a deterministic design/build relevance
score are derived privately before the packet is redacted.

Raw bookmarks, fetched pages, private metadata, URLs, titles, notes, excerpts,
and local paths remain in an owner-only local ledger. Bookmark text is untrusted
evidence, never instructions. Collection does not mutate browser, Field Theory,
GitHub, or Hermes source data.

Dry-run collection is safe to inspect without advancing cursors:

```sh
python3 scripts/collect-bookmark-candidates.py --ledger /tmp/stack-bookmark-smoke.sqlite
```

Use `--apply` only with the owner-local durable ledger after the source adapter
and policy have been reviewed. It records observations and advances a cursor as
one transaction; it still does not triage, activate, install, publish, or
schedule.

## Triage and human gate

Triage evaluates design/build relevance, existing-catalog overlap, provenance,
license, expected leverage, novelty, evidence quality, implementation cost, and
evaluation cost. It proposes the smallest durable outcome: no action, evidence
attachment, reference update, skill update, new candidate skill, upstream
import/update, or blocked import. A relevant unlicensable repository remains a
blocked import; Stack copies no source content.

The review packet is redacted and bounded by the activation policy. Provenance
review, evaluation review, and publication review are distinct human gates.
Candidate evaluation is immutable-pin, credential-free, network-denied,
temporary-workspace-only, and artifact-only. There is no automatic activation
or publication path.

Only explicit Hermes submissions carry a Hermes callback identifier. Scheduled
Field Theory, Arc, and GitHub discoveries remain receipted in Stack's owner-only
ledger and never attempt to update a nonexistent Hermes inbox row. If the same
canonical item appears in Hermes and another source, the grouped candidate keeps
the explicit Hermes identifier so its later disposition updates the original
inbox record.
