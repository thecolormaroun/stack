---
title: micro-branch skill - Plan
type: feat
date: 2026-11-06
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
---

# micro-branch skill - Plan

> **Update, 2026-11-10: Twombly dropped.** Twombly is a paid third-party product,
> so Maroun took it out of Stack. The local board is now the only canvas. The
> Design Studio preset, per-origin frames, `--view` and `--localize` stay. Gone: the
> Twombly adapter, its version pin, port and privacy flags, canvas comments and
> focus (`feedback`), and the Excalidraw scrub, which only existed to pass
> Twombly's secret check. A test now fails if "twombly" appears under `skills/`.
> The Twombly decisions below are left as written, as a record of what was built.

## Goal contract

- **Objective:** ship a Stack-owned `micro-branch` skill that keeps every design iteration as its own git branch ("take"), lays takes out side by side on a canvas, and lets the person jump back to any take or pick one into trunk.
- **Constraints:** Change.org-agnostic (no company names, systems, registries or repos in the skill). Python 3 stdlib only. Never pushes, never shares a canvas, never deletes a take without first tagging it. Touches only the new skill folder plus the registry, docs and tests that every new capability updates.
- **Validation command:** `python3 scripts/classify-capabilities.py --check && python3 scripts/build-capability-registry.py --check && python3 scripts/apply-skill-layout.py --dry-run && python3 -m unittest discover -s tests`, plus one end-to-end run on a throwaway repo.
- **Stop condition:** CI green, PR merged to `main`, runtime reinstalled, and `stack:micro-branch` present in `~/.claude/skills/stack/skills/micro-branch/`.
- **Documentation:** the skill's `SKILL.md` and references explain the workflow; this plan records the decisions.

## Product contract

### Problem

When a person iterates with a coding agent, each change usually replaces the previous version. Design work is not linear: people try several answers to one question, go back, and build on an earlier attempt. Keeping versions by hand as sibling files breaks as soon as a shared component changes, and nothing shows the attempts side by side.

### Requirements

- R1. One command starts a round: a named design question with a base commit.
- R2. One command cuts a take: a new branch from the round's base (or from another take) with its own worktree, so takes never overwrite each other.
- R3. Publishing a take builds it, snapshots the static output, and places it on a canvas as a labelled frame. A failed build publishes nothing and marks the take broken.
- R4. Any take can be reopened at any time, including archived ones.
- R5. Picking a take squash-merges it into trunk with a traceable commit message, then archives every take in the round as a tag.
- R6. A new round can start from a take without merging it.
- R7. Canvas feedback (what the person is looking at, comments) comes back as JSON mapped to takes.
- R8. Two canvas adapters: Twombly (default, pinned version, localhost only) and a zero-dependency local board.
- R9. Hard limits: at most 4 takes per round by default (configurable up to 8); no push; no share; pick refuses a dirty trunk.
- R10. Nothing in the skill names an employer, design system or private registry.

### Scope boundaries

- Out: sharing canvases, hosted review, multi-person locking, Design Studio presets, dev-server capture for apps without a static build (documented as a follow-up).
- Out: importing `materic-inc/twombly-skill`. It has no license and only tells the agent to run `twombly@latest`; the skill's own reference pins the CLI instead.

## Key technical decisions

- KTD1. **Deterministic work lives in `scripts/mb.py`; judgment lives in `SKILL.md`.** The script owns git, worktrees, state, builds and adapters, and prints JSON. The agent decides what each take should try and how to read feedback.
- KTD2. **State lives in `<git-common-dir>/micro-branch/state.json`.** Every worktree shares it, it never leaves the machine, and it adds no files to the project. Branches and tags remain the source of truth for code.
- KTD3. **Names.** Round `r<N>-<slug>`, take `t<N>-<slug>`, branch `mb/<round>/<take>`, archive tag `mb-archive/<round>/<take>`, worktree `<repo-parent>/<repo-name>.takes/<round>/<take>`.
- KTD4. **Frames are snapshots.** The build output is copied to `<state-dir>/frames/<round>/<take>/` before publishing, so a frame survives worktree removal and rebuilds of other takes.
- KTD5. **Pick = squash merge + archive.** Trunk stays readable; tags keep every take's full history.
- KTD6. **Twombly is pinned and local.** The adapter runs `npx -y twombly@<pinned>` and never calls `share`. No silent fallback: when Twombly fails, the script says so and names the board adapter.
- KTD7. **Tests never touch the network.** The Twombly adapter is exercised through a fake CLI (`MB_TWOMBLY_CMD`).

## Implementation units

- U1. `mb.py` core: `init`, `config`, `status`, `round new`, `take new`, `open`. Tests on temp repos.
- U2. `publish`: build, snapshot, board adapter, Twombly adapter. Tests with a fake Twombly.
- U3. `pick`, `round next`, `round close`. Tests for squash, tags, worktree cleanup, dirty-trunk refusal.
- U4. `feedback`: Twombly context and comments mapped to takes.
- U5. `SKILL.md`, references, `capability.json`, registry rebuild, catalog counts.
- U6. End-to-end run on a throwaway repo with the board and with real Twombly (local only).
- U7. PR, CI, merge, runtime install, load check.

## Risks

| Risk | Mitigation |
|---|---|
| Twombly CLI changes (15 releases in two days) | Pin the version in config; the reference names the tested version |
| Twombly gates reject frames that load remote fonts or scripts | Reference explains bundling assets; board adapter has no gates |
| Worktree setup is slow for node projects | Optional `setup` command per take; pnpm/npm caches make repeats cheap |
| Branch sprawl | Take cap, archive on pick, `round close` |
