---
name: agent-operating-stack
description: "Route broad Stack/Hermes work through the right design, engineering, agent-orchestration, and verification loops. Use when adding external agent workflow ideas to Maroun's stack, choosing between ideate/departments/mega/tdd/review skills, drafting long-running /goal contracts, delegating subagents, or making Hermes/Mookie leverage Stack without unsafe core patches or unverified runtime claims."
---

# Agent Operating Stack

## Overview

Use this skill as the router for Maroun's operating stack: product/design pipelines, Matt Pocock-style engineering loops, David Ondrej-style agent orchestration, Emil Kowalski-style design engineering, and Hermes/Mookie safety gates. It turns broad requests into an executable loop with a source of truth, hard boundaries, and a verification gate.

Read [references/imported-skills.md](references/imported-skills.md) when you need the exact list of imported upstream skills. Read [references/source-map.md](references/source-map.md) when you need upstream provenance, license posture, or the detailed mapping from the Meng To post and linked repos into local Stack skills. Read [references/execution-routing.md](references/execution-routing.md) before any multi-agent, multi-reviewer, or long-running Hermes workflow.

## Operating Loop

For broad, urgent, multi-step, or "add this to the stack" requests:

1. Name the durable outcome in one sentence.
2. Identify the source of truth: repo files, issue, plan, UI, docs, screenshots, live service state, or an upstream source.
3. Name hard boundaries: what must not be mutated, weakened, promoted, exposed, or claimed as complete.
4. Choose the workflow lane below.
5. Choose the verification gate before acting.
6. Keep working until the gate passes or the same blocker repeats enough to mark blocked.
7. Close out with changed files, proof used, residual risk, and the next useful gate.

## Workflow Lanes

### New Product Or Feature

- Vague idea or startup wedge: use `ideate`.
- Brain dump needs a product/design spec: use `departments`.
- Build from idea through PR-quality verification: use `mega-workflow`.
- UI-heavy work: use `cdo`, then `emil-design-eng` and `review-animations` before shipping.

### Software Engineering

Use the Matt-derived loop as the default discipline:

- Concrete imported router: `$matt-ask-matt`.
- Ambiguous implementation: align vocabulary and decisions before coding. Create or update `CONTEXT.md`/ADRs only when the repo already uses them or the decision is genuinely durable.
- Single-session concrete work: use `$matt-implement` and `$matt-tdd` for small vertical slices where a real seam exists.
- Multi-session work: use `$matt-to-spec` and `$matt-to-tickets`; keep each ticket independently verifiable.
- Foggy or huge work: use `$matt-wayfinder`; map investigation decisions first and do not collapse planning and execution unless the destination is already clear.
- Bug or regression: use `$matt-diagnosing-bugs`; build a red-capable feedback loop before theorizing, then minimize, instrument, fix, and regression-test.
- Review: use `$matt-code-review`; separate standards/design quality from spec faithfulness so one axis does not mask the other.

### Agent Orchestration

Use the David-derived loop only when delegation or persistence is actually useful:

- Model routing: use Sol/high for orchestration and final synthesis, Terra/medium for implementation, Terra/high for risk review, and Luna/medium for bounded exploration. Do not let executors inherit Sol implicitly.
- `/goal`: use `$david-goal-loop` only for work with a concrete stop condition and validation command. Include objective, read-first files, constraints, validation, documentation, checkpoints, and stop condition.
- Subagents: use `$david-codex-subagent` only for self-contained work with the minimum required context, owned files/worktree isolation, and a clear definition of done. Prefer an artifact path or compact task packet over copying the full parent conversation. Review their diffs or artifacts before trusting them.
- Handoffs: use `$david-handoff` or `$matt-handoff` when a session must continue elsewhere; do not rely on chat memory alone for multi-session continuity.
- Scheduling: use `$david-agent-self-scheduling` for general agent scheduling guidance, but prefer Hermes' built-in scheduler for Hermes work. Ask before new cron, LaunchAgents, credential grants, paid services, or production-state changes.

Apply the quota and fan-out limits in `references/execution-routing.md`. External skills remain upstream-owned; Stack controls when they are invoked and prevents automatic implementation, simplification, full-review, and validator waves from stacking mechanically.

### Hermes And Mookie

When Hermes, Mookie, GBrain, Telegram gateway, Google/Gmail/Calendar, or local plugins are in scope:

- Read the local Hermes source of truth first: `~/hermes/MOOKIE.md`, `~/hermes/KNOWLEDGE.md`, `~/hermes/PILOT.md`, and the relevant plan/report under `docs/plans/` or `tmp/`.
- Prefer Hermes-native extension surfaces: plugins, hooks, config, root-level tests, skills, local scripts, and scheduler jobs.
- Do not preserve private Hermes core patches unless the user explicitly accepts the local patch plus a removal/upstream gate.
- Separate runtime liveness from auth health, queue health, lock state, and browser/account access.
- For Google/Gmail/Calendar claims, verify `gog auth list --check` or the local preflight before claiming live access.
- Preserve Sol/high for the user-facing Mookie root when its quality is valuable, but route delegated implementation to Terra and lightweight/background work to Luna. Control long-context growth and repeated cache reads instead of solving every quota problem by downgrading the interactive model.
- Use `hermes-native-patch-migration` for patch migration and `agent-verification-ladder` for proof selection.

## Verification Gates

Pick the lowest proof level that can genuinely prove the claim:

- Artifact: exact file, diff, report, source map, plan, screenshot, or output exists and matches the request.
- Command: focused test, lint, typecheck, parser, smoke command, or update dry-run passes.
- State: live service, branch, queue, LaunchAgent, gateway, deployment, auth, or lock state is checked.
- Browser/UI: `agent-browser` screenshot or smoke when user-visible rendering matters.
- Independent: focused validation thread or isolated worktree for broad, risky, or reusable workflow changes.

Never turn "no error shown" into proof. Name unproven gates explicitly.

## Hermes-Ready Skill Rules

When adding a reusable workflow to Stack for Hermes or Codex to leverage:

- Create or update a discoverable skill under `skills/<name>/`.
- Include `agents/openai.yaml` with a short default prompt using `$skill-name`.
- Keep `SKILL.md` lean; move provenance and detailed mapping into `references/`.
- Preserve source pins and license posture for imported/adapted upstream ideas.
- Prefix upstream imports when names would collide with Stack-native skills, as with `matt-*` and `david-*`.
- Prefer Stack-native skills for Maroun-specific behavior and imported skills for the upstream workflow they encode.
- Add README/config routing only when it improves discovery for future agents.

## Closeout Format

Report:

- workflow lane chosen;
- files changed;
- upstream sources or local surfaces inspected;
- verification command or artifact;
- Hermes/Mookie gate status when relevant;
- residual risk and next smallest gate.
