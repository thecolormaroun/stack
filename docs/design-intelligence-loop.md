# Design Intelligence Loop

## Recommendation

Rebuild the old OpenClaw weekly design digest as an operator-owned automation
that uses Stack as the durable skill source.

Ownership split:
- Stack owns the design-intelligence skill, graph references, templates, and promotion rules.
- The local operator owns optional runner scripts, eval bundles, and eventual recurring automation.
- Hermes and GBrain remain source/memory substrates: bookmark snapshots, imports, and backfill staging.
- OpenClaw is historical evidence only; do not depend on its stale cron state for the rebuild.

## Weekly Inputs

Every weekly run must read:
- Arc sidebar/bookmark state from `~/Library/Application Support/Arc/StorableSidebar.json`.
- Arc History as a recency supplement only.
- Field Theory/X bookmarks from `~/.ft-bookmarks/bookmarks.db`, JSONL, Markdown exports, and media metadata.
- GBrain imported bookmark roots, especially deltas where Field Theory is ahead.
- Curated web sources: Brian Lovin, Design Spells, Handheld Design, Featured Mobile.

Intake is read-only. The run may write a source manifest, digest, and promotion packet, but it must not mutate Arc, Field Theory, X, GBrain roots, Vault, or Studio skills during collection.

## Weekly Flow

1. Build a source manifest with read status, candidate counts, and extraction failures.
2. Synthesize the weekly digest using the preserved Output A/B/C structure.
3. Produce a promotion packet for Zettelkasten and Studio/CDO skill candidates.
4. Run the Codex design eval gate for any candidate skill update.
5. Promote only through a reviewable Stack change after eval evidence exists.

## Historical Backfill

Initial backfill window: `2026-04-01` through the current run date.

Chunk by week. Each chunk should produce:
- `source-manifest.json`
- `weekly-design-digest-YYYY-MM-DD.md`
- `promotion-packet.md`

Use Hermes tmp or another review staging area for generated packets until promotion is approved.

## Commands

Stack's shipped bookmark collector is the portable intake surface. A dry-run
does not advance cursors:

```bash
python3 scripts/collect-bookmark-candidates.py \
  --ledger /tmp/stack-design-intelligence-smoke.sqlite
```

For a reviewed owner-local collection/curation run:

```bash
scripts/run-stack-bookmark-curation.sh collection --manual --apply
scripts/run-stack-bookmark-curation.sh curation --manual --apply
```

An optional external eval harness must be supplied explicitly:

```bash
cd "$STACK_DESIGN_EVAL_ROOT"
DRY_RUN=1 FINAL_HTML_ONLY=1 IGNORE_USER_CONFIG=1 \
  scripts/evaluate-design-skills.sh run-one design-intelligence-v1 001-operational-dashboard
```

Promotion gate:

```bash
cd "$STACK_DESIGN_EVAL_ROOT"
EVAL_BUNDLES="codex-current design-intelligence-v1" \
EVAL_PROMPTS="001-operational-dashboard 002-productivity-app 003-landing-page-with-assets 004-existing-page-redesign 005-data-workflow" \
FINAL_HTML_ONLY=1 IGNORE_USER_CONFIG=1 RUN_ID=design-intelligence-gate \
  scripts/evaluate-design-skills.sh run-matrix
```

## Automation Gate

Do not enable the recurring weekly automation until the operator approves the live job.

Recommended live cadence:
- Saturday morning: source manifest and digest.
- Sunday evening: taste-compounding promotion packet after digest review.

## Latest Candidate Eval

Latest historical verified gate: `2026-06-17`.

Baseline run:
`design-intelligence-gate-20260615T223548Z`

Candidate run:
`design-intelligence-gate-final2-20260615T232621Z`

Result: `design-intelligence-v1` beat `codex-current` on 5 of 5 fixtures with no candidate hard fails.

Evidence saved with the candidate run:
- `report.md`
- `viewport-hard-gate.tsv`
- `screenshots-final/contact-sheet-mobile.jpg`
- `screenshots-final/contact-sheet-desktop.jpg`
