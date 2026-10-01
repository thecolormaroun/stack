---
name: david-short
description: Manually-invoked skill that forces the agent to compress its current answer — strip filler, simplify wording, and cut length while keeping the substance. Use when the user says "short", "shorter", "simpler", "too long", "tl;dr", or wants a more concise version of the previous response.
disable-model-invocation: true
---

## Stack Import

- Invoke this curated import as `$david-short`.
- Upstream name: `short`.
- Upstream author: David Ondrej.
- Exact upstream commit: `69c3ae5228eb146724fd23dac3d43eab5805bcc3`.
- Source metadata and license notice: [references/source.md](references/source.md).
- New skills, deletions, and license changes remain review-gated.

rewrite your last response to be simpler & shorter. do not do anything else.
