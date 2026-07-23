---
name: stack-gemini-review
description: |
  Run a read-only Gemini / Antigravity second-model review lane for git-backed Stack
  skill changes, PR diffs, runtime-sync diffs, and upstream parity diffs. Use when
  Maroun asks for Gemini review, Antigravity review, Google AI review, or
  model-diverse second review.
---

# stack-gemini-review

Use this as an advisory second-review lane. Codex remains the executor and decides whether findings are valid.

## Boundary

This lane is read-only by default.

Do not:

- edit, patch, stage, commit, push, merge, or open PRs from this lane;
- mutate `vendor/`, `current/`, `upstreams.lock.json`, or upstream checkouts;
- print credentials, raw secret values, private finance/health/email bodies, or full repos;
- run from sensitive local roots such as Vault, browser profiles, credential folders, finance data, or health data;
- treat Gemini/Antigravity findings as authoritative without Codex/user review.

## Source Of Truth

- Resolve the Stack checkout with
  `STACK_REPO_DIR="${STACK_REPO:-$(git rev-parse --show-toplevel)}"`.
- Stack skill: `${STACK_REPO_DIR}/skills/engineering/gemini-review/SKILL.md`
- Runtime capability: `gemini-review`, when it is installed and available.

## Recommended Flow

1. Load the repository-local `gemini-review` capability when available.
2. Ask it for a dry-run against the explicit target repository and base ref.
3. Run the real advisory review only after the dry-run is clean.
4. Validate all findings through Codex or user review before acting.

The Stack repository does not ship an Antigravity executable, credentials, or
a Gemini service adapter. If the runtime capability or its configured provider
is unavailable, stop with a clear blocked result. Do not search another
workspace, invent a wrapper path, or claim a second-model review occurred.

Useful targets:

- Stack skill changes: target `"${STACK_REPO_DIR}"` at base `HEAD`
- This workflow layer: target the active Git-backed Stack checkout
- PR-style diffs: `--base main` or the appropriate merge base
- Runtime changes: review the diff containing Stack's compiler, installer, or
  bootstrap files
- Upstream parity checks: review Stack adapter and package metadata diffs, not
  package-cache mutations

## Verification

A safe dry-run identifies the target repository, base ref, provider readiness,
and planned review without mutating the target.

A real review is usable only when it produces an advisory report and target
repository status remains unchanged except for pre-existing user edits.

Close with the report path, dry-run or smoke commands run, top findings, false positives, and the next action.
