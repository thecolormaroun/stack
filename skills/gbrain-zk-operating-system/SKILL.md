---
name: gbrain-zk-operating-system
description: "Operate and validate the GBrain-first Zettelkasten knowledge layer. Use for GBrain ZK gateway work, source-aware qrels, Library/Fieldbook retrieval routing, zk-lab/zk-answers/zk-questions/zk-proposals preflights, answer/gap packets, and deciding whether derived GBrain sources should stay shadow-only or be approved for registration."
---

# GBrain ZK Operating System

Use this skill when the work is about making GBrain the agent-native read and evaluation layer for Zettelkasten, Library, and Fieldbook while keeping Obsidian files canonical.

## Source Order

1. Read the current plan: `~/Projects/Zettelkasten/docs/plans/2026-07-02-001-feat-gbrain-native-zettelkasten-operating-system-plan.md`.
2. Read current Hermes artifacts:
   - `~/hermes/knowledge/gbrain-zk-operating-dashboard.md`
   - `~/hermes/knowledge/gbrain-zk-source-registration-preflight.md`
   - `~/hermes/knowledge/gbrain-zk-operating-source-comparison.md`
3. Inspect touched gateway, plugin, qrel, and test files before changing behavior.
4. Verify live GBrain state with explicit `~/.bun/bin/gbrain` paths when needed; do not assume ambient `PATH` contains `gbrain`.
5. Use raw Vault/Fieldbook file reads only for exact disk-state verification, newest unsynced notes, or approved edits.

## Operating Levels

- Level 0: current `vault` and `fieldbook` mirror.
- Level 1: GBrain-first reads with source-aware citations.
- Level 2: derived lab/answer/question/proposal sources as shadow augmentation.
- Level 3: preferred agent substrate for selected query classes after eval pass.
- Level 4: supervised canonical-write proposal packets.
- Level 5: GBrain-native canonical store, explicitly out of scope without later approval.

Default to Level 1 unless a preflight and explicit approval allow Level 2 source registration or embedding.

## Invariants

- `~/Vault` remains canonical Library storage.
- `~/Fieldbook` remains canonical Fieldbook storage.
- `vault` and `fieldbook` source IDs must stay distinct in qrels, citations, and eval scoring.
- `zk-lab`, `zk-answers`, `zk-questions`, and `zk-proposals` are generated GBrain-owned surfaces until approved.
- `zk-questions` is eval fuel, not answer authority.
- `zk-proposals` is review material, not canonical truth.
- Canonical Library writeback remains disabled unless a separate approved writer workflow says otherwise.

## Validation Ladder

For implementation work, require:

- unit tests for gateway/source-routing behavior;
- source-aware qrel checks proving wrong-source hits do not satisfy a qrel;
- smoke output that labels citations without printing raw sensitive note text;
- no-mutation proof for `~/Vault` and `~/Fieldbook`;
- dashboard or preflight artifact update showing source freshness, stale chunks, qrel quality, answer packets, question packets, and proposal queue counts.

For read-only review, inspect existing artifacts and report the current level, warnings, and next gate.

## Hard Stops

- Do not register `zk-lab`, `zk-answers`, `zk-questions`, or `zk-proposals` without explicit approval.
- Do not embed new generated sources, change GBrain provider settings, add LaunchAgents, alter Readwise/Obsidian settings, or add generated sources to scheduled allowlists.
- Do not write to Vault, Fieldbook, source corpora, credentials, browser profiles, email/calendar, or production systems.
- Do not make a derived source the default retrieval authority without eval pass and explicit promotion.
- Do not print private note bodies, finance/health details, raw retrieved passages, or secrets in smoke output.

## Useful Commands

Read-only checks should prefer existing project commands and explicit paths, for example:

```bash
python3 -m unittest ~/hermes/tests/test_gbrain_knowledge_gateway.py
~/.bun/bin/gbrain sources list --json
python3 -m json.tool ~/hermes/knowledge/gbrain-zk-source-aware-qrels.json >/dev/null
```

Only run source registration or sync commands from the preflight after explicit approval.

## Closeout

Report:

```text
Current operating level:
Sources inspected:
Gateway/qrel/tests checked:
Dashboard/preflight artifacts:
Writes made:
Hard stops preserved:
Next gate:
Promotion recommendation:
```
