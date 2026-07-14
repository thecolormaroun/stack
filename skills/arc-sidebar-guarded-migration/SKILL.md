---
name: arc-sidebar-guarded-migration
description: "Plan, audit, and verify guarded Arc sidebar JSON migrations. Use when Maroun asks to tidy Arc sidebar tabs, move loose captures into folders, inspect Arc sidebar backups or migration reports, or validate private browser-profile state without deleting data or weakening backup, clean-quit, mirror-integrity, and post-reopen checks."
---

# Arc Sidebar Guarded Migration

## Overview

Use this skill for Arc sidebar cleanup work where the data is private and the JSON state has multiple mirrors. The default is read-only audit; mutation requires explicit user intent plus clean quit, backup, atomic write, and post-reopen verification.

## Source Order

1. Read the current request and identify whether the task is audit-only or mutation-approved.
2. Read recent automation memory at `~/.codex/automations/weekly-arc-sidebar-auto-tidy/memory.md` if present. If `CODEX_HOME` is unset, use `~/.codex`.
3. For validation-only tasks, prefer existing backup reports under `~/Library/Application Support/Arc/codex-sidebar-backups/*/migration-report.json` over live profile files.
4. Inspect live Arc profile JSON only when the user explicitly asks for live cleanup or current-state audit, and do not print private tab titles or URLs beyond high-level categories unless needed and safe.

## Read-Only Audit

Use read-only audit when validating this skill, reviewing a prior run, or deciding what would be safe to move.

1. Count candidate loose tabs by space/folder category.
2. Classify each proposed move as `safe`, `ambiguous`, `active/current`, or `skip`.
3. Confirm target cleanup folders already exist before recommending moves.
4. Check prior reports for parent/child mirror consistency, final counts, retry count, and sync-health status.
5. Label evidence provenance for each check: independently verified from backup JSON, simulated from backup plus report, or reported by prior run memory. Do not overstate final post-write integrity when no persisted after-write JSON snapshot exists.
6. Return a plan or validation report without changing Arc files.

## Mutation Workflow

Only mutate when the user clearly asked for cleanup or movement:

1. Confirm Arc is closed, or cleanly quit Arc before reading/writing live state.
2. Create a timestamped backup under the Arc backup root before any write.
3. Validate the backup contains all relevant sidebar/live-data files.
4. Apply only parent/child moves into existing target folders; do not create broad new taxonomies during a cleanup pass.
5. Update every required mirror/wrapper with current sync metadata.
6. Write atomically.
7. Reopen Arc only when the workflow calls for post-write verification.
8. Verify after reopen that moved item parent ids match in both mirrors, target folders contain the moved ids, parent/child integrity is clean, `publishInProgress` is false, and retry count is acceptable.
9. If Arc exposes additional loose session tabs after launch, take at most one corrective pass unless Maroun explicitly asks for another.

## Boundaries

- Do not delete tabs, folders, backups, or browser profile files.
- Do not mutate Roon Reserve data or unrelated browser/application state.
- Do not move active/current operational quick refs, Top Apps, Work auth/admin refs, or ambiguous tabs.
- Do not expose private tab titles, URLs, account pages, finance, health, credential, household, or sensitive personal details in reports.
- Do not claim a clean run when sync health remains `loading`, `processingInitialSync`, or otherwise unsettled; report it as a warning or blocker.

## Closeout

Report backup path, number of moves, before/after counts by category, skips, verification checks, warnings, and whether any corrective pass was used. For validation-only runs, state that no Arc live profile files were changed.
