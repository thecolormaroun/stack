# stack-codex

`stack-codex` is a thin orchestration layer.

It does three things:

1. Uses the official `gstack` Codex skills when they exist
2. Reads the official `compound-engineering` command docs in place
3. Adds local workflow glue so Claude Code and Codex can stay aligned

The plugin intentionally does not vendor external upstream content into the
skills. Resolve the Stack checkout before using repository helpers:

```bash
STACK_REPO_DIR="${STACK_REPO:-$(git rev-parse --show-toplevel)}"
```

Set `STACK_REPO` when the current Git root is not the Stack checkout. A normal
clean-home installation uses `scripts/bootstrap-stack.py`; it stages the
repository bundle and the pinned external package exports beneath the selected
deployment root. No separate `Codex` workspace is required.

## Agent routing

The local execution policy lives at
`references/agent-execution-policy.md`. The default primary is Sol/high, while
bounded work routes to Luna Max first and justified complex work escalates to
Terra Max. The safe fallback is a single Terra/Luna executor when quota state
is unavailable. A fresh Sol/high review is the final gate for consequential
deliveries, not routine work.

Local `explorer`, `luna_worker`, `terra_complex_worker`, `worker`, `reviewer`,
and `sol_reviewer` roles pin Luna/Terra/Sol models, while quota preflight limits
concurrency and review fan-out. External gstack and compound-engineering files
remain untouched.
