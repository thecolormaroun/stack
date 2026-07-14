---
name: zettelkasten-plan-review-gate
description: "Stress-test Zettelkasten, Obsidian, Vault/Fieldbook, GBrain, and source-migration plans before execution. Use when Maroun asks for plan review, Gemini/GStack/Compound Engineering review, migration safety, reverse-split planning, cutover readiness, or whether a ZK/GBrain plan is implementation-ready."
---

# Zettelkasten Plan Review Gate

Use this skill when a Zettelkasten or GBrain plan could move, split, register, sync, index, or change the authority of knowledge sources. The output should make the plan safer and more executable without performing the migration.

## Source Order

1. Read the target plan under `docs/plans/`.
2. Read the repo `AGENTS.md` and any local plan status or impact report the plan names.
3. Inspect scripts, configs, tests, and docs only as needed to verify plan assumptions.
4. If reviewing GBrain behavior, prefer existing preflight/status artifacts under `~/hermes/knowledge/` and `~/hermes/tmp/` before touching live commands.
5. Use external model or multi-lens reviews only as advisory evidence; the local plan and artifacts remain source of truth.

## Review Lenses

Run the review as concrete findings, ordered by risk:

- migration safety: copy/move integrity, rollback, idempotency, dry-run proof, destructive boundaries;
- source authority: Library vs Fieldbook vs GBrain vs derived lab sources;
- sync and path risk: Obsidian Sync, Readwise, templates, attachments, daily notes, notification ledgers, LaunchAgents, hard-coded roots;
- privacy/security: health, finance, personal notes, token/plugin caches, logs, raw note-body exposure;
- operator readiness: exact commands, approval gates, stop conditions, verification contracts, artifact paths;
- product strategy: whether the plan solves the actual user problem without overbuilding or hiding a cutover;
- falsification: what evidence would prove the plan's preferred architecture wrong.

## Optional Review Fanout

When Maroun asks to "run it through everything," use available review surfaces in read-only mode. Good prompts name the plan path, lens, hard stops, and expected findings format. Keep generated reviews advisory and then synthesize them into plan edits or blockers.

Do not expose private note text to remote model surfaces. Use redacted plan content, diffs, or local summaries when the plan contains sensitive details.

## Hard Stops

- Do not move, rename, delete, sync, import, embed, register GBrain sources, change LaunchAgents, or mutate Vault/Fieldbook during a review.
- Do not treat a plan as implementation-ready if approval gates, rollback, source authority, or no-mutation proof are missing.
- Do not bury a destructive or external-account action inside "cleanup."
- Do not quote sensitive note, finance, health, or credential material in the report.

## Validation Standard

A plan can be called implementation-ready only when it has:

- explicit source-of-truth roots and source IDs;
- phase-by-phase commands with dry-run and apply separation;
- approval gates before source registration, embedding, remote sync cleanup, or canonical write changes;
- rollback/rescue paths and no-source-corpus-mutation proof;
- tests or smoke checks for each changed script/plugin/gateway;
- a clear `DONE` definition and a `DO_NOT_PROMOTE` / blocked state when gates remain open.

## Closeout

Use this shape:

```text
Verdict:
Blockers:
Plan edits or recommended edits:
Evidence inspected:
Commands/checks run:
What was not changed:
Next safe gate:
```
