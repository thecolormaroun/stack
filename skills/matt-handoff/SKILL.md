---
name: matt-handoff
description: 'Namespaced import of Matt Pocock engineering/productivity skills: Compact
  the current conversation into a handoff document for another agent to pick up..
  Use via $matt-handoff when this upstream workflow is needed inside Maroun''s Stack
  or Hermes-safe operating loop.'
argument-hint: What will the next session be used for?
disable-model-invocation: true
---
## Stack Import

- Invoke this imported skill as `$matt-handoff`.
- Upstream name: `handoff`.
- Source metadata and license notice: [references/source.md](references/source.md).
- For broad routing, Hermes/Mookie safety boundaries, or verification choice, start with `$agent-operating-stack` and then use this skill as the focused workflow.


Write a handoff document summarising the current conversation so a fresh agent can continue the work. Save to the temporary directory of the user's OS - not the current workspace.

Include a "suggested skills" section in the document, which suggests skills that the agent should invoke.

Do not duplicate content already captured in other artifacts (specs, plans, ADRs, issues, commits, diffs). Reference them by path or URL instead.

Redact any sensitive information, such as API keys, passwords, or personally identifiable information.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.
