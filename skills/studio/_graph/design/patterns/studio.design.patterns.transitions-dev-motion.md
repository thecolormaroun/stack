---
id: studio.design.patterns.transitions-dev-motion
name: Transitions.dev Motion Patterns
description: Concrete CSS/React transition recipes for common app UI state changes.
when_to_use:
  - when implementing a specific app transition
  - when choosing motion for dropdowns, modals, tabs, badges, panels, loaders, or text swaps
  - when motion should stay dependency-free
---

# Transitions.dev Motion Patterns

Use this node when the design direction is already clear and the question is
which exact app transition to implement.

Primary source: `skills/ui-skills/transitions-dev-motion/SKILL.md`

## Load
- `skills/ui-skills/transitions-dev-motion/references/motion-catalog.md` to choose a pattern.
- `skills/ui-skills/transitions-dev-motion/references/source.json` to check source, commit, license, and dependency metadata.
- `skills/ui-skills/transitions-dev-motion/scripts/extract-transitions-dev.mjs --out-dir <dir>` when exact source-backed CSS/React snippets are needed.

## Fit
- Dropdowns, modals, panels, tooltips, tabs, badges, text swaps, icon swaps, counters, skeleton reveals, success checks, and shimmer labels.
- Dependency-free CSS plus small JS orchestration.
- Reduced-motion guarded implementations.

## Rules
- Install only the chosen pattern, not the whole library.
- Preserve explicit transition properties; do not collapse to `transition: all`.
- Prefer the lower-overhead pattern when two fit.
- Keep attribution because the upstream repository currently reports no explicit license.

## Related
- [[studio.design.patterns.motion-design-patterns]]
- [[studio.design.system.motion-tokens]]
