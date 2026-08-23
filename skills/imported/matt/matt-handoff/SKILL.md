---
name: matt-handoff
description: Compact the current conversation into a handoff document for another agent to pick up.
argument-hint: "What will the next session be used for?"
disable-model-invocation: true
---

## Stack Import

- Invoke this curated import as `$matt-handoff`.
- Upstream name: `handoff`.
- Upstream author: Matt Pocock.
- Exact upstream commit: `5b15a47f2d7150f545fbcacbfe381787fc0230dc`.
- Source metadata and license notice: [references/source.md](references/source.md).
- New skills, deletions, and license changes remain review-gated.

Write a handoff document summarising the current conversation so a fresh agent can continue the work. Save to the temporary directory of the user's OS - not the current workspace.

Include a "suggested skills" section in the document, naming which skills the next agent should call the Skill tool for.

Do not duplicate content already captured in other artifacts (specs, plans, ADRs, issues, commits, diffs). Reference them by path or URL instead.

Redact any sensitive information, such as API keys, passwords, or personally identifiable information.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.
