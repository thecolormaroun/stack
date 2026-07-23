# CDO Skill Routing Guide

Use this decision tree when working on any design/UI task:

```
NEW PROJECT or NEW FEATURE?
│
├─ YES → Step 1: Run UI/UX Pro Max design system generator
│         `python3 skills/cdo/ui-ux-pro-max/scripts/design_system.py "description"`
│         → Outputs: style, colors, typography, layout pattern, anti-patterns
│
├─ Step 2: Need visual direction / brand mood?
│   └─ YES → Load visual-direction/SKILL.md
│             → Outputs: mood board direction, color rationale, brand personality
│
├─ Step 3: Need type scale or font decisions?
│   └─ YES → Load typography/SKILL.md (or use Pro Max font pairing output)
│
├─ Step 4: Need grid/layout/responsive strategy?
│   └─ YES → Load layout-strategy/SKILL.md
│
├─ Step 5: Need component specs or design tokens?
│   └─ YES → Load design-system/SKILL.md
│
├─ Step 6: Need user flows or accessibility audit?
│   └─ YES → Load ux-patterns/SKILL.md
│
├─ Step 7: WRITING CODE? (any UI implementation)
│   └─ ALWAYS:
│       ├─ Load taste-skill/SKILL.md (premium code quality, kills AI slop)
│       ├─ Load deslop/SKILL.md (remove AI-generated slop after code generation)
│       ├─ Load simplify/SKILL.md (refactor for clarity without changing behavior)
│       └─ Tune dials: DESIGN_VARIANCE / MOTION_INTENSITY / VISUAL_DENSITY
│
└─ Step 8: SHIPPING UI?
    └─ MANDATORY QA GATES:
        ├─ Load rams/SKILL.md (WCAG accessibility + visual design review)
        ├─ Load react-doctor/SKILL.md (if React: `npx react-doctor . --verbose`)
        └─ Both must PASS before code ships
```

## Quick Reference Table

| Phase | Skill | What it does |
|-------|-------|-------------|
| **Kickoff** | UI/UX Pro Max | Generates design system (colors, fonts, style, patterns) |
| **Direction** | Visual Direction | Brand mood, aesthetic foundation, inspiration |
| **Structure** | Layout Strategy | Grid, spacing, responsive behavior |
| **System** | Design System | Tokens, component specs, cross-platform consistency |
| **Flows** | UX Patterns | User journeys, accessibility, interaction patterns |
| **Implementation** | Taste Skill | Code quality enforcement, anti-slop, motion, performance |

## Rules

- UI/UX Pro Max and Taste Skill should BOTH be active on any greenfield UI project
- Taste Skill is mandatory for ALL frontend code generation — no exceptions
- Pro Max is optional for existing projects (design system already defined)

## Post-Build Quality Pipeline

Run after EVERY code generation:

1. **DESLOP** — Remove AI slop: unnecessary comments, defensive checks, `any` casts
2. **SIMPLIFY** — Reduce nesting, improve naming, consolidate logic
3. **RAMS** — WCAG 2.1 audit, color contrast, focus states, touch targets
4. **REACT DOCTOR** — `npx react-doctor@latest . --verbose` (47+ rules, 0-100 score)
5. **KNIP** — `npx knip` for unused files, exports, dependencies
6. **FAVICON** — For new projects: generate complete favicon set

**Quality gate:** "Would a staff engineer approve this?" — if not, iterate.
