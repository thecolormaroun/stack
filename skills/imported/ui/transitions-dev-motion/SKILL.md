---
name: transitions-dev-motion
description: Production-ready motion patterns from Transitions.dev for web app UI. Use when implementing or reviewing dropdowns, modals, panel reveals, page transitions, card resizes, number pop-ins, text swaps, icon swaps, success checks, avatar hovers, error shakes, input clear dissolves, skeleton reveals, shimmer text, sliding tabs, tooltips, or staggered text reveals.
license: Source wrapper for https://transitions.dev; upstream GitHub repo currently has no explicit license.
metadata:
  source: https://github.com/Jakubantalik/transitions.dev
  source_site: https://transitions.dev
  upstream_skill: skills/transitions-dev
---

# Transitions.dev Motion

Use this skill to add tasteful, production-ready web app transitions without
inventing timing values from scratch.

The upstream project publishes an installable agent skill at
`Jakubantalik/transitions.dev/skills/transitions-dev`. This Stack skill is the
source-of-truth wrapper for Maroun's design library: it records source metadata,
the catalog, selection rules, update checks, dependency checks, and an extractor
that can pull the full upstream CSS and React snippets when exact code is needed.

## Source Boundary

- Upstream site: https://transitions.dev
- Upstream repo: https://github.com/Jakubantalik/transitions.dev
- Upstream skill path: `skills/transitions-dev`
- Upstream package dependencies: none as of 2026-06-13; build uses Node only.
- Upstream GitHub license: none reported as of 2026-06-13.
- Stack source metadata: [references/source.json](references/source.json).

Because the upstream repo has no explicit license, do not paste a wholesale copy
of all upstream reference files into public repos. For exact snippets, run the
extractor locally and preserve source attribution in generated artifacts.

## How To Use

1. Read [references/motion-catalog.md](references/motion-catalog.md).
2. Pick one transition that matches the UI object and state change.
3. If exact code is needed, run:

```bash
node skills/ui-skills/transitions-dev-motion/scripts/extract-transitions-dev.mjs --format markdown
```

4. Paste only the chosen transition's variables, CSS, DOM hooks, and JS
   orchestration. Keep the `prefers-reduced-motion` guard.

To produce a full local reference pack, run:

```bash
node skills/ui-skills/transitions-dev-motion/scripts/extract-transitions-dev.mjs --out-dir /tmp/transitions-dev-motion
```

That writes `_root.css`, `source.json`, `motion-tokens.md`, and one markdown file
per transition.

## Commands

### `transitions reveal`

List the eighteen available transitions, with when-to-use guidance and source
reference names.

### `transitions extract`

Run the extractor and return the full source-backed catalog. Prefer JSON when a
tool will consume it:

```bash
node skills/ui-skills/transitions-dev-motion/scripts/extract-transitions-dev.mjs --format json
```

Use markdown when a human or agent needs to inspect snippets:

```bash
node skills/ui-skills/transitions-dev-motion/scripts/extract-transitions-dev.mjs --format markdown
```

Use `--out-dir` when full extraction is needed as files:

```bash
node skills/ui-skills/transitions-dev-motion/scripts/extract-transitions-dev.mjs --out-dir /tmp/transitions-dev-motion
```

### `transitions check-upstream`

Check the latest upstream commit, package dependencies, and license metadata:

```bash
node skills/ui-skills/transitions-dev-motion/scripts/extract-transitions-dev.mjs --check
```

### `transitions apply`

When applying a transition to a project:

1. Identify the closest match from the catalog.
2. Extract the exact upstream snippet if needed.
3. Install only the chosen transition. Do not install all eighteen unless the
   project is building a reusable motion library.
4. Use existing framework conventions. Do not add Framer Motion, GSAP, Motion
   One, or any other dependency just for these snippets.
5. Preserve reduced-motion behavior.

## Selection Rules

- Dense operational tools: prefer text state swaps, sliding tabs, skeleton
  reveal, dropdown, tooltip, and small panel reveal.
- Product/marketing surfaces: success check, text reveal, page side-by-side, and
  shimmer can be appropriate, but keep one focal motion per viewport.
- Interruptible UI uses transitions or springs; avoid keyframes for rapidly
  toggled state.
- Name exact transition properties. Never use `transition: all`.
- Use exits faster than entries for overlays, dropdowns, modals, and tooltips.
- Keep blur short and small. Never animate blur continuously or on large
  surfaces.

## Dependencies

The upstream snippets are CSS and small vanilla JavaScript orchestration. They
do not require a package dependency. The extractor requires Node 18+ for global
`fetch` and built-in `node:vm`.

If a project already uses React, the extractor can return React examples from
the upstream page. If a project does not use React, use the CSS and DOM-hook
guidance instead.
