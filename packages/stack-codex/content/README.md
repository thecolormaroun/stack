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
`references/agent-execution-policy.md`. The safe fallback is a single executor
when quota state is unavailable. The active runtime may select a stronger
orchestrator explicitly; the bundle does not require a separate launcher.

Local `explorer`, `worker`, and `reviewer` roles pin Luna/Terra models, while
quota preflight limits concurrency and review fan-out. External gstack and
compound-engineering files remain untouched.
