---
id: design-intelligence.promotion-rules
name: Design Intelligence Promotion Rules
description: Evidence, eval, review, and publication gates for automatically turning digest findings into bounded Stack skill updates.
---

# Promotion Rules

The loop compounds taste only when a finding is material, improves eval
outcomes, survives independent review, and completes verified publication.

## Default Safety

Source intake must not mutate:
- Arc browser state.
- Field Theory bookmark corpus.
- X/Twitter account state.
- GBrain source roots.
- Vault notes.
- critique logs.

Source collection is read-only. Promotion runs separately under exact contract
`weekly-design-auto-promotion-approved-v1`, processes every independently
material candidate sequentially, and uses an isolated branch plus pull request
for each candidate. It has no per-run candidate-count, changed-file, or byte
ceiling. The active checkout is never the materialization surface.

## Candidate Thresholds

A finding can become a skill candidate when at least one is true:
- the same pattern appears in 2 or more independent sources.
- a bookmark explicitly names a reusable design technique.
- a prior critique log issue recurs at least twice.
- the pattern fixes a hard eval failure such as mobile overflow, card nesting, unreadable density, fake data, or decorative slop.

## Proposal Requirements

Every candidate must include:
- evidence links or local source references.
- the exact target skill/reference file.
- the smallest proposed text change.
- an idempotency note explaining why this is not already covered.
- a rollback path binding the current file digests until every automatic gate passes.

## Eval Gate

Use an approved design-skill eval harness when available. The harness is an
optional local tool and is not bundled with Stack.

Scope the gate to the actual candidate bundle and `codex-current`; do not run unrelated historical bundles when evaluating one candidate change.

If `STACK_DESIGN_EVAL_ROOT` points to a reviewed harness checkout, a scoped run
can use:

```bash
cd "$STACK_DESIGN_EVAL_ROOT"
EVAL_BUNDLES="codex-current design-intelligence-v1" \
EVAL_PROMPTS="001-operational-dashboard 002-productivity-app 003-landing-page-with-assets 004-existing-page-redesign 005-data-workflow" \
FINAL_HTML_ONLY=1 IGNORE_USER_CONFIG=1 RUN_ID=design-intelligence-gate \
  scripts/evaluate-design-skills.sh run-matrix
```

If the variable or harness is unavailable, label the candidate
`candidate - blocked on eval`; do not guess a workspace path.

Promotion rule:
- candidate beats `codex-current` on at least 4 fixtures.
- no hard fails on mobile width, content overflow, missing primary workflow, fake critical data, or broken HTML.
- screenshot/rubric evidence is saved with the run.

Result envelopes for every split must bind `candidate_packet_digest`,
`materialization_receipt_digest`, and `manifest_digest` to the exact evaluated
inputs. A result from another patch or fixture manifest is not reusable.
Every baseline and candidate score must include all configured dimensions;
aggregate-only scores cannot demonstrate the per-dimension regression gate.
Repetition identifiers must be distinct positive integers within each fixture.
These structural checks do not attest that feedback came from a real task:
the reviewed harness and saved independent feedback remain separate gates.

If the candidate is useful but the eval is not run, label it `retry_with_alert`, not `promoted`.

## Runtime Promotion

The approved automatic tail may create or update one lineage-bound pull
request at a time, merge it after all required checks pass, and publish every
independently material candidate to Claude and Codex. It has no candidate,
changed-file, or byte ceiling. Each candidate must require, in order:

1. `material-evidence` and exact source citations.
2. a live-binding receipt that fixes the exact canonical campaign path and
   digest returned by the collection entrypoint.
3. candidate lineage whose packet, card, revision, evidence, and change IDs
   are present in the bound design-packet and retrieval artifacts, plus exact
   design-packet, retrieval, and candidate-evaluation artifact digests.
4. isolated automatic-weekly materialization with exact path and rollback digests.
5. `frozen-design-eval` with the baseline, protected holdout, and rotating canary.
6. the full Stack repository test suite.
7. a fresh independent review with verdict `ship`.
8. green pull-request CI and merge verification against the reviewed head.
9. atomic compilation/install from merged `origin/main`, both runtime discovery
   checks, and a rollback receipt.

Weak candidates are `no_action`; failed evaluation or review is
`rejected_no_queue`; unavailable operational prerequisites are
`retry_with_alert`. None creates a recurring human approval backlog. Direct
main commits, vendor/imported edits, route/command changes, upstream-pin
changes, source mutation, credentials, paid fallback, and destructive cleanup
remain prohibited.
