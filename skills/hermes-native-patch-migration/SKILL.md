---
name: hermes-native-patch-migration
description: "Plan, execute, or audit update-safe Hermes/Mookie patch migrations. Use when local Hermes core commits, gateway patches, Mookie plugins, hooks, printed CLI tools, Morning Pages, Link Inbox, daily maintenance update blockers, or gateway restart proof need to move into native Hermes extension surfaces without preserving a private core patch stack."
---

# Hermes Native Patch Migration

## Overview

Use this skill to move Maroun-specific Hermes/Mookie behavior out of private core patches and into native local surfaces: plugins, hooks, tests, config, docs, and daily-maintenance posture. The success condition is not "patch applied"; it is an update-safe Hermes checkout with the live gateway proving the behavior still works.

## Source Order

1. Read `~/hermes/MOOKIE.md`, `~/hermes/KNOWLEDGE.md`, and `~/hermes/PILOT.md` when present.
2. Read the current plan or blocker artifact, usually under `~/hermes/docs/plans/` or `~/hermes/tmp/mookie-daily-maintenance/latest.md`.
3. Inspect the exact local surfaces in scope:
   - `~/hermes/plugins/`
   - `~/hermes/hooks/`
   - `~/hermes/tests/`
   - `~/hermes/config.yaml`
   - `~/hermes/hermes-agent/` only when a generic upstreamable core hook or test is required.
4. Check live/runtime evidence only as needed: `hermes gateway status`, the relevant LaunchAgent label, and smoke artifacts under `~/hermes/tmp/`.
5. Treat memory and old reports as hints. Verify current branch, files, tests, and gateway state before declaring the blocker gone.

## Migration Workflow

1. Name the private patch or blocker in plain English: what behavior it preserves, which files carry it, and why updates are blocked.
2. Classify each delta:
   - Mookie-local behavior belongs in `~/hermes/plugins/`, `~/hermes/hooks/`, root-level tests, or local config.
   - Generic Hermes lifecycle behavior may live in `hermes-agent/` only with focused generic tests and an upstreamable explanation.
   - Obsolete or already-upstreamed behavior should be dropped, not replayed.
3. Preserve user-facing behavior with tests before removing the old path. For Mookie flows, root-level tests are preferred over Mookie-specific tests under `hermes-agent/tests/`.
4. Remove invalid or private core coupling only after the native replacement is proven.
5. Update daily-maintenance or status reporting so it reflects the new truth: clean upstream posture, explicit local plugin surfaces, and exact remaining gates.
6. Restart or reload the gateway only when code/config changes need live proof, then verify the LaunchAgent PID and smoke output.

## Verification Ladder

Use the smallest ladder that proves the change:

- Static proof: branch/ahead-behind, file placement, plugin/hook registration, no invalid hook names, no private core tool registration.
- Unit proof: focused tests for the native plugin, hook, or generic lifecycle contract.
- Runtime proof: `hermes config check`, `hermes gateway status`, plugin list, and a quick Mookie/Zouzou or feature-specific smoke.
- Update proof: daily maintenance latest report no longer names the old private patch stack as the blocker.

For read-only audits, do not restart the gateway or mutate the checkout. Produce a migration-readiness report with the commands intentionally skipped.

## Read-Only Audit Checklist

Use targeted checks instead of broad log dumps:

```bash
git -C ~/hermes/hermes-agent status --short --branch
git -C ~/hermes/hermes-agent rev-list --left-right --count HEAD...origin/main
rg "pre_agent_dispatch|printed_cli" ~/hermes/hermes-agent ~/hermes/plugins ~/hermes/hooks ~/hermes/tests ~/hermes/config.yaml
rg "pre_gateway_dispatch|pre_llm_call|command:|printed_cli" ~/hermes/plugins ~/hermes/hooks ~/hermes/tests
```

Prefer `~/hermes/tmp/mookie-daily-maintenance/latest.md` and targeted `jq` over dumping full maintenance JSON. If a command could expose secrets or runtime-sensitive output, summarize only the safe status fields.

## Hard Stops

- Do not write to Vault, source corpora, credentials, browser profiles, external accounts, or production systems.
- Do not force-push, reset, delete user work, or rewrite unrelated dirty files.
- Do not keep Mookie-specific behavior in Hermes core unless Maroun explicitly accepts a temporary local patch and a concrete upstream/removal gate.
- Do not expose token values, Telegram secrets, Google tokens, account identifiers, or sensitive personal material from logs.
- Ask before adding LaunchAgents, cron, new automations, paid services, or new credential grants.

## Closeout

Report:
- what moved or should move;
- exact files inspected or changed;
- tests, commands, and runtime checks used;
- whether the Hermes update blocker is cleared, partially cleared, or still blocked;
- any gateway restart or manual approval still needed;
- the next smallest review or upstreaming gate.
