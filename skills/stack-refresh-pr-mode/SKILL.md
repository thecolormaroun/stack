---
name: stack-refresh-pr-mode
description: "Run Maroun's review-safe Claude/Codex skill stack refresh from ~/Codex. Use when asked to update, refresh, verify, or diagnose the local skill stack, the update-last30days-skill automation, gstack/compound-engineering pins, Impeccable, last30days, illo, transitions-dev-motion, or Stack repo PR-mode behavior without pushing directly to main."
---

# Stack Refresh PR Mode

Use this skill for the recurring skill-stack update loop. The goal is a verified local refresh with explicit warnings, not a hidden production promotion.

## Source Order

1. Read `~/Codex/README.md`.
2. Read `~/Codex/upstreams.lock.json`.
3. Read `~/.codex/automations/update-last30days-skill/memory.md` if it exists.
4. Check `~/Projects/stack` branch and status before running anything that might sync or push.

Do not inspect, print, or modify `~/.config/last30days/.env` or `~/.config/illo/config.yaml`. It is OK to report whether protected config files exist when the run asks for that.

## Refresh Command

Run from `~/Codex`:

```bash
SYNC_STACK_REPO_TO_GITHUB=pr ~/.codex/scripts/update-last30days-skill.sh
```

Use the exact command unless the user explicitly changes it. Do not replace it with manual installs, ad hoc copies, or direct runtime edits.

## Validation-Only Mode

When validating this skill or auditing readiness, do not run the refresh command. Use the same source order, collect Stack branch/status, record the current upstream pins, and produce a checklist/report that says the refresh was not executed.

## Required Verification

Verify every requested installed skill path. The usual set is:

```text
~/.codex/skills/last30days/SKILL.md
~/.codex/skills/gstack/SKILL.md
~/.codex/skills/ce-setup/SKILL.md
~/.codex/skills/teach-impeccable/SKILL.md
~/.codex/skills/impeccable/SKILL.md
~/.codex/skills/transitions-dev-motion/SKILL.md
~/.codex/skills/illo/SKILL.md
```

Also report:
- the resolved gstack ref and Compound Engineering version from `upstreams.lock.json`;
- Stack repo branch and dirty/untracked status;
- the pre-run branch name, whether PR mode pushed, opened a PR, or left local changes unpushed, and the exact gate: do not push directly to main;
- warnings such as missing `gbrain`, missing plan-tune hooks, runtime restart requirements, or branch-not-main.

## Hard Stops

Stop and ask before:
- pushing directly to `main`;
- deleting or resetting Stack changes;
- changing protected config or secrets;
- widening the task into external account, browser profile, credential, or production-state changes.

If `~/Projects/stack` is not on `main`, keep PR-mode behavior and report the branch gate instead of forcing a checkout.

## Closeout

Start with the status: completed, blocked, or completed-with-warnings. Then name the command, exit status, verified paths, what changed, what remained unpushed or review-gated, and the next useful gate.
