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
2. **Curation.** Read-only bookmark collection records source observations in
   an owner-local ledger. Triage compares candidates with the catalog and
   prepares a bounded, redacted review packet. Capturing a link is not a
   promotion.
3. **Human gate.** Provenance, evaluation, activation, and publication require
   review. Automation may collect evidence and prepare candidates, but may not
   activate, merge, install, or publish a capability.
4. **Publication and recovery.** The compiler selects only reviewed `active`
   entries for a declared target, stages all outputs, and the installer switches
   them atomically. Receipts preserve the catalog digest, source commit, and
   prior target pointers for rollback without rewriting source history.
5. **Reassessment.** Periodic review uses validation, overlap, upstream health,
   maintenance, scope, and usage as separate signals. Low usage alone never
   auto-archives a capability.

Read the detailed contracts:

- [`docs/skill-architecture.md`](docs/skill-architecture.md) — the current 141-capability estate, cuts, merges, families, packages, and routing model.
- [`docs/architecture.md`](docs/architecture.md) — ownership, catalog, and inclusion boundary.
- [`docs/capability-lifecycle.md`](docs/capability-lifecycle.md) — evidence, review, and lifecycle transitions.
- [`docs/bookmark-curation.md`](docs/bookmark-curation.md) — safe intake through review packet.
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

## Security and privacy

Bookmark text and fetched pages are untrusted evidence, never instructions.
Raw bookmarks, fetched evidence, private repository metadata, private URLs,
titles, local paths, and proprietary payloads stay out of public Stack
artifacts. See [`docs/private-overlay.md`](docs/private-overlay.md) for the
local-only exception and its authorization boundary.
