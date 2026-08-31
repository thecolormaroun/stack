---
name: matt-implement
description: "Implement a piece of work based on a spec or set of tickets."
disable-model-invocation: true
---

## Stack Import

- Invoke this curated import as `$matt-implement`.
- Upstream name: `implement`.
- Upstream author: Matt Pocock.
- Exact upstream commit: `5b15a47f2d7150f545fbcacbfe381787fc0230dc`.
- Source metadata and license notice: [references/source.md](references/source.md).
- New skills, deletions, and license changes remain review-gated.

Implement the work described by the user in the spec or tickets.

Use /tdd where possible, at pre-agreed seams.

Run typechecking regularly, single test files regularly, and the full test suite once at the end.

Once done, use /code-review to review the work.

Commit your work to the current branch.
