# Stack Agent Execution Policy

This is the local composition policy for Codex and Claude Stack workflows. It
controls when and how the wrappers use external workflows; it does not modify
`vendor/`, upstream skill files, or generated upstream agent definitions.

## Model roles

| Role | Model | Reasoning | Use |
|---|---|---|---|
| Orchestrator | `gpt-5.6-sol` | `high` | Decomposition, architecture, conflict resolution, final synthesis |
| Worker | `gpt-5.6-terra` | `medium` | Implementation, tests, general engineering work |
| Reviewer | `gpt-5.6-terra` | `high` | Correctness, security, contracts, and risk review |
| Explorer | `gpt-5.6-luna` | `medium` | Repository mapping, cataloging, extraction, summaries, and bounded research |

Use Sol as an explicit orchestrator, not as an inherited executor default. Use
`xhigh` only for an explicit escalation after a concrete hard problem survives
Sol/high or Terra/high. Do not select a model through task wording alone.

Codex role names are `worker`, `reviewer`, and `explorer`. When the active
subagent primitive exposes a role selector, select one of those roles explicitly.
When it does not, use a model-pinned, ephemeral `codex exec` process instead of
silently inheriting Sol:

```bash
codex exec --ephemeral --model gpt-5.6-terra \
  --config 'model_reasoning_effort="medium"' \
  --sandbox workspace-write "<self-contained worker packet>" </dev/null
```

Use Luna/`read-only` for explorer packets and Terra/`high`/`read-only` for
review packets. A subprocess receives a complete packet and never resumes the
orchestrator session.

## Portable quota preflight

Use quota information exposed by the active runtime when it is available.
There is no required external quota script. If quota state is absent, stale,
or unreadable, use the tested fail-closed fallback: mode `single`, maximum one
executor, Terra/Luna only, and no fan-out. This fallback makes the bundle
executable from a clean home while preserving the same safety boundary.

Honor the resolved mode:

| Rolling quota used | Mode | Maximum executors | Policy |
|---:|---|---:|---|
| `<50%` | `normal` | 3 | Bounded Terra/Luna fan-out allowed |
| `50-69%` | `constrained` | 2 | Terra/Luna only; prefer serial work |
| `70-84%` | `single` | 1 | No fan-out; one Terra/Luna executor at a time |
| `>=85%` | `pause` | 0 | Deterministic/local work only unless the user explicitly overrides |
| unknown | `single` | 1 | Fail closed: no fan-out, Terra/Luna only |

The preflight constrains model work, not safe local shell inspection. Do not
retry quota or capacity failures in a loop. Record whether quota came from the
runtime or the `single` fallback in the closeout.

## Durable run state

Resolve the Stack checkout with `STACK_REPO` or the current Git root. If
`scripts/stack-run-state.py` exists there, use it for run identity, child
leases, checkpoints, gates, resume, and terminal receipts. An installed stage
may also expose the same repository-relative helper; prefer the first verified
copy discovered from the stage or Stack checkout.

When the helper is unavailable, continue serially with the runtime's visible
plan/task state and project-local artifacts. Do not claim durable resume,
leases, or receipts in this fallback. This is a documented degraded mode, not
an instruction to fetch another workspace.

## Dispatch limits

- Maximum three open agent threads.
- Maximum nesting depth one. Children never spawn children.
- Use `fork_turns: "none"` for self-contained packets.
- Use at most `fork_turns: "3"` when the child genuinely depends on the latest
  exchange. Never use `fork_turns: "all"`.
- Give every child a bounded goal, relevant paths, boundaries, deliverable, and
  verification command. Pass artifact paths instead of replaying large content.
- Allow one follow-up turn per child. After that, close it and start a fresh,
  narrower packet only if the verification gate still requires work.
- Release completed agents promptly.
- Run one review wave. A second wave requires a validated P0/P1 finding or an
  explicit user request for deep review.

## Composing external CE skills

The external skills remain authoritative for their own behavior. The local
wrapper decides whether invoking the whole skill is proportionate.

### `ce-work`

- Run trivial and small work inline.
- Use Terra workers only for independent, bounded implementation units.
- Dispatch at most the quota preflight's executor count.
- Do not automatically chain implementation fan-out, three-way simplification,
  full review, and validator waves. The Stack wrapper owns that composition.

### `ce-simplify-code`

- Run at most once, at a phase boundary, on substantive human-authored code.
- In `normal` mode, the upstream three-lens pass may run with its reviewers on
  Terra/Luna.
- In `constrained` or `single` mode, perform reuse, quality, and efficiency as
  one inline pass instead of launching three reviewers.
- Skip it for documentation, configuration, generated, vendored, or mechanical
  changes, matching the upstream no-yield preflight.

### `ce-code-review`

- Default to a targeted/lite review: inline fast pass plus one Terra/high
  reviewer selected for the actual risk.
- Add a second reviewer only when the diff has a distinct high-risk surface.
- Invoke the full upstream multi-reviewer workflow only in `normal` mode when
  the user explicitly requests deep review or the diff touches authentication,
  payments, destructive data changes, public contracts, concurrency, or a
  verification mechanism that could silently pass.
- Validate P0/P1 findings independently. Do not launch one validator per weak
  P2/P3 item by default.

### Stack pipelines

- `stack-lfg` owns the normal review wave for its implementation.
- `stack-mega` must not automatically run another full `stack-review` after a
  successful `stack-lfg` review. Re-review only for material post-review edits,
  unresolved P0/P1 risk, or explicit deep-review intent.
- `stack-review` uses one findings-first pass sized by risk and quota. It does
  not stack gstack and full CE rosters mechanically.

## Verification gate

Before closing an orchestrated run, confirm:

1. Every child used the intended role/model/reasoning level.
2. No child used `fork_turns: "all"` or spawned descendants.
3. Peak open-agent count stayed within the quota preflight result and never
   exceeded three.
4. Only one review wave ran unless the P0/P1 exception was recorded.
5. The smallest reliable tests or artifact checks passed.
6. The closeout records the runtime quota result or the portable `single`
   fallback.
