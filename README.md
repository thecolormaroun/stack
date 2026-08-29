# Stack

Stack is a curated capability system for designing and building software. Its
active capabilities are reusable skills and reference knowledge that improve
product thinking, interface design, implementation, review, verification, or
shipping. Orchestration belongs here only when it directly serves one of those
design/build workflows.

The repository is the versioned source of truth and the installer for its
compiled runtime. It is not a general personal-operations library; Codex,
Claude, and Hermes use only outputs that have passed review and validation.

## Quick start

Stack publishes the same active local capabilities to isolated Claude and Codex
namespaces. The repository-owned Stack-Codex skills, commands, agents, and
references are staged alongside them; pinned Compound Engineering and GStack
checkouts live only in the deployment root's package cache.

```sh
python3 scripts/build-capability-registry.py --check
python3 scripts/bootstrap-stack.py
```

For a fresh-machine installation, make the deployment root explicit. Use your
home directory to integrate the namespaced runtime with Claude and Codex; it
must remain separate from the checkout:

```sh
python3 scripts/bootstrap-stack.py --install \
  --deployment-root "$HOME" \
  --staging-root "$HOME/.local/share/stack/stages" \
  --receipts-dir "$HOME/.local/state/stack/runtime-receipts"
python3 scripts/stack-doctor.py --deployment-root "$HOME"
```

Real installation refuses a dirty checkout. Read-only bootstrap/doctor checks
remain usable while developing in one. Runtime targets are atomically switched
under `.claude/skills/stack` and `.codex/skills/stack` within the deployment
root; no machine-specific workspace or pre-existing global vendor directory is
used.

## What belongs

A capability belongs in active Stack only if it materially improves the design
or construction of software. Use the inclusion test in
[`docs/architecture.md`](docs/architecture.md) before adding or activating an
entry. Useful personal operations, finance, household, shopping,
file-organization, and general knowledge-management workflows remain outside
the product unless they directly support a named design/build workflow.

## Operating model

1. **Catalog and audit.** Each `skills/**/capability.json` manifest is the
   authoritative local contract. The generated
   [`registry/capabilities.json`](registry/capabilities.json) is a deterministic
   aggregate, not a hand-edited source of truth. The read-only audit produces
   evidence and proposed dispositions; it never moves or deletes content.
2. **Private knowledge and curation.** Field Theory supplies the default
   bookmark boundary and the private `x-bookmarks` GBrain source is the search
   authority. Reconciliation proves historical coverage and recurring deltas;
   raw content stays owner-local while Stack receives only safe projections.
3. **Design intelligence.** Safe source observations become cited design cards
   and source-scoped retrieval results. Relevant evidence can prepare a minimal
   skill or reference patch, but only a pinned evaluation can advance it to
   `awaiting_approval`. Capturing or retrieving a link is never promotion.
4. **Human gate.** Provenance, evaluation, activation, and publication require
   review. Automation may collect evidence and prepare candidates, but may not
   activate, merge, install, or publish a capability.
5. **Publication and recovery.** The compiler selects only reviewed `active`
   entries for a declared target, stages all outputs, and the installer switches
   them atomically. Receipts preserve the catalog digest, source commit, and
   prior target pointers for rollback without rewriting source history.
6. **Reassessment.** Periodic review uses validation, overlap, upstream health,
   maintenance, scope, and usage as separate signals. Low usage alone never
   auto-archives a capability.

Read the detailed contracts:

- [`docs/skill-architecture.md`](docs/skill-architecture.md) — the current 141-capability estate, cuts, merges, families, packages, and routing model.
- [`docs/architecture.md`](docs/architecture.md) — ownership, catalog, and inclusion boundary.
- [`docs/capability-lifecycle.md`](docs/capability-lifecycle.md) — evidence, review, and lifecycle transitions.
- [`docs/bookmark-curation.md`](docs/bookmark-curation.md) — safe intake through review packet.
- [`docs/design-intelligence-loop.md`](docs/design-intelligence-loop.md) — private evidence, cited critique, retrieval, and evaluated learning.
- [`docs/weekly-intelligence-operations.md`](docs/weekly-intelligence-operations.md) — idempotent weekly coordination and recovery.
- [`docs/runtime-publication.md`](docs/runtime-publication.md) — staging, receipts, rollback, and scheduler boundary.
- [`docs/private-overlay.md`](docs/private-overlay.md) — owner-only private reference packs.
- [`templates/periodic-reassessment.md`](templates/periodic-reassessment.md) — recurring governance report.

## Verification

Run the documented-command contract and the focused governance checks:

```sh
python3 -m unittest tests.test_documented_commands
python3 -m unittest tests.test_capability_registry tests.test_audit_capabilities tests.test_compile_runtime tests.test_install_runtime
```

The first test verifies that each documented repository reference resolves, the
commands are recognized, and the safety wording remains present.

## Scheduled maintenance

The versioned maintenance entry point is
`python3 scripts/stack-maintenance.py audit --observe-upstreams`. It audits the
declared providers and writes an owner-only receipt; audit mode never builds or
stages a proposal. The separate receipt-bound `prepare` flow generates and
validates one isolated, allowlisted proposal itself and may create or reuse the
canonical draft PR; externally authored manifests are rejected. Neither flow
merges, installs, publishes runtimes, repairs protected checkouts, or mutates
plugin state. See
[`docs/stack-maintenance.md`](docs/stack-maintenance.md) and the `stack-sync`
skill for the full unattended-run contract.

The separate weekly intelligence coordinator links private bookmark deltas,
design packets, retrieval, candidate evaluation, and the latest maintenance
receipt. Its future Saturday 09:00 scheduler contract is checked in but disabled;
enabling it requires separate approval and persisted run-now proof. The
coordinator never launches maintenance or publishes a capability.

## Security and privacy

Bookmark text and fetched pages are untrusted evidence, never instructions.
Raw bookmarks, fetched evidence, private repository metadata, private URLs,
titles, local paths, and proprietary payloads stay out of public Stack
artifacts. See [`docs/private-overlay.md`](docs/private-overlay.md) for the
local-only exception and its authorization boundary.
