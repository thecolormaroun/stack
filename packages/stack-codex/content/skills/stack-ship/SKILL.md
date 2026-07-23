---
name: stack-ship
description: |
  Finalize, validate, and publish work using the official gstack ship flow plus
  compound-engineering release hygiene where it helps. Use when the user wants
  the work pushed, PR'd, or prepared for merge.
---

# stack-ship

## Read these upstream guides first

- `../../references/upstreams.md`
- Installed GStack `ship`, when available.
- Installed Compound Engineering `ce-commit-push-pr`, `ce-test-browser`, and
  `ce-demo-reel`, when available.

If those exports are unavailable, use the repository's native test, Git, and
pull-request workflow. External mutation still requires the user's approval;
report which package-specific helpers were unavailable.

## Workflow

1. Verify the branch is actually ready:
   - tests relevant to the change
   - review findings addressed
   - changelog/version expectations handled if the repo uses them
2. Use the gstack ship flow for commit, push, and PR mechanics when available.
3. If the change is UI-facing, run browser verification before you call it ready.
4. If the user wants demo artifacts, add them after the code and review are already clean.

## Rule

Do not skip the review or validation stage just because the user said "ship it". The point of the ship flow is fast confidence, not blind optimism.
