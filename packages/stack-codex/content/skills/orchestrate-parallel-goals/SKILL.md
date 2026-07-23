---
name: orchestrate-parallel-goals
description: Turn broad, fuzzy, ambitious, multi-step, or build-like user requests into a concrete operating loop with a filled template-style brief, top-level goal, useful parallel subgoals, execution, synthesis, and verification. Use when the user asks to "build [thing] in [tech/framework]", create or write a /goal, spawn agents, use parallel agents, split work into subagents, run multiple workstreams concurrently, "go for it", "keep looping", "take this end to end", or gives an open-ended product/design/code/document/research task that would benefit from goal-setting and parallel investigation. Avoid for tiny one-step answers, narrow code-review requests, or tasks with explicit no-subagent/no-parallelism boundaries.
---

# Orchestrate Parallel Goals

Use this skill to convert a raw task into a self-directed execution loop. Keep it lightweight: the goal is better momentum and decomposition, not ceremony.

## 0. Load The Local Execution Policy

Read `../../references/agent-execution-policy.md` before deciding whether to
delegate. Use quota state exposed by the active runtime. If it is unavailable,
use the policy's portable `single` fallback: one executor and no fan-out.

Resolve the Stack checkout from `STACK_REPO` or the current Git root. When
`scripts/stack-run-state.py` exists in the installed stage or checkout, use it
for the run identifier, children, checkpoints, gates, resume, and receipt. If
it is unavailable, continue serially with visible runtime task state and
project-local artifacts, and report that durable resume was unavailable. Sol
owns decomposition and final synthesis; use the configured `worker`,
`reviewer`, and `explorer` roles for Terra/Luna execution. Never let a child
inherit Sol accidentally.

## 1. Fill The Brief

Translate the user's request into a concise brief. For broad build, product, design, or prototype asks, first compress the request into a filled template-style seed:

```text
Build [specific thing] in [tech/framework/environment].
It should include [main capabilities], with [interaction, animation, behavior, or workflow details].
Make it feel [mood or quality bar], using [visual, source-material, data, environment, or domain details] and [extra effects or constraints].
Output [format, files, change set, screenshot, PR, deployed state, or verified result].
```

Then adapt this broader shape to the domain:

```text
Create [artifact] using [environment or stack].
Include [core capabilities or deliverables].
Define [behaviors, interactions, constraints, or acceptance details].
Aim for [quality bar, mood, or operating standard].
Use [important context, source material, visual details, data sources, or constraints].
Produce [final artifact, change set, answer, PR, file, screenshot, or verified state].
```

Do not leave placeholders in the brief. Preserve useful user language, especially mood, quality, interaction, visual, and environment cues, then turn vague adjectives into observable acceptance details where possible. Infer conservative defaults from the repo, existing files, user preferences, and live state. Ask only when the missing detail would make the work risky, irreversible, expensive, or likely to violate the user's intent.

Treat a top-level goal or subgoal as exit criteria, not just an opening prompt. Before dispatch or long-running execution, tighten the brief until a later agent can tell whether the work is done without rereading the whole thread:

- Prefer measurable success criteria: numeric or computable targets when they fit; otherwise use explicit feature, spec, design-system, or acceptance checklist criteria.
- Give starting guidance when possible: likely files, tools, environments, docs, commands, known constraints, and paths that would send the agent in the wrong direction.
- Name progress signals for ambitious work: tests, benchmarks, coverage, eval suites, visual diffs, preview deploys, screenshots, or a durable status artifact.
- Require a realistic environment for performance, deployment, data, browser, mobile, or integration goals: same stack, flags, data shape, deploy target, or device class where feasible.
- For visual goals, use images as context and comparison aids, but define completion with implementable criteria. Do not accept cropped screenshots, weakened tests, reduced coverage, or other fake progress as success.

## 2. Set The Operating Loop

Before acting, identify:

- Goal: the durable outcome to deliver.
- Source of truth: files, UI, docs, command output, screenshots, APIs, or other concrete evidence.
- Boundaries: what must not be touched, weakened, deleted, promoted, exposed, or claimed as complete.
- Verification gate: the measurable command, screenshot, UI check, test, artifact, or deploy status that proves done.
- Loop policy: keep going until the gate passes, or mark blocked after the same blocker repeats three times.
- Closeout: what changed, what was verified, what remains risky, and the next useful move.

For long-running goals, decide how progress stays visible: meaningful commits, a draft PR, a markdown/HTML status artifact, a dashboard, scheduled check-ins, or another durable trail that fits the project.

If a goal tool or `/goal` workflow is available and the current user request or platform policy allows creating a goal, create a top-level goal from the brief. Otherwise, keep the goal as an internal objective and use the available task-tracking primitive, such as `update_plan`, for visible progress on substantial tasks.

## 3. Route Through Stack Capabilities

Before splitting or executing, choose whether an existing stack layer should own a phase:

- Use `stack-ideate` when the problem framing, product shape, UX direction, or tradeoffs are still open.
- Use `stack-mega` when the work is broad enough to need ideation, planning, implementation, review, and validation in one autonomous pass.
- Use `stack-lfg` when the request is scoped enough to take from plan to reviewed, shippable code.
- Use `stack-review` before calling implementation ready, or whenever the request is review-shaped.
- Use `stack-ship` only when the user wants a PR, push, merge prep, or shipping hygiene.
- Use `stack-sync` only for stack/runtime parity, upstream refreshes, plugin drift, or install issues.
- For frontend-heavy work, read `../../references/frontend-libraries.md` before choosing packages, UI blocks, animation helpers, or microinteraction defaults.

Prefer these local routing skills over copying upstream workflow detail into
this file. When direct upstream context is needed, resolve it through
`../../references/upstreams.md` and invoke the installed sibling capability by
name.

## 4. Split Parallel Work

Break the task into independent workstreams only when parallelism will improve speed or quality.

Good workstreams include:

- Context discovery against different source surfaces.
- Product or requirements shaping from existing evidence.
- Architecture, data, integration, or risk review.
- UI, interaction, copy, or visual direction.
- Implementation of separable modules or files.
- Verification, edge-case review, and test planning.

Avoid parallel dispatch when the task is tiny, when sequencing is required, when shared files would cause churn, when platform policy does not allow agent spawning, or when user boundaries rule it out.

Apply the local limits even when more workstreams exist: at most three open
agents, depth one, and the lower executor count returned by the quota preflight.
Queue or execute remaining units serially. Use one review wave; a second wave
requires a validated P0/P1 issue or explicit deep-review intent.

## 5. Dispatch With Subgoals

When true subagent tools are available, give each agent a self-contained goal:

```text
Goal: [one clear subgoal]

Context: [filled brief plus only the relevant constraints]
Deliverable: [specific output needed by the main agent]
Boundaries: [owned files, decisions, and areas to avoid]
Verification: [checks, evidence, or reasoning required]
Progress: [signals or artifact the main agent can inspect]
```

Dispatch useful subagents concurrently only when the tool surface supports it and the current user/platform policy permits it. In Codex, use real subagents only when the user explicitly asks for subagents, delegation, or parallel agent work; otherwise parallelize safe local inspection commands with `multi_tool_use.parallel` and do the remaining synthesis directly in the main thread.

Use `fork_turns: "none"` for these self-contained packets. Use at most
`fork_turns: "3"` when a child genuinely needs the latest exchange, and never
use `fork_turns: "all"`. Allow one follow-up turn per child, then close it.
Select `explorer` for read-only discovery, `worker` for implementation, and
`reviewer` for risk review. If the dispatch primitive cannot select a role or
model, use the explicit model-pinned `codex exec --ephemeral` fallback from the
local execution policy.

Do not create extra agents just to look busy. The main agent owns the task, the edits, the truth checking, and the final answer.

## 6. Synthesize And Execute

As results return:

- Compare recommendations against the source of truth.
- Resolve conflicts explicitly.
- Apply only the parts that fit the user's request and project constraints.
- Preserve existing repo patterns and avoid unrelated refactors.
- Verify untrusted or speculative claims before relying on them.
- Watch for false completion signals such as lowered thresholds, disabled paths, superficial visual matches, fixture-only success, or passing tests with reduced coverage.

Then implement the focused change, run the smallest reliable verification gate, and keep looping until the gate passes or a real blocker remains.

Before closeout, record the runtime quota result or portable `single` fallback
and verify the child session metadata shows Terra/Luna at the intended
reasoning levels, no full-history forks, no nested descendants, and no
duplicate review wave. When `scripts/stack-run-state.py` was used, include its
gate and receipt evidence.

## 7. Close Out

Report the completed result in plain language. Include what changed or was produced, what verification ran, and any real residual risk or blocker. For goals that took multiple attempts, review the final diff for failed experiments, cleanup gaps, or artifacts that should not ship before calling the goal achieved. Keep raw logs out of the final answer unless the user asked for them.
