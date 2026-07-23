---
name: stack
description: "Canonical Stack root router for choosing a command, trust class, and owning workflow."
---

# Stack

`registry/commands.json` is authoritative for canonical commands, ownership,
trust classes, aliases, and runtime names. Apply
`registry/routing-rules.json` in its declared order: canonical id, alias,
intent, then context.

1. State the selected canonical route and the reason it fits the request.
2. Apply that route's trust class before delegation. Read-only work may inspect;
   local mutation requires the active workspace scope; external mutation also
   requires explicit approval.
3. Delegate to the route owner and keep provider-native CE, GStack, and
   Stack-Codex commands available as registry aliases; do not translate or
   duplicate their workflows here.

If review could mean code, architecture, security, data, or simplicity, ask
which review target is intended (and request the artifact/context if absent)
before routing to `stack.review`.

`stack` itself supports `help`, `route`, and `status`. It is a router, not a
composite workflow; use [`stack.run`](../run/SKILL.md) for an end-to-end run.
