---
name: david-prompt-me
description: 'Namespaced import of David Ondrej agent skills: Prompt the user with
  pointed questions to extract what is in his head about a project — remaining work,
  what is being avoided, what really matters, what does not. Use when the user says
  "prompt me", "ask me questions", or wants the agent to figure out priorities by
  questioning him.. Use via $david-prompt-me when this upstream workflow is needed
  inside Maroun''s Stack or Hermes-safe operating loop.'
---
## Stack Import

- Invoke this imported skill as `$david-prompt-me`.
- Upstream name: `prompt-me`.
- Source metadata and license notice: [references/source.md](references/source.md).
- For broad routing, Hermes/Mookie safety boundaries, or verification choice, start with `$agent-operating-stack` and then use this skill as the focused workflow.


# prompt-me

DRAFT — being refined with the user.

Core idea: the agent interviews the user to extract priorities, avoided work, and importance from his head.

Example trigger:

> start prompting me questions to figure out what other work needs to be done on this project, and what we are avoiding, and what really has importance, and what doesn't have importance
