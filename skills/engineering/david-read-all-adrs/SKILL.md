---
name: david-read-all-adrs
description: 'Stack-owned, adapted from David Ondrej agent skills: Read every ADR markdown
  file in the project''s docs/adr/ folder so you have full context on past decisions.
  Use only when the user explicitly calls it.. Use via $david-read-all-adrs when this workflow is needed inside Maroun''s Stack or Hermes-safe operating loop.'
disable-model-invocation: true
---
## Stack-owned

- Invoke this skill as `$david-read-all-adrs`.
- Adapted from David Ondrej's `read-all-adrs` skill (MIT). Stack owns this copy and no longer tracks upstream.
- Origin and license notice: [references/source.md](references/source.md).
- For broad routing, Hermes/Mookie safety boundaries, or verification choice, start with `$agent-operating-stack` and then use this skill as the focused workflow.

Read EVERY single ADR `.md` file in this project's `docs/adr/` folder, start to
finish.

Do not skim, sample, or summarize from filenames. Read every ADR file for this
project in full before relying on ADR context.
