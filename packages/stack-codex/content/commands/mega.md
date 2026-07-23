---
name: mega
description: Large autonomous workflow for fuzzy, high-leverage, or multi-step work
argument-hint: "[goal or project]"
---

Use the `stack-mega` skill in this plugin.

Read `../references/agent-execution-policy.md` first and obey its model,
quota, context, concurrency, and single-review-wave limits.

Sequence:

1. `stack-ideate`
2. lock the plan
3. `stack-lfg`
4. reuse the `stack-lfg` review unless material edits, P0/P1 risk, or explicit
   deep-review intent require `stack-review`
