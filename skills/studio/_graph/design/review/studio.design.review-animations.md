---
id: studio.design.review-animations
name: Review Animations
description: Aggressive animation and motion-code review derived from Emil Kowalski's animation philosophy. Use when the job is to judge whether motion should ship.
skill_path: ~/.claude/stack/skills/review-animations/SKILL.md
standards_path: ~/.claude/stack/skills/review-animations/references/STANDARDS.md
source: github.com/emilkowalski/skill
version: "1.0.0"
triggers:
  - "review animation code"
  - "motion review"
  - "animation PR review"
  - "check easing and duration"
depends_on:
  - "CSS, animation, transition, or motion implementation exists"
complements:
  - "[[studio.design.emil-design-eng]] — broader animation philosophy and component polish"
  - "[[studio.design.userinterface-wiki]] — broad UI implementation rule catalog"
  - "[[studio.design.patterns.transitions-dev-motion]] — concrete transition snippets when a fix needs a pattern"
---

# Review Animations

Use this node when reviewing whether an animation should ship. It is narrower and sharper than the broad UI graph: purpose, frequency, easing, duration, origin, interruptibility, GPU performance, reduced motion, hover gating, and cohesion.

## Load

- Skill: `skills/review-animations/SKILL.md`
- Standards: `skills/review-animations/references/STANDARDS.md`
- Source metadata: `skills/review-animations/references/source.json`

## Routing

| Situation | Use |
|-----------|-----|
| PR contains animation, transition, motion, spring, keyframe, or gesture code | `review-animations` |
| Need broader design-engineering judgment or implementation taste | `emil-design-eng` |
| Need a concrete CSS/React motion pattern | `transitions-dev-motion` |
| Need broad UI/UX rule coverage beyond motion | `userinterface-wiki` |

## Output Expectation

Return the skill's required table:

| Before | After | Why |
| --- | --- | --- |

Then close with a clear **Block** or **Approve** verdict.
