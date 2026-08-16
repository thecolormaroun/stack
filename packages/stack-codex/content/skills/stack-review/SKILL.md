---
name: stack-review
description: |
  Findings-first code review that combines gstack's review discipline with compound-engineering's
  deeper failure-mode and stakeholder lenses. Use when the user asks for review,
  audit, risk analysis, or "is this ready?".
---

# stack-review

Read `../../references/agent-execution-policy.md` and resolve quota through the
runtime or the portable `single` fallback before dispatching any reviewer.
External review skills remain unchanged; this wrapper chooses the smallest
review shape that proves readiness.

## Read upstream review guides

1. `../../references/upstreams.md`
2. Installed GStack `review` and `qa` capabilities, when available.
3. Installed Compound Engineering `ce-code-review`, when available.

If those package exports are unavailable, perform the findings-first method
below inline and report that the package-specific lenses were unavailable.

## Review method

1. Start with findings, not summary.
2. Order by severity and user impact.
3. Use concrete file and line references whenever possible.
4. Choose exactly one review owner for the run:
   - Routine diff: run an inline fast pass plus one `reviewer` (Terra/high) for
     the highest actual risk.
   - Consequential diff: verify the accumulated diff in the primary, then use
     one fresh `sol_reviewer` and require `ship`, `fix-first`, or `rethink`.
     Rerun it after any implementation fix.
   - Explicit deep, non-consequential review in `normal` quota mode: use the
     full upstream `ce-code-review` roster instead of the routine reviewer.
5. Cover both:
   - Code correctness and regressions
   - Operational, security, and deployment risks
6. Treat these as protected artifacts, not cleanup targets:
   - `docs/plans/*.md`
   - `docs/solutions/*.md`
7. Treat upstream review guides as inputs or fallbacks, not additional review
   calls. Do not stack GStack `review`, `ce-code-review`, a routine reviewer,
   and a consequential Sol gate. Add one distinct domain reviewer only when the
   local execution policy explicitly justifies it and quota mode permits it.
8. Validate P0/P1 findings independently. Do not launch validators for every
   weak P2/P3 observation.

## Output contract

- If there are findings, lead with them.
- If there are no findings, say that plainly and then note residual risk or test gaps.
- If the user wants fixes, implement them and re-run targeted validation.
- Run one risk-sized review wave. A fix invalidates a consequential Sol verdict
  and requires a fresh verdict for the changed diff.
