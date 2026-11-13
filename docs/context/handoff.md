# Handoff

Rewritten on every change; see `AGENTS.md`.

- Author: Claude
- Date: 2026-11-13

## Done

- [#55](https://github.com/thecolormaroun/stack/pull/55): retired 8
  David skills built for their author's setup, and made 10 David/Matt skills
  whose upstream copies were removed Stack-owned. The classifier no longer
  rewrites the stageshow manifest, so a rerun is a no-op.
- [#56](https://github.com/thecolormaroun/stack/pull/56), based on
  #55: wrote the admission rule (`docs/upstream-policy.md`), added
  `"tracking"` to every provider, made davidondrej/skills pick-only and its
  12 remaining skills Stack-owned, and added this shared context
  (`AGENTS.md`, the `CLAUDE.md` symlink, `docs/context/`).

## Next

1. Owner review and merge: #55, then #56. Both are drafts.
2. Reinstall from `main` after both merge, then run `scripts/stack-doctor.py`.
3. Confirm the weekly `stack-upstream-sync` task skips `pick-only` providers
   before Monday's run.
4. Decide on gstack and stewdio (they fail the admission rule but are still
   `weekly`), and on refreshing the impeccable and taste-skill copies.
