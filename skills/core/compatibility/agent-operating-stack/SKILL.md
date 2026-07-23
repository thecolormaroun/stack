---
name: agent-operating-stack
description: "Compatibility adapter for the canonical Stack root router."
---

# Agent Operating Stack

Deprecated compatibility adapter: route this legacy entry point through
[`stack`](../../stack/SKILL.md), using `registry/commands.json` and
`registry/routing-rules.json` as the authoritative command and routing sources.

Canonical target: `stack`

Do not recreate an operating loop here. The root router selects the canonical
route, applies its trust and approval class, and delegates to its owning
workflow.
