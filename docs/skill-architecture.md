# Stack skill architecture

Stack is a runtime-neutral control plane for software work. Logical command IDs are authoritative; source paths and host syntax are adapters. A command first selects a family workflow, then delegates to a Stack-owned leaf or a pinned package export. It never copies an upstream workflow into a router.

## Current estate

The refactor began with 150 callable skills. Nine personal-operations and
knowledge-management workflows were integrated into their existing native
owners and removed from Stack. The remaining catalog contains 141 capabilities:
133 active capabilities and eight deprecated compatibility routes.

| Family | Capabilities |
| --- | ---: |
| Core | 5 |
| Product | 6 |
| Planning | 7 |
| Design | 18 |
| Engineering | 67 |
| Orchestration | 11 |
| Review | 5 |
| QA | 5 |
| Delivery | 2 |
| Knowledge | 8 |
| Platform | 7 |

Four duplicate implementations were collapsed behind canonical capabilities:
`cdo-deslop` → `deslop`, `cdo-rams` → `rams`, `cdo-react-doctor` →
`react-doctor`, and `taste-skill-suite-taste-skill` → `cdo-taste-skill`.
Four broad legacy entry points remain only as warning adapters:
`agent-operating-stack`, `departments`, `ideate`, and `mega-workflow`.

The nine workflows removed from Stack were Arc sidebar migration, online
shopping, GBrain/Zettelkasten operations, Gemini Zettelkasten recovery, local
finance, bookmark taxonomy, personal file organization, Vault migration
mapping, and Zettelkasten plan review. Their destination receipts are recorded
in `registry/migrations/2026-07-18-estate-refactor.json`; removal did not mean
discarding the workflows.

## Taxonomy

`registry/families.json` defines eleven stable families: core, product, planning, design, engineering, orchestration, review, QA, delivery, knowledge, and platform. `stack.explore` belongs to product, `stack.learn` belongs to knowledge, and `stack.run` belongs to core. A future capability has one primary family, optional supporting families, one artifact role, and one visibility tier. Provider provenance is independent: an imported Matt engineering leaf remains Matt-owned even when its functional family is engineering.

Roles are `router`, `workflow`, `leaf`, `adapter`, `reference-pack`, `package`, and `alias`. Visibility is `primary`, `extended`, `internal`, `compatibility`, `reference-only`, or `external`. Only primary commands enter the root command tree; extended and package-native commands remain direct routes. Compatibility routes warn with their canonical replacement. External and reference-only material never becomes an active command merely by being catalogued.

The physical layout is now `skills/core`, family folders under `skills/`,
imported provider folders under `skills/imported`, and external package
declarations under `packages/`. No callable capability lives directly under
`skills/`. Stable logical IDs keep command identity independent from source
location.

## Commands and routing

`registry/commands.json` contains exactly the twelve primary logical routes: `stack`, `stack.explore`, `stack.plan`, `stack.design`, `stack.build`, `stack.orchestrate`, `stack.review`, `stack.qa`, `stack.ship`, `stack.learn`, `stack.maintain`, and `stack.run`.

Routing precedence is canonical ID, explicit alias, intent, then context. A package-health failure makes its route unavailable and preserves last-known-good metadata; it never silently substitutes a different implementation. Materially competing routes ask with candidates. For example, a generic review request with both code and visual artifacts must offer `stack.review` and `stack.design`, not guess.

Direct Compound Engineering, GStack, and Stack-Codex invocations are declared package-native aliases. They remain extended routes and emit a canonical-target warning; they do not create a second command tree.

## Package health and provenance

`registry/upstreams.json` allows only canonical HTTPS sources and immutable commit or digest pins. `upstreams.lock.json` repeats those exact pins for deterministic audit. `scripts/sync-upstreams.py` is a fail-closed preflight: it validates metadata and, when given an acquired checkout, validates both origin and exact commit before any extraction or staging caller may continue. It performs no download, extraction, staging, or runtime publication itself.

Each provider declares exports, Stack adapters, compatibility evidence, license posture, and last-known-good metadata. `THIRD_PARTY_NOTICES.md` attributes copied or adapted material without claiming Stack ownership of upstream work. Matt, David, and design imports remain provider-namespaced and are not promoted to primary routes just because they are retained.

Stack-Codex is the repository-local exception to the external-package rule. Stack owns and bundles its complete eight-skill plugin surface under `packages/stack-codex/content`, identifies this Stack repository as its canonical source, and pins the sorted package content with SHA-256. The current clean-home bundle pin is `483015638591618e884d4c21f1fa037b645bb872e33acf063fa7a5f802c80df3`. The same fail-closed preflight verifies that digest before a caller may stage the bundle.
