# Third-party notices

Stack owns command mappings and package metadata, not the upstream skill implementations. No package manifest in `packages/` copies upstream code.

| Provider | Canonical source | Pin | License posture |
| --- | --- | --- | --- |
| Compound Engineering | EveryInc/compound-engineering-plugin | `1a7a4c1e844b55fe74f2aac79d9879cc136fbb5b` | MIT |
| GStack | garrytan/gstack | `7c9df1c568a9ea745508f679a329332b2c338063` | MIT |
| Matt Pocock skills | mattpocock/skills | `391a2701dd948f94f56a39f7533f8eea9a859c87` | MIT |
| David Ondrej skills | davidondrej/skills | `5c99080334072075eb9e0a17837f7d24e4f3e6ae` | MIT |
| Emil Kowalski skills | emilkowalski/skills | `c8a79627b59d72d764d6ab6f2c87c09a48169833` | MIT |
| Stewdio blank-page skill | StewdioAI/blank-page | `cd42b37fa7cd0a5550e51f45cc8f82f63377b98c` | MIT |

Stack-Codex is Stack-owned repository content, bundled under `packages/stack-codex/content` so a GitHub clone contains the complete eight-skill package. Its package pin, `483015638591618e884d4c21f1fa037b645bb872e33acf063fa7a5f802c80df3`, is a deterministic SHA-256 digest over sorted relative paths and exact file bytes. It is not an external upstream and does not appear in the third-party table above.

## Stageshow

The pinned integration in `skills/imported/benjitaylor/stageshow` imports
Benji Taylor's Stageshow 0.1.0 from `benjitaylor/skills` at
`802057409787133703c56001080169e347305572`. Its MIT license, upstream notices,
retained artwork licenses/source records and CC0 photograph attribution remain
with the import. The MIT license does not cover app-bundle artwork or grant
trademark rights. App-bundle icons and five official-only brand SVGs are omitted;
copied phone glyph paths are replaced with independently authored generic
geometry. `source.json` and `STACK-REVIEW.md` record the exact subset, modifications
and representative isolated runtime validation. Local compiler/installer receipts
record managed-runtime availability; dependencies are not bundled into exports.
