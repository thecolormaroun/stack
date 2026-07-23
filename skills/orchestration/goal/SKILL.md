---
name: stack-orchestrate-goal
description: Manage an observable, resumable Stack goal lifecycle without owning project artifacts.
---

# Stack goal lifecycle

Create or resume a run in the owner-local state store and keep the plan and deliverables in the active project. Checkpoint durable project artifact paths before handoff or lease expiry. A cancelled run may be resumed before it receives a terminal receipt; a receipted run is immutable.

Use the same logical states in Claude and Codex. Host-specific delegation APIs are adapters, not lifecycle definitions.
