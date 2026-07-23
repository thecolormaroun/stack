---
name: stack-mega
description: |
  Large autonomous workflow for fuzzy or high-leverage work. Use when the task is
  bigger than a normal feature pass and needs ideation, planning, implementation,
  review, and ship discipline in one flow.
---

# stack-mega

Use this when `stack-lfg` is not enough because the problem is still fuzzy, the scope is large, or the user wants a more ambitious pass.

Read `../../references/agent-execution-policy.md` and run the quota preflight
before selecting any multi-agent phase. The larger scope does not raise the
three-agent, depth-one, or one-review-wave limits.

## Sequence

1. Start with `stack-ideate`.
2. Convert the chosen direction into an explicit plan.
3. Run `stack-lfg` on the chosen plan.
4. Treat the review produced by `stack-lfg` as the final review by default.
5. Run `stack-review` again only after material post-review edits, for unresolved
   P0/P1 risk, or when the user explicitly asks for a separate deep review.

## Upstream inputs

Read these official sources before you lock the plan:

- local stack references:
  - `../../references/upstreams.md`
  - `../../references/frontend-libraries.md` when the work includes frontend package or microinteraction choices
- installed GStack capabilities: `office-hours`, `design-consultation`, and
  `autoplan`
- installed Compound Engineering capabilities: `ce-ideate`, `ce-brainstorm`,
  `ce-plan`, `ce-work`, `ce-code-review`, and `lfg`

When an installed package export is unavailable, keep the sequence using the
Stack skills' documented inline fallbacks and report the missing enhancement.

## Standard

- Prefer complete plans over happy-path plans.
- Keep user-visible tradeoffs explicit.
- Do not stop at "here is what I would do." Actually do the work unless blocked.
- Keep Sol/high in the orchestrator lane and Terra/Luna in execution lanes.
- Never trade quota for duplicate phase coverage: one phase owns each output.
