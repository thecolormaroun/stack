---
id: design-intelligence.promotion-rules
name: Design Intelligence Promotion Rules
description: Review and eval gates for turning digest findings into skill updates.
---

# Promotion Rules

The loop compounds taste only when a finding repeats, survives review, and improves eval outcomes.

## Default Safety

Do not directly mutate:
- Arc browser state.
- Field Theory bookmark corpus.
- X/Twitter account state.
- GBrain source roots.
- Vault notes.
- Studio/CDO skills.
- critique logs.

Source collection is read-only. Promotion is review-gated.

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
- a rollback path: leave the current skill untouched until PR/review approval.

## Eval Gate

Use the Codex design skill eval harness when available.

Promotion rule:
- candidate beats `codex-current` on at least 4 fixtures.
- no hard fails on mobile width, content overflow, missing primary workflow, fake critical data, or broken HTML.
- screenshot/rubric evidence is saved with the run.

If the candidate is useful but the eval is not run, label it `candidate - blocked on eval`, not `promoted`.

## Runtime Promotion

The skill may generate:
- a PR or review packet for Stack.
- an eval bundle candidate for Codex.
- a short summary for chat/Telegram.

It must not silently update the default runtime bundle, install skills globally, or enable a recurring automation without operator approval.

