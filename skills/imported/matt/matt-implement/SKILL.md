---
name: matt-implement
description: 'Namespaced import of Matt Pocock engineering/productivity skills: Implement
  a piece of work based on a spec or set of tickets.. Use via $matt-implement when
  this upstream workflow is needed inside Maroun''s Stack or Hermes-safe operating
  loop.'
disable-model-invocation: true
---
## Stack Import

- Invoke this imported skill as `$matt-implement`.
- Upstream name: `implement`.
- Source metadata and license notice: [references/source.md](references/source.md).
- For broad routing, Hermes/Mookie safety boundaries, or verification choice, start with `$agent-operating-stack` and then use this skill as the focused workflow.


Implement the work described by the user in the spec or tickets.

Use $matt-tdd where possible, at pre-agreed seams.

Run typechecking regularly, single test files regularly, and the full test suite once at the end.

Once done, use $matt-code-review to review the work.

Commit your work to the current branch.
