---
name: vault-migration-consumer-map
description: "Plan safe Obsidian vault splits or vault-root migrations by inventorying every reader, writer, automation, skill, config, launchd job, and hard-coded path before any move. Use when separating Zettelkasten/Knowledge from a personal Vault, changing ~/Vault paths, reducing Obsidian Sync load, or preparing pause-retarget-dry-run-resume migration plans."
---

# Vault Migration Consumer Map

Use this skill for planning-only or validation-only passes before moving Obsidian vault content. The core job is to prove that every live consumer has a migration path before any source files move.

## Default Posture

- Treat migration as planning-only unless Maroun explicitly approves execution.
- Do not move, rename, delete, sync-reset, or rewrite vault content during planning.
- Do not mutate LaunchAgents, Hermes/GBrain state, importer state, skills, source corpora, credentials, or Vault files.
- Exclude secrets, auth files, caches, logs, generated transcripts, and databases from broad quoted output.

## Consumer Inventory

Map live consumers before proposing mechanics:
- Zettelkasten scripts, queues, factories, eval harnesses, and tmp artifacts;
- Hermes/GBrain readers, writers, importers, overlays, morning pages, Mookie `/zk`, and policy allowlists;
- LaunchAgents and scheduled jobs that read or write the vault;
- Codex/Stack skills and automations that name Vault or Knowledge paths;
- Obsidian config, Sync behavior, attachments, plugins, and mobile usability constraints;
- local project docs that define source-of-truth boundaries.

Minimum read-only checklist:
- installed LaunchAgent plists and wrapper scripts, with redacted environment output;
- active Zettelkasten scripts/configs for factories, writers, importers, stats, queues, and gardeners;
- Hermes/Mookie ZK plugins and GBrain gateway/policy/source-root config;
- `~/.gbrain/source-roots` mirrors and root manifests;
- Obsidian `.obsidian` metadata and plugin lists;
- Stack skills/automations that encode root boundaries;
- state, queue, and ledger files that may store absolute paths.

Prefer `rg -l`, file lists, and metadata-first scans over broad content reads. Prefer active code/config/docs over historical memory dumps. If archives or importer reports create noise, narrow searches to live scripts, configs, and docs.

## Plan Shape

Produce a durable plan with:
- objective and non-goals;
- current vault roots and proposed target roots;
- consumer map with owner/path, read/write mode, current path assumption, migration action, validation gate, and rollback;
- pause window for writers and scheduled jobs;
- copy-first or bridge strategy, with why it is safer than direct move;
- dry-run commands and expected counts;
- cutover order;
- rollback and resume checkpoints;
- post-cutover monitoring.

## Verification Gates

A credible plan names concrete gates:
- path-reference scan over active files after retargeting;
- dry-run import/factory/MOC/health commands where available;
- Obsidian opens both vaults locally;
- mobile sync load target is achieved without deleting remote data blindly;
- launchd jobs are paused, retargeted, dry-run, then resumed;
- no writer points at the old content path after cutover.

If a consumer cannot be verified without mutating private state, mark it as a manual checkpoint rather than assuming it is safe.

## Closeout

Report:

```text
Recommended migration shape:
Consumers found:
Hard stops:
Dry-run gates:
Rollback plan:
What remains unknown:
Decision needed:
```
