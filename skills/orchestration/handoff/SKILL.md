---
name: stack-orchestrate-handoff
description: Hand off a Stack workflow child with explicit ownership, checkpoints, and independent review and QA gates.
---

# Stack handoff

Record the child's owner, role, model role, workspace/worktree scope, and project-artifact checkpoint paths in the shared run. The receiving worker must claim a current lease before changing that child. Handoffs do not automatically pass review, QA, ship, or approval gates.

Keep vendor-specific execution details in the host adapter; this skill defines only Stack's portable contract.
