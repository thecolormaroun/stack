---
id: studio.design.userinterface-wiki
name: User Interface Wiki
description: Comprehensive UI/UX rules audit — 152 rules across 12 categories. Use for code review, implementation guidance, and quality gates.
skill_path: ~/.claude/skills/userinterface-wiki/SKILL.md
rules_path: ~/.claude/skills/userinterface-wiki/rules/
source: github.com/raphaelsalaja/userinterface-wiki
version: "3.0.0"
triggers:
  - "/ui-audit — full 152-rule review"
  - "/animation-review — animation principles, timing, exit animations"
  - "/ux-laws — cognitive psychology rules (Fitts's, Hick's, Miller's, etc.)"
  - "/typography-review — OpenType, text-wrap, font rendering"
  - "/prefetch-review — predictive loading patterns"
depends_on:
  - "component implementation exists"
  - "CSS/animation code to review"
complements:
  - "[[studio.design.emil-design-eng]] — Emil's skill covers animation philosophy; this covers implementation rules"
  - "[[studio.design.review-animations]] — sharper animation-only review for motion PRs"
  - "[[studio.design.checklist.visual-qa]] — visual QA is manual; this is rule-based automated review"
---

# User Interface Wiki

152 rules across 12 categories for automated UI/UX code review.

## When to Use

| Scenario | Use This |
|----------|----------|
| Reviewing animation implementation | Load rules: `timing-*`, `physics-*`, `spring-*`, `easing-*` |
| Exit animation issues | Load rules: `exit-*`, `presence-*`, `mode-*`, `nested-*` |
| CSS pseudo-element work | Load rules: `pseudo-*`, `transition-*`, `native-*` |
| Adding sound/audio feedback | Load rules: `a11y-*`, `appropriate-*`, `impl-*`, `weight-*` |
| Morphing icon components | Load rules: `morphing-*` |
| Container width/height animations | Load rules: `container-*` |
| UX pattern review | Load rules: `ux-*` (Fitts's, Hick's, Miller's, etc.) |
| Prefetching implementation | Load rules: `prefetch-*` |
| Typography audit | Load rules: `type-*` |
| Visual polish (shadows, spacing) | Load rules: `visual-*` |

## Priority Order

1. **CRITICAL** — Animation Principles (`timing-`, `physics-`, `staging-`)
2. **HIGH** — Timing Functions, Exit Animations, UX Laws, Visual Design
3. **MEDIUM** — CSS Pseudo, Audio, Sound, Container, Prefetch, Typography
4. **LOW** — Morphing Icons

## Integration with Studio Pipeline

- **Pre-commit**: Run `/ui-audit` on changed components
- **PR review**: Load relevant rule categories based on diff
- **Design QA**: Combine with `visual-qa-loop` for comprehensive review

## Rule File Format

Each rule in `rules/` follows:
```markdown
---
id: rule-id
category: category-name
priority: CRITICAL|HIGH|MEDIUM|LOW
---

# Rule Title

**Why:** Explanation of the principle

**Example (bad):**
```tsx
// problematic code
```

**Example (good):**
```tsx
// correct implementation
```
```
