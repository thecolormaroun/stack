---
name: design-intelligence
description: "Run the weekly design intelligence loop: scan curated sources, Arc bookmarks, Field Theory/X bookmarks, and GBrain deltas; synthesize a design digest; propose review-gated skill updates; and require eval evidence before promotion."
---

# Design Intelligence Loop

Use this skill for the rebuilt weekly design digest and taste-compounding workflow.

The loop has two jobs:
- Find high-signal design inspiration from curated sources and Maroun's saved links.
- Convert repeated lessons into reviewable Studio/CDO skill updates only after evidence and eval.

## Operating Rule

Run as a read-only intake by default. Do not mutate Arc, Field Theory, X/Twitter, GBrain source roots, Vault, or Studio skill files during source collection.

Promotion is a separate review step.

## Load Order

1. Read `references/source-adapters.md` for the source surfaces and safe access rules.
2. Read `references/output-contract.md` for digest and backfill deliverables.
3. Read `references/promotion-rules.md` before proposing any skill update.
4. Read `eval/checklist.md` before claiming a run is complete.
5. Use `templates/weekly-digest.md` for the report body.

## Weekly Run

Default cadence: Saturday morning, after bookmark sync and before any taste-compounding promotion.

Use a seven-day window unless the operator passes an explicit range.

Required source lanes:
- Curated sources: Brian Lovin `/sites` or writing, Design Spells, Handheld Design, Featured Mobile.
- Arc bookmarks/sidebar: current sidebar plus Arc history as a date supplement.
- Field Theory/X bookmarks: live Field Theory SQLite/JSONL/Markdown export.
- GBrain: imported `x-bookmarks` and saved-link roots, especially deltas where Field Theory is ahead.

## Historical Backfill

For the OpenClaw outage recovery, run a catch-up window before resuming normal weekly cadence.

Default catch-up window: `2026-04-01` through the current run date.

Chunk the backfill by week. Each chunk should produce its own source manifest and digest so weak or unreachable sources are visible instead of hidden inside one giant report.

## Outputs

Every run must produce:
- A source manifest with counts, paths used, fetch/read status, and candidate samples.
- A weekly design digest with Output A, Output B, and Output C.
- A promotion packet with proposed Studio/CDO changes, evidence links, and the eval gate required before promotion.

The digest may suggest Zettelkasten notes and skill changes, but it must not directly write them.

## Evaluation Gate

Before a proposed skill update becomes the default runtime behavior:
- Install or refresh the candidate skill into Codex.
- Run the design-skill eval matrix against `codex-current`.
- Promote only when the candidate beats `codex-current` on at least 4 fixtures and has no hard fails.

If the eval harness is unavailable, mark the promotion packet as blocked rather than approving it from taste alone.

