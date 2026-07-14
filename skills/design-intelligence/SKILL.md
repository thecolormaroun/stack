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
4. For the 2026 OpenClaw outage recovery candidate, read `references/backfill-candidate-guidance-2026-06-15.md`.
5. Read `eval/checklist.md` before claiming a run is complete.
6. Use `templates/weekly-digest.md` for the report body.

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

## Candidate Guidance From Historical Backfill

Status: candidate from the 2026-04-01..2026-06-15 OpenClaw outage backfill. Use this guidance for `design-intelligence-v1` eval runs; do not treat it as default runtime taste until the eval gate passes and the Stack change is reviewed.

- Ground taste in concrete references before inventing. Use saved references, pattern libraries, side-by-side comparisons, and explicit visual vocabulary as design infrastructure; do not let the model free-associate a generic style when evidence exists.
- Treat component registries as raw ingredients, not an aesthetic. When using shadcn/ui or a registry source, borrow coverage of states, layout primitives, and component anatomy, then deliberately customize density, tokens, radii, shadows, and interaction states so the result does not read like a default registry demo.
- Use named, state-driven motion instead of generic decoration. Pick the smallest transition that clarifies a real state change, document its trigger, timing, interruption behavior, and reduced-motion fallback, and avoid `transition-all`, perpetual ambient movement, or motion that hides missing hierarchy.
- For AI-assisted design or builder workflows, expose the design tree. The UI should show the brief/prompt, generated directions, comparison criteria, selected branch, iteration history, and eval/QA state as first-class product surfaces rather than collapsing the experience into a chat box.
- Generate design candidates in multiples when exploring taste, compare them side by side against the rubric, then refine the selected branch. Do not promote a single attractive artifact without critique/eval evidence.
- For operational and data-heavy tools, favor dense comparative workspaces: tables, filters, timelines, side panels, validation states, batch controls, and specific deltas. Do not let portfolio, launch-page, or configurator inspiration override the user's primary workflow.
- Dense mobile tables must recompose, not widen the page. At narrow viewports, switch to priority columns, stacked row cards, or an internal scroll region whose parent still keeps `documentElement.scrollWidth <= innerWidth`; do not rely on a large table `min-width` that creates page-level horizontal overflow.
- Before/after redesign artifacts should open on the improved experience. If a legacy "before" view is included for comparison, constrain it inside the viewport and never let the old layout define the page width or primary mobile experience.
- Mobile hard gates apply to the whole shell, not just content tables. Top-level app wrappers, sidebars, sticky headers, nav rows, filters, panels, charts, and dialogs need `min-width:0`, `max-width:100%`, and wrapping/contained overflow so no child can expand the document past the viewport.
