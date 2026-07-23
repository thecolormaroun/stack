---
name: stack-orchestrate-parallel
description: Create bounded, durable parallel Stack workflow children through the local orchestration contract.
---

# Stack parallel goals

Use `stack-run-state.py` as the neutral run ledger. Record the canonical project identity, explicit child owner/model role, workspace or worktree, and artifact checkpoint paths. The run owner sets bounded fan-out; children must not spawn more children.

Do not treat a claimed lease as authority for external mutation. Review, QA, ship, and explicit approval remain separate contract gates. See `docs/orchestration-contract.md`.
