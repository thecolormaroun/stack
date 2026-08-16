---
name: stack-lfg
description: |
  Full autonomous build loop for Codex using official gstack and compound-engineering
  upstreams. Use when the user wants a scoped feature taken from plan to reviewed,
  shippable code with minimal back-and-forth.
---

# stack-lfg

## Resolve upstreams first

1. Read `../../references/agent-execution-policy.md` and resolve quota through
   the runtime or its portable `single` fallback.
2. Read `../../references/upstreams.md`.
3. Invoke installed GStack and Compound Engineering sibling skills by their
   declared names.
4. If an upstream export is unavailable, use the inline plan, implementation,
   review, and verification steps below and report the missing enhancement.

## Workflow

1. Clarify the target only if ambiguity will cause rework.
2. Treat installed Compound Engineering capabilities `ce-plan`, `ce-work`,
   `ce-code-review`, `ce-simplify-code`, `ce-test-browser`, and
   `ce-commit-push-pr` as available phase owners, not a mandatory chain.
3. Treat installed GStack `autoplan`, `review`, `qa`, and `ship` capabilities
   the same way. Select one review owner and one ship owner per run; use the
   other upstream guides as inputs or fallbacks rather than duplicate calls.
4. Build the plan, implement the work, and keep artifacts in-repo when they help:
   - `docs/plans/`
   - `docs/solutions/`
   - Sol/high owns planning, architecture, reconciliation, verification, and
     synthesis. Dispatch bounded Luna workers first and Terra workers only for
     justified complex units, within the quota preflight result.
5. Review before close-out:
   - Run one findings-first review wave sized by risk and quota.
   - Use an inline fast pass plus one Terra/high reviewer for routine diffs.
   - For consequential deliveries, run a fresh Sol/high final review after the
     primary verifies the diff. Require `ship`, `fix-first`, or `rethink`, and
     rerun it after any implementation fix.
   - `stack-lfg` owns that final verdict. A parent orchestrator consumes the
     valid verdict for the same verified diff instead of launching another.
   - Invoke full compound multi-angle review only for an explicitly deep,
     non-consequential review in `normal` quota mode. For consequential work,
     feed the applicable lenses to the fresh Sol gate instead.
   - Do not stack a second review merely because two upstream guides exist.
   - focused validation for changed code paths
6. If the work is frontend-heavy, run browser verification and note the result.
   - For frontend package and microinteraction choices, read `../../references/frontend-libraries.md` and use those recommendations only when they fit the target project's stack.
7. If the user asked for a PR or ship step, finish with the gstack ship flow or the repo's existing GitHub flow.

## Rule

Do not freeze upstream instructions into this skill. Invoke installed upstream
capabilities at runtime and use this skill as the orchestration layer.

Do not patch upstream skills. The local execution policy controls composition:
at most three agents, depth one, no `fork_turns: "all"`, one follow-up per
child, one simplification phase, and one review wave unless a validated P0/P1
requires another pass.
