---
name: david-short
description: 'Namespaced import of David Ondrej agent skills: Manually-invoked skill
  that forces the agent to compress its current answer — strip filler, simplify wording,
  and cut length while keeping the substance. Use when the user says "short", "shorter",
  "simpler", "too long", "tl;dr", or wants a more concise version of the previous
  response.. Use via $david-short when this upstream workflow is needed inside Maroun''s
  Stack or Hermes-safe operating loop.'
disable-model-invocation: true
---
## Stack Import

- Invoke this imported skill as `$david-short`.
- Upstream name: `short`.
- Source metadata and license notice: [references/source.md](references/source.md).
- For broad routing, Hermes/Mookie safety boundaries, or verification choice, start with `$agent-operating-stack` and then use this skill as the focused workflow.


rewrite your last response to be simpler & shorter. do not do anything else.
