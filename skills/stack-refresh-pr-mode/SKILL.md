---
name: stack-refresh-pr-mode
description: "Run Maroun's review-safe Claude/Codex skill stack refresh from ~/Codex. Use when asked to update, refresh, verify, or diagnose the local skill stack, the update-last30days-skill automation, gstack/compound-engineering pins, Emil design skills, Impeccable, last30days, illo, transitions-dev-motion, or Stack repo PR-mode behavior without pushing directly to main."
---

# Stack Refresh PR Mode

Use this skill for the recurring skill-stack update loop. The goal is a verified local refresh with explicit warnings, not a hidden production promotion.

## Source Order

1. Read `~/Codex/README.md`.
2. Read `~/Codex/upstreams.lock.json`.
3. Read `~/Projects/stack/skills/emil-design-eng/references/source.json` and `~/Projects/stack/skills/review-animations/references/source.json` when Emil/design skills are in scope.
4. Read `~/.codex/automations/update-last30days-skill/memory.md` if it exists. If `CODEX_HOME` is unset, use `~/.codex`.
5. Check `~/Projects/stack` branch and status before running anything that might sync or push.

Treat `~/Codex` as the workflow/runtime layer, not the authoritative git state. The Stack repo dirty-state and branch gate live in `~/Projects/stack`.

Do not inspect, print, or modify `~/.config/last30days/.env` or `~/.config/illo/config.yaml`. It is OK to report whether protected config files exist when the run asks for that.

## Refresh Command

Run from `~/Codex`:

```bash
SYNC_STACK_REPO_TO_GITHUB=pr ~/.codex/scripts/update-last30days-skill.sh
```

Use the exact command unless the user explicitly changes it. Do not replace it with manual installs, ad hoc copies, or direct runtime edits.

If the refresh stalls while downloading or cloning upstream skills, treat repeated GitHub HTTPS hangs, `fetch-pack` disconnects, or long `resp.read()` waits as a network/upstream transfer blocker. First preserve or restore any required local skill folder from the latest local backup when the installer left it missing, then verify the required installed paths. Do not keep retrying indefinitely and do not replace the managed installer with manual runtime edits.

## Validation-Only Mode

When validating this skill or auditing readiness, do not run the refresh command. Use the same source order, collect Stack branch/status, record the current upstream pins, and produce a checklist/report that says the refresh was not executed.

When auditing a dated range, sort automation-memory entries by timestamp before reporting; the memory file may not be strictly chronological.

## Required Verification

Verify every requested installed skill path. The usual set is:

```text
~/.codex/skills/last30days/SKILL.md
~/.codex/skills/gstack/SKILL.md
~/.codex/skills/ce-setup/SKILL.md
~/.codex/skills/teach-impeccable/SKILL.md
~/.codex/skills/impeccable/SKILL.md
~/.codex/skills/transitions-dev-motion/SKILL.md
~/.codex/skills/emil-design-eng/SKILL.md
~/.codex/skills/review-animations/SKILL.md
~/.codex/skills/review-animations/references/STANDARDS.md
~/.codex/skills/illo/SKILL.md
```

Also report:
- the resolved gstack ref, Compound Engineering version, and Emil design-skill upstream commit from `upstreams.lock.json` plus Stack `source.json`;
- Stack repo branch and dirty/untracked status;
- the pre-run branch name, whether PR mode pushed, opened a PR, or left local changes unpushed, and the exact gate: do not push directly to main;
- warnings such as missing `gbrain`, missing plan-tune hooks, runtime restart requirements, or branch-not-main.
- optional upstream warning lanes separately from failures. Missing Compound Engineering aliases, skipped Claude gstack install due to non-generated local edits, `.factory` generated-token ceilings, GitHub transfer/network stalls, plugin restart-required notices, and absent non-interactive plan-tune hooks are warnings unless the requested refresh target depends on them.
- whether local Stack changes are pre-existing, newly produced by the refresh, or unrelated to the refresh. Do not clean them up during the run.

## Failure And Warning Triage

Classify refresh outcomes precisely:

- `completed`: refresh command exited 0 and required installed paths verify.
- `completed-with-warnings`: required paths verify, but warnings remain, such as skipped Claude gstack local override, non-interactive plan-tune hooks, missing optional Compound aliases, generated token ceilings, GitHub transfer stalls, or Codex restart required for an updated plugin.
- `blocked-restored`: the command failed or was interrupted, but a required skill was restored from a known backup and required paths verify.
- `blocked`: a required installed path is missing, protected config would need mutation, Stack is on an unsafe branch for the requested action, or the refresh cannot be made trustworthy locally.

If GitHub downloads, zip reads, or git fetches stall, treat it as a network/transfer blocker before blaming the script. Restore any required missing skill from `~/.codex/skills/.backups/daily-build-skills-latest/` only when a backup already exists and the missing path is part of the required verification set. Report the restore path and still mark the run as warning or blocked according to final verification.

If the refresh updates a plugin such as `illo` and reports restart required, do not restart Codex from the automation. Record the restart-required gate in closeout.

If a generated skill exceeds a token ceiling, report the exact generated file path and keep it as a warning unless it prevents one of the required installed paths from existing.

## Hard Stops

Stop and ask before:
- pushing directly to `main`;
- deleting or resetting Stack changes;
- changing protected config or secrets;
- widening the task into external account, browser profile, credential, or production-state changes.

If `~/Projects/stack` is not on `main`, keep PR-mode behavior and report the branch gate instead of forcing a checkout.

## Closeout

Start with the status: completed, completed-with-warnings, blocked-restored, or blocked. Then name the command, exit status, verified paths, what changed, what remained unpushed or review-gated, and the next useful gate.
