---
name: stack-ideate
description: |
  Product, UX, and implementation shaping workflow. Use when the user needs help
  turning a vague idea into a buildable direction with real tradeoffs.
---

# stack-ideate

## Resolve the right upstream voices

Read these first:

- `../../references/upstreams.md`
- For frontend, UI motion, or package selection: `../../references/frontend-libraries.md`
- Installed GStack `office-hours` and `design-consultation`, when available.
- Installed Compound Engineering `ce-ideate`, `ce-brainstorm`, and `ce-plan`,
  when available.

If the package exports are unavailable, use the output shape and behavior below
inline; do not search an unrelated home-directory workspace.

## Output shape

Produce a compact result with:

1. Best framing of the user problem
2. One recommended direction and why
3. The main risks or open decisions
4. A plan concrete enough to hand off to `stack-lfg`

## Behavior

- Stay grounded in the repo and the user's actual constraints.
- Prefer one strong direction over a pile of equivalent options.
- When frontend or product taste matters, use gstack's design voice before finalizing the plan.
