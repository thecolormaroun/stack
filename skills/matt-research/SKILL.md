---
name: matt-research
description: 'Namespaced import of Matt Pocock engineering/productivity skills: Investigate
  a question against high-trust primary sources and capture the findings as a Markdown
  file in the repo. Use when the user wants a topic researched, docs or API facts
  gathered, or reading legwork delegated to a background agent.. Use via $matt-research
  when this upstream workflow is needed inside Maroun''s Stack or Hermes-safe operating
  loop.'
---
## Stack Import

- Invoke this imported skill as `$matt-research`.
- Upstream name: `research`.
- Source metadata and license notice: [references/source.md](references/source.md).
- For broad routing, Hermes/Mookie safety boundaries, or verification choice, start with `$agent-operating-stack` and then use this skill as the focused workflow.


Spin up a **background agent** to do the research, so you keep working while it reads.

Its job:

1. Investigate the question against **primary sources** — official docs, source code, specs, first-party APIs — not a secondary write-up of them. Follow every claim back to the source that owns it.
2. Write the findings to a single Markdown file, citing each claim's source.
3. Save it where the repo already keeps such notes; match the existing convention, and if there is none, put it somewhere sensible and say where.
