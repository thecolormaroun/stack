---
id: design.moc
description: (no description)
name: Design (MOC)
description: Entry point for Studio design knowledge (patterns, heuristics, checklists, templates).
inputs:
  - design_brief: "Product brief or PRD from product.moc or CPO skill"
  - taste_profile: "Maroun's curated taste profile from research.moc/tastemining"
  - user_request: "Direct design request (/design, /typography, /layout, etc.)"
outputs:
  - design_spec: "Component specs, interaction patterns, spacing/color decisions"
  - design_tokens: "Token pack (colors, typography, spacing, motion)"
  - design_brief_md: "Written design brief for complex work"
triggers:
  - "/design — full CDO orchestration"
  - "/typography — font pairing, type scale"
  - "/layout — grid, spacing, responsive"
  - "/designsystem — tokens, components"
  - "/ux — user flows, patterns, accessibility"
  - "/assets — AI-generated visuals"
  - "/copy — write or review UI copy"
  - "/microcopy — pattern-match to a UI surface"
  - "/copy-qa — run the copy QA checklist"
depends_on:
  - "[[product.moc]] — needs product brief before designing"
  - "[[research.moc]] tastemining — pulls Maroun's taste profile"
feeds_into:
  - "[[ship.moc]] — design spec becomes implementation input"
  - "coding-agent skill — component specs guide implementation"
---

# Design — MOC

Entry point for design work. Load sub-nodes progressively — don't load everything at once.

## When to use which sub-domain

| Task | Load this |
|------|-----------|
| Visual brand direction, colors, mood | [[studio.design.system.creative-direction]] → [[studio.design.system.design-tokens]] |
| Font choices, type scale | [[studio.design.typography.moc]] |
| Grid, spacing, responsive rules | [[studio.design.layout.moc]] |
| Component library, tokens | [[studio.design.designsystem.moc]] |
| Images, icons, OG images | [[studio.design.assets.moc]] |
| Writing or reviewing UI copy | [[studio.design.copy.moc]] |
| Pattern-match a UI copy surface | [[studio.design.copy.microcopy-patterns]] |
| Copy tone for a specific emotional context | [[studio.design.copy.tone-matrix]] |
| Pre-ship copy QA | [[studio.design.copy.checklist]] |
| Quick UI critique | [[studio.design.checklist.ui-critique]] |
| Visual QA before shipping | [[studio.design.checklist.visual-qa]] |
| Animation/transition review, easing, polish | [[studio.design.emil-design-eng]] |
| Concrete app transition pattern | [[studio.design.patterns.transitions-dev-motion]] |
| Full UI/UX rules audit (152 rules) | [[studio.design.userinterface-wiki]] |
| Animation implementation review | [[studio.design.userinterface-wiki]] → `timing-*`, `physics-*`, `spring-*` rules |
| UX psychology audit (Fitts's, Hick's, etc.) | [[studio.design.userinterface-wiki]] → `ux-*` rules |
| Typography implementation review | [[studio.design.userinterface-wiki]] → `type-*` rules |

## MOCs (sub-domains)
- [[studio.design.typography.moc]] — type scale, font pairing, readability
- [[studio.design.layout.moc]] — grid systems, spacing, responsive
- [[studio.design.designsystem.moc]] — tokens, components, colors, motion
- [[studio.design.assets.moc]] — AI-generated visuals, icons, OG images
- [[studio.design.copy.moc]] — UX copywriting, microcopy, tone, voice

## Design Engineering
- [[studio.design.emil-design-eng]] — animation decisions, easing, spring physics, component polish (Emil Kowalski / Vercel / Sonner)
- [[studio.design.userinterface-wiki]] — 152 implementation rules: animation, timing, UX laws, typography, prefetch, visual polish (Raphael Salaja)

## System
- [[studio.design.system.design-tokens]] — canonical token definitions
- [[studio.design.system.creative-direction]] — Maroun's design taste and brand philosophy

## Patterns
- [[studio.design.patterns.design-with-taste]] — how to make opinionated design decisions
- [[studio.design.patterns.motion-design-patterns]] — Motion.dev patterns
- [[studio.design.patterns.transitions-dev-motion]] — concrete CSS/React transition patterns from Transitions.dev
- [[studio.design.patterns.premium-interaction-patterns]] — premium feel heuristics

## Copy
- [[studio.design.copy.moc]] — UX copywriting entry point (load this first for any copy work)
- [[studio.design.copy.ux-writing-principles]] — core principles, sourced from Polaris/Google/Apple/NNG
- [[studio.design.copy.microcopy-patterns]] — pattern library: errors, CTAs, empty states, modals, loading, success
- [[studio.design.copy.tone-matrix]] — emotional context → tone mapping
- [[studio.design.copy.persona-voice]] — per-project voice guide template
- [[studio.design.copy.checklist]] — pre-ship copy QA checklist
- [[studio.design.copy.anti-patterns]] — copy mistakes to catch and fix

## Heuristics
- [[studio.design.heuristics.irreversible-actions]] — flows where mistakes are costly (payments, deletion, publishing)

## Checklists
- [[studio.design.checklist.ui-critique]] — structured design critique
- [[studio.design.checklist.visual-qa]] — pre-ship quality gate
- [[studio.ship.qa.visual-qa-loop]] — screenshot → compare → fix protocol (Gate 1)
- [[studio.ship.qa.two-axis-review]] — 4-quadrant quality score, min 3/5 (Gate 2)
- [[studio.design.copy.checklist]] — pre-ship copy QA (runs alongside visual-qa)

## Critique & Taste
- [[studio.design.critique.taste-compounding]] — live critique accumulation → anti-slop rule promotion

## Templates
- [[studio.design.template.design-brief]] — design brief format
