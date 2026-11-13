# Decisions

Append only; see `AGENTS.md`. One line per decision: date, decision, pull
request. To reverse a decision, add a new line.

- 2026-11-06: Publish the Claude runtime as the `stack@skills-dir` plugin, so skills load as `stack:<name>`. [#46](https://github.com/thecolormaroun/stack/pull/46)
- 2026-11-10: Drop Twombly from micro-branch because it is a paid third-party product; the local board is the only canvas. [#52](https://github.com/thecolormaroun/stack/pull/52)
- 2026-11-13: Make davidondrej/skills pick-only; its remaining tracked skills become Stack-owned at their last inspected commit. [#56](https://github.com/thecolormaroun/stack/pull/56)
- 2026-11-13: Adopt the upstream admission rule in `docs/upstream-policy.md`: weekly tracking needs an OSI license file, publication for other users, no silent deletions or versioned releases, and general-purpose skills. [#56](https://github.com/thecolormaroun/stack/pull/56)
