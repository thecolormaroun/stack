# Stack command tree

`registry/commands.json` is the authoritative command registry. This table is
a documentation mirror of its primary command IDs and trust classes; update it
only when the registry changes.

| Command | Owner | Trust class |
| --- | --- | --- |
| `stack` | `core-stack` | `read-only` |
| `stack.explore` | `cpo` | `read-only` |
| `stack.plan` | `compound-engineering` | `read-only` |
| `stack.design` | `cdo` | `read-only` |
| `stack.build` | `compound-engineering` | `local-mutation` |
| `stack.orchestrate` | `stack-codex` | `local-mutation` |
| `stack.review` | `compound-engineering` | `read-only` |
| `stack.qa` | `gstack` | `read-only` |
| `stack.ship` | `gstack` | `external-mutation` |
| `stack.learn` | `gstack` | `read-only` |
| `stack.maintain` | `stack-codex` | `local-mutation` |
| `stack.run` | `core-run` | `local-mutation` |

Legacy adapters preserve existing entry points: `agent-operating-stack` maps to
`stack`; `mega-workflow` maps to `stack.run full`; `departments` maps to
`stack.run plan`; and `ideate` maps to `stack.explore ideate`. Direct
CE, GStack, and Stack-Codex commands remain usable through their registry
aliases. The router asks for clarification when review intent is ambiguous and
never performs an external mutation without explicit approval.
