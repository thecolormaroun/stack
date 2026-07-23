---
name: fieldbook-source-split
description: "Plan, execute, or validate a safe split between Maroun's mobile-friendly Fieldbook vault, the larger Library/Vault, and GBrain source mirrors. Use when working on Obsidian vault migration, Fieldbook/Library separation, GBrain source registration, phone sync readiness, mirror refresh scripts, or cleanup gates after a vault split."
---

# Fieldbook Source Split

Use this skill when the goal is to keep a small, phone-friendly Obsidian vault useful without breaking the larger knowledge Library or GBrain ingestion.

## Source Order

1. Inspect the current user request and any handoff artifact.
2. Read local repo/workspace guidance before touching files:
   - `~/Projects/Zettelkasten/AGENTS.md`, when present.
   - Relevant Hermes/GBrain docs or scripts only after locating them with `rg`.
3. Inspect the real surfaces:
   - `~/Fieldbook`
   - `~/Vault`
   - `~/.gbrain/source-roots/fieldbook`
   - any mirror refresh script or GBrain source config found by `rg "fieldbook|source-roots|gbrain source"`.
4. Use prior memory only as support; verify live state before claiming current import, sync, or embedding status.

## Workflow

1. Map consumers before moving content: Obsidian desktop, phone Sync, Hermes/Mookie routing, Zouzou file access, GBrain sources, jobs, and automated writers.
2. Keep the old Library/Vault intact until phone and source-ingestion proof pass.
3. Keep Fieldbook free of heavy Library-only roots, plugin state, old Sync state, `.git`, credentials, and generated caches.
4. For GBrain, prefer a GBrain-owned mirror under `~/.gbrain/source-roots/fieldbook` instead of initializing git inside the mobile vault.
5. Verify import/search separately from semantic embedding. If the embedding provider requires credentials or quota, stop at that provider gate and report it.
6. Treat Obsidian Sync and phone setup as manual/user-gated. Walk Maroun through desktop-first setup, then phone setup, then a round-trip smoke note.

## Hard Stops

- Do not delete or clean the old Library/Vault without explicit approval.
- Do not add `.git` inside `~/Fieldbook` unless Maroun explicitly chooses that tradeoff.
- Do not mutate Vault, credentials, browser profiles, external accounts, or GBrain production jobs during validation-only work.
- Do not claim phone Sync, remote vault creation, or embedding completion without direct proof.

## Verification

Use the narrowest live checks that match the request:

```bash
find ~/Fieldbook -maxdepth 2 -name .git -o -name .obsidian
find ~/Fieldbook -maxdepth 2 \( -path '*10 Knowledge*' -o -path '*Utilities/Highlights*' \)
test -d ~/.gbrain/source-roots/fieldbook
gbrain search --source fieldbook "test" --limit 3
```

For read-only validation, do not refresh mirrors or run imports. Instead, inspect scripts/configs and report which mutation-capable checks were skipped.

## Closeout

Report:

- what changed or was inspected;
- consumer routing status;
- rollback status for the old Library/Vault;
- Fieldbook negative checks;
- GBrain mirror/import/search status;
- Sync/phone setup state;
- embedding or provider blockers;
- the next manual gate for Maroun.
