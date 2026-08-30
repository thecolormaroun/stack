---
name: design-intelligence
description: "Run the weekly design intelligence loop: scan curated sources, Arc bookmarks, Field Theory/X bookmarks, and GBrain deltas; synthesize a design digest; and automatically promote one evaluated Stack-owned skill/reference improvement when every publication gate passes."
---

# Design Intelligence Loop

Use this skill for the rebuilt weekly design digest and taste-compounding workflow.

The loop has two jobs:
- Find high-signal design inspiration from curated sources and Maroun's saved links.
- Convert repeated lessons into evaluated Studio/CDO skill updates and publish at most one automatically when every scoped gate passes.

## Operating Rule

Run source intake read-only. Do not mutate Arc, Field Theory, X/Twitter, GBrain source roots, Vault, or Studio skill files during source collection.

Promotion is a separate automatic tail under authorization contract
`weekly-design-auto-promotion-approved-v1`. It may touch only existing
Stack-owned skill/reference Markdown, at most one candidate and three files per
run. It still requires isolated materialization, frozen evaluation, full tests,
a fresh independent `ship` review, green pull-request checks, verified merge,
atomic runtime publication, discovery, and rollback evidence.

## Load Order

1. Read `references/source-adapters.md` for the source surfaces and safe access rules.
2. Read `references/output-contract.md` for digest and backfill deliverables.
3. Read `references/promotion-rules.md` before proposing any skill update.
4. Read `references/card-contract.md` before building or reviewing a design card.
5. Read `references/retrieval-contract.md` before querying task-context inspiration.
6. For the 2026 OpenClaw outage recovery candidate, read `references/backfill-candidate-guidance-2026-06-15.md`.
7. Read `eval/checklist.md` before claiming a run is complete.
8. Use `templates/weekly-digest.md` for the legacy report body, or the
   repository template `../../../templates/weekly-design-intelligence.md` for
   the U16 Output A/B/C body.

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
- A promotion packet with proposed Studio/CDO changes, evidence links, gate results, and a `no_action`, `rejected_no_queue`, `retry_with_alert`, or published disposition.

The digest may suggest Zettelkasten notes but must not write them. Skill and
reference changes advance only through the separate automatic promotion tail;
the digest itself never edits a runtime or checkout.

## U16 Card and Packet Boundary

When U15 source observations are available, use the checked-in
`registry/design-card.schema.json`,
`registry/design-intelligence-packet.schema.json`, and
`scripts/build-design-intelligence-packet.py` contract. The builder is an
owner-local packet writer: its `--out` and optional `--markdown-out` targets
must be outside the public Stack checkout. Keep the raw U15 companion rows in
the owner-local source boundary; never copy raw text, URLs, paths, or media
payloads into a public artifact.

When the input is a public-safe U15 snapshot, pass its approved owner-local
ledger with `--ledger`. The builder performs one read-only join on
`source_observations(evidence_id, raw_json)` and quarantines any observation
whose private companion is missing. It never copies the ledger path into the
packet.

The builder performs privacy and eligibility checks before analysis. Only
`accepted` or `revised` software/design observations can become cards. Personal
or non-software observations receive a private `no_candidate` disposition;
malformed, incomplete, deleted, missing, rejected, or instruction-injection
inputs are `quarantined` or `no_candidate` and cannot influence routing,
approval, tools, or publication. A screenshot can establish visible facts but
cannot establish unseen motion, interaction, accessibility, or responsive
behavior.

Cards retain opaque evidence citations, original/canonical identities,
capture/revision times, content/media/link digests, and derivation lineage.
Duplicate thread/article/Arc observations share one lineage graph while
retaining source evidence. Conflicting explicit claims remain distinct and are
surfaced as uncertainty. Prompt/model/config/sampling/code changes derive a
new revision and never overwrite an earlier card.

Provider egress inside the deterministic packet builder is default-deny. There
is no live provider client or paid fallback in that module. An injected fake
analyzer is allowed only with an explicit approved provider contract that names
the provider, exact allowed fields, redaction/minimization, retention,
training, and log-redaction posture. The fake receives only that allowlisted
opaque/digest context, and its output cannot set approval, routing, or
publication state. Retrieval updates and candidate changes remain pending or
quarantined; no card becomes skill/reference input or retrieval truth here.

Every packet reports explicit `empty`, `complete`, `partial`, or `failed`
input-digest state; deterministic unchanged input produces byte-stable output
and `no_action`. A weekly rendering keeps Output A, Output B, and Output C,
but rendering is a report only and never mutates Arc, Field Theory, GBrain,
Vault, skills, references, or promotion state.

## U17 Retrieval Boundary

Use `scripts/query-design-intelligence.py` and the checked-in request/response
schemas for design-time retrieval. The owner-local target manifest is the
authority; caller-supplied target identity alone is never sufficient. Retrieval
is fixed to GBrain source `x-bookmarks` and may call only read-only text and
image search. It returns three to seven cited results when enough authorized
evidence exists, or an explicit empty, failed, sparse, stale, or missing-modality
state.

Retrieval does not consume quarantined U16 cards as truth. It does not import,
reindex, change a provider, use a paid fallback, write a source, or modify a
skill/reference file. Read `references/retrieval-contract.md` for ranking,
privacy, degradation, and benchmark gates.

## Evaluation and Publication Gate

Before a proposed skill update becomes the default runtime behavior:
- Materialize it outside the active checkout and bind exact evidence, base
  commit, target files, and rollback digests.
- Require the exact live-binding receipt and prove that every packet, card,
  revision, evidence, and change ID exists in the campaign's persisted
  design-packet/retrieval artifacts before materialization.
- Run the frozen design-skill eval matrix against `codex-current`.
- Require at least four fixture wins, protected holdout and rotating-canary
  passes, full repository tests, and no hard failures.
- Require a fresh independent review with final verdict `ship`.
- Merge only through a green lineage-bound pull request whose reviewed head and
  candidate digests still match.
- Publish only from verified merged `origin/main` through the atomic compiler,
  installer, two-runtime discovery check, and rollback receipt.

If any gate is unavailable, retain resumable owner-local evidence and return
`retry_with_alert`; never guess a pass. A weak or rejected candidate creates no
human review queue.

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
