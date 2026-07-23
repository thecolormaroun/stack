# Stack estate decision packet

Status: **all recommendations approved by Maroun on 2026-07-19**. The approval
is recorded in `capability-review-receipt.json` and is scoped to disposition
review only. Nothing in this packet has moved, merged, activated, installed,
published, or scheduled.

The corrected audit classifies from capability names/frontmatter rather than
incidental safety text. It covers 145 capabilities: 122 unchanged keep
proposals, 9 proposed moves, 8 overlap decisions, and 6 orchestration/router
holds. The 23 item-level decisions are split across two machine-readable packets
of at most 20 decisions each:

- `capability-review-packet-1.json`: 20 decisions
- `capability-review-packet-2.json`: 3 decisions

## Recommended decisions

These recommendations are now reviewed decisions, not applied state. Moves
still require a real destination and consumer receipt; merges still require a
verified compatibility alias, provenance transfer, and consumer receipt before
the source migration can become apply-approved.

### Move out of Stack

| Capability | Recommendation | Proposed destination | Rationale |
|---|---|---|---|
| `arc-sidebar-guarded-migration` | `move` | Personal-operations / Codex automation layer | Private browser-profile maintenance, not software design/build. |
| `david-online-shopping` | `move` | Hermes personal-operations skills | Purchasing research is explicitly outside Stack's identity. |
| `gbrain-zk-operating-system` | `move` | Hermes/GBrain operating layer | Operates the personal knowledge substrate rather than building software. |
| `gemini-zk-orchestrator` | `move` | Zettelkasten/Hermes operating layer | ZK production and quota operations are domain-specific personal knowledge work. |
| `local-finance-interface` | `move` | Zouzou/local-finance project capabilities | Valuable product work, but tied to private household finance. |
| `mookie-bookmark-taxonomy` | `move` | Hermes/GBrain operating layer | Produces Mookie graph taxonomy rather than Stack design/build capabilities. |
| `personal-file-organization-review` | `move` | Personal-operations capability set | Personal storage and backup governance is out of scope. |
| `vault-migration-consumer-map` | `move` | Zettelkasten/Hermes operating layer | Obsidian/Vault source migration is knowledge-system operations. |
| `zettelkasten-plan-review-gate` | `move` | Zettelkasten/Hermes operating layer | Reviews personal knowledge-system migrations, not product delivery. |

### Resolve overlap pairs

| Capability | Recommendation | Canonical target / reason |
|---|---|---|
| `cdo-deslop` | `merge` | Merge into top-level `deslop`; the files are byte-identical and Codex currently consumes the top-level path. |
| `deslop` | `keep` | Canonical installed entrypoint. |
| `cdo-react-doctor` | `merge` | Merge into top-level `react-doctor`; the files are byte-identical and Codex currently consumes the top-level path. |
| `react-doctor` | `keep` | Canonical installed entrypoint. |
| `cdo-rams` | `merge` | Merge useful self-contained checks/provenance into top-level `rams`, which owns the supporting checklist/reference files and is the current Codex consumer path. |
| `rams` | `keep` | Canonical entrypoint with owned evaluation and instruction artifacts. |
| `cdo-taste-skill` | `keep` | More complete version and the path currently consumed by Codex. |
| `taste-skill-suite-taste-skill` | `merge` | Merge provenance into `cdo-taste-skill`; the suite version is a shorter overlapping variant. |

### Review orchestration/support holds

| Capability | Recommendation | Supported design/build workflow |
|---|---|---|
| `agent-operating-stack` | `keep` | Routes design/build requests into planning, implementation, review, and verification. |
| `david-pi-custom-model` | `keep` | Supports model selection for bounded software-building work. |
| `david-run-deep-swe` | `keep` | Directly orchestrates software-engineering execution. |
| `illo` | `keep` | Routes asset generation in service of interface/product design. |
| `matt-ask-matt` | `keep` | Routes software architecture and TypeScript implementation guidance. |
| `menu` | `keep` | Routes Studio product, research, design, and shipping workflows. |

## Important corrections from the first draft

`agent-verification-ladder`, `field-theory-bookmark-synthesis`, and
`gemini-review` are now ordinary keep proposals. They were false positives in
the first audit because their safety sections mentioned out-of-scope domains;
their actual identities directly support verification, design/build inspiration
curation, and code review.

Maroun's `Approve all` decision has filled the reviewed migration map. It does
**not** authorize source moves, runtime publication, private-overlay activation,
or live scheduling. Each later action retains its own verification and approval
gate.
