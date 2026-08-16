# Stack Agent Execution Policy

This is the local composition policy for Codex and Claude Stack workflows. It
controls when and how the wrappers use external workflows; it does not modify
`vendor/`, upstream skill files, or generated upstream agent definitions.

## Model roles

| Role | Model | Reasoning | Use |
|---|---|---|---|
| Primary orchestrator | `gpt-5.6-sol` | `high` | Requirements, decomposition, architecture, conflict resolution, verification, and final synthesis |
| Cost-effective worker | `gpt-5.6-luna` | `max` | Bounded, independently verifiable implementation or research units |
| Complex worker | `gpt-5.6-terra` | `max` | Context-heavy, high-risk, or wider-blast-radius implementation after route justification |
| Worker | `gpt-5.6-terra` | `medium` | Implementation, tests, general engineering work |
| Routine reviewer | `gpt-5.6-terra` | `high` | Correctness, security, contracts, and risk review for ordinary diffs |
| Consequential reviewer | `gpt-5.6-sol` | `high` | Fresh final acceptance or commitment judgment for consequential work |
| Explorer | `gpt-5.6-luna` | `medium` | Repository mapping, cataloging, extraction, summaries, and bounded research |

Use Sol/high as the default primary orchestrator. The primary keeps requirements,
architecture, worker specifications, reconciliation, authoritative verification,
and final acceptance. Children never inherit Sol accidentally: bounded routine
work uses Luna Max, and justified complex work uses Terra Max. Use `xhigh` only
for an explicit escalation after a concrete hard problem survives Sol/high or
Terra/high. Do not select a model through vague task wording alone.

Codex role names are `luna_worker`, `terra_complex_worker`, `worker`,
`reviewer`, `sol_reviewer`, and `explorer`. When the active subagent primitive
exposes a role selector, select one of those roles explicitly.
When it does not, do not substitute a role-less subprocess: model pinning cannot
prove the named role, its developer instructions, or the parent/child contract.
Keep the unit in the primary or stop and report that native attested dispatch is
unavailable. Cost-effective routing fails closed instead of approximating a
different lane.

## Default cost-effective execution

Apply cost-effective routing to every planning, implementation, and review run
unless the user explicitly overrides the route for that run:

- Prefer deterministic local tools before spending a model call.
- Use `luna_worker` first for bounded packets with explicit ownership, scope,
  and focused verification, including mechanical repository research,
  extraction, classification, low- or medium-risk implementation, and tests.
- Keep decomposition, architecture, ambiguity, cross-unit reconciliation,
  canonical commits, and final verification in the primary orchestrator.
- Route context-heavy, high-risk, or wider-blast-radius implementation to
  `terra_complex_worker` only after explicit classification or one corrected
  Luna attempt demonstrates the need.
- After the primary inspects the complete diff and reruns verification, use a
  fresh `sol_reviewer` as the final gate for consequential deliveries. Routine
  work keeps the proportionate Terra review path and does not pay a Sol-review
  tax.
- Never weaken safety, quota, review, approval, backup, or verification gates
  to obtain a cheaper route.

## Consequential Sol gates

Use one fresh Sol/high context for either of these bounded gates:

- **Commitment review:** before committing to consequential architecture,
  authentication or security boundaries, payments, migrations, destructive
  data changes, public contracts, production-state changes, or wide refactors.
  Require `proceed`, `change`, or `stop`.
- **Final delivery review:** after parent verification when the implemented
  change touches one of those surfaces or is a substantial cross-cutting
  multi-agent delivery. Require `ship`, `fix-first`, or `rethink`.

The final Sol review replaces the default Terra reviewer unless a separate,
distinct domain-risk review is justified. Treat all selected reviewers as one
risk-sized review wave rather than mechanically stacking generic passes. Any
implementation fix invalidates the prior final verdict and requires a new fresh
Sol review.

The reviewer requests a read-only sandbox, but the host's observed policy is
authoritative. If the host broadens isolation, continue only when hard isolation
is not required and the primary proves exact before/after repository and artifact
state. If isolation is unobservable, a mutation occurs, or hard isolation is
required, stop the gate instead of claiming a read-only review.

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

The executor cap constrains child implementation and research work, not the
already-active Sol primary or safe local shell inspection. Serialize a required
Sol final review after implementation. In `pause` mode, do not spend a reviewer
call without an explicit override; leave consequential acceptance blocked. Do
not retry quota or capacity failures in a loop. Record whether quota came from
the runtime or the `single` fallback in the closeout.

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
- Run one risk-sized review wave. A consequential Sol final gate belongs to
  that wave; a second generic wave requires a validated P0/P1 finding or an
  explicit user request for deep review. A fresh re-review after a required fix
  is not optional because the earlier verdict is invalid.

## Composing external CE skills

The external skills remain authoritative for their own behavior. The local
wrapper decides whether invoking the whole skill is proportionate.

### `ce-work`

- Run trivial and small work inline.
- Prefer `luna_worker` for well-specified, independently verifiable units.
- Route context-heavy, high-risk, or wider-blast-radius units to
  `terra_complex_worker` only when the classification or a corrected Luna
  attempt justifies escalation.
- Keep the Sol/high primary responsible for the actual diff, authoritative test
  reruns, and the consequential final-review decision.
- Use Terra workers only for independent, bounded implementation units.
- Dispatch at most the quota preflight's executor count.
- Do not automatically chain implementation fan-out, three-way simplification,
  full review, and validator waves. The Stack wrapper owns that composition.

### `ce-plan`

- Use `luna_worker` for bounded repository mapping, pattern inventories,
  extraction, and learnings research.
- Keep scope, architecture, reconciliation, confidence judgment, and final
  plan authoring in the Sol/high primary unless the user selects another model.

### `ce-simplify-code`

- Run at most once, at a phase boundary, on substantive human-authored code.
- In `normal` mode, the upstream three-lens pass may run with its reviewers on
  Terra/Luna.
- In `constrained` or `single` mode, perform reuse, quality, and efficiency as
  one inline pass instead of launching three reviewers.
- Skip it for documentation, configuration, generated, vendored, or mechanical
  changes, matching the upstream no-yield preflight.

### `ce-code-review`

- Default routine diffs to a targeted/lite review: inline fast pass plus one
  Terra/high reviewer selected for the actual risk.
- For a consequential implemented diff, use the fresh `sol_reviewer` final gate
  after parent verification. Do not also add the default Terra reviewer unless
  a distinct domain-risk surface justifies it.
- Seed selected Compound Engineering persona prompts into the pinned `reviewer`
  role. Do not directly dispatch model-unpinned `ce-*` persona profiles.
- Add a second reviewer only when the diff has a distinct high-risk surface.
- Invoke the full upstream multi-reviewer workflow only for an explicitly deep,
  non-consequential review in `normal` mode. For consequential authentication,
  payments, destructive data, public-contract, concurrency, or silent-pass
  verification risks, seed the applicable lenses into the fresh Sol final gate
  rather than launching a second generic roster.
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
6. A required consequential final review returned `ship`, and any post-review
   fix received a new verdict.
7. Reviewer isolation was observed, or broader host policy was reported with
   exact before/after state proof.
8. The closeout records the runtime quota result or the portable `single`
   fallback.
