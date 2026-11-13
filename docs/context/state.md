# Stack state

Rewritten on every change; see `AGENTS.md`. Last updated 2026-11-13 by Claude
in [#56](https://github.com/thecolormaroun/stack/pull/56).

## Main

- `origin/main` is `73136f9`, "Preserve approved imports during upstream
  maintenance (#51)".
- On `main`, 29 David and 22 Matt skills still sit under `skills/imported/`.
  #55 and #56 change that: no David skill stays tracked, and
  davidondrej/skills becomes pick-only.

## Installed

- Claude `stack@skills-dir` and Codex `~/.codex/skills/stack` were published
  from `73136f9` at 2026-11-13 17:35 UTC.
- Neither #55 nor #56 is installed. Reinstall from `main` after both
  merge.

## Open pull requests

| PR | What | State |
| --- | --- | --- |
| [#55](https://github.com/thecolormaroun/stack/pull/55) | Retire 8 David skills; make 10 David/Matt skills Stack-owned | draft |
| [#56](https://github.com/thecolormaroun/stack/pull/56) | Admission rule, David pick-only, shared agent context; based on #55 | draft |
| [#54](https://github.com/thecolormaroun/stack/pull/54) | Import Emil's gestures and learn-taste skills | draft |
| [#48](https://github.com/thecolormaroun/stack/pull/48) | Stack critique and review, 2026-11-06 | draft |
| [#43](https://github.com/thecolormaroun/stack/pull/43) | Weekly knowledge intake and evidence | open since 2026-10-03 |
| [#23](https://github.com/thecolormaroun/stack/pull/23) | Sol High as the default Codex orchestrator | open since 2026-08-16 |

A separate session is pinning ibelick/ui-skills as provider `ibelick`. Its row
in `registry/upstreams.json` needs `"tracking": "weekly"` (it passes the
admission rule).

## Blockers

- **Monday weekly maintenance** (`stack-upstream-sync`, 8am): davidondrej/skills
  flattened every skill path on 2026-11-09, so the David lane fails until
  #56 merges. #55 alone does not unblock it.
- The scheduled task must skip `pick-only` providers. A separate session owns
  that change.
- Merge #55 before #56. If #54 or the ibelick change lands first,
  rebase and regenerate the generated files; never hand-edit them.

## Open owner decisions

From the 2026-11-13 audit in `docs/upstream-policy.md`:

- gstack and stewdio fail the admission rule but are still `weekly`.
- The impeccable and taste-skill copies no longer match upstream, which merged
  them into single skills.
