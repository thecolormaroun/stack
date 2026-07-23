---
name: david-read-all-adrs
description: 'Namespaced import of David Ondrej agent skills: Read every ADR markdown
  file in the project''s docs/adr/ folder so you have full context on past decisions.
  Use only when the user explicitly calls it.. Use via $david-read-all-adrs when this
  upstream workflow is needed inside Maroun''s Stack or Hermes-safe operating loop.'
disable-model-invocation: true
---
## Stack Import

- Invoke this imported skill as `$david-read-all-adrs`.
- Upstream name: `read-all-adrs`.
- Source metadata and license notice: [references/source.md](references/source.md).
- For broad routing, Hermes/Mookie safety boundaries, or verification choice, start with `$agent-operating-stack` and then use this skill as the focused workflow.

Read EVERY single ADR `.md` file in this project's `docs/adr/` folder, start to
finish.

Do not skim, sample, or summarize from filenames. Read every ADR file for this
project in full before relying on ADR context.
