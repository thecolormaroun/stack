---
name: stack-run
description: "Canonical composite Stack workflow run with explicit evidence and approval gates."
---

# Stack Run

`stack.run` is the one composite workflow. Use the shared lifecycle and local
ledger defined in [`docs/orchestration-contract.md`](../../../docs/orchestration-contract.md):
create or resume a run, record project artifacts as checkpoints, and preserve
separate review, QA, ship, and approval gates.

Its modes are `full`, `plan`, `build`, `verify`, and `ship`:

- `plan` routes the planning stage.
- `build` routes an approved plan to implementation.
- `verify` records independent review and QA evidence.
- `ship` requires passed review and QA gates plus explicit approval before any
  external mutation.
- `full` advances through the applicable stages in that order, stopping at a
  failed, missing-evidence, or approval gate.

Delegate each stage to its canonical Stack command and its owning provider.
Do not reproduce CE, GStack, or domain workflow details here. A workflow ledger
records coordination state; it never grants authority to push, merge, deploy,
buy, schedule, or otherwise mutate an external system.
