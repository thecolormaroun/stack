---
name: matt-research
description: Investigate a question against high-trust primary sources and capture the findings as a Markdown file in the repo. Use when the user wants a topic researched, docs or API facts gathered, or reading legwork delegated to a background agent.
---

## Stack Import

- Invoke this curated import as `$matt-research`.
- Upstream name: `research`.
- Upstream author: Matt Pocock.
- Exact upstream commit: `5b15a47f2d7150f545fbcacbfe381787fc0230dc`.
- Source metadata and license notice: [references/source.md](references/source.md).
- New skills, deletions, and license changes remain review-gated.

Spin up a **background agent** to do the research, so you keep working while it reads.

Its job:

1. Investigate the question against **primary sources** (official docs, source code, specs, first-party APIs), not a secondary write-up of them. Follow every claim back to the source that owns it.
2. Write the findings to a single Markdown file, citing each claim's source.
3. Save it where the repo already keeps such notes; match the existing convention, and if there is none, put it somewhere sensible and say where.
