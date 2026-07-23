---
name: cpo
description: "Chief Product Officer skill. Turn brain dumps into shipping software. Process voice/text into structured plans compatible with compound-engineering /lfg workflow."
metadata:
  clawdbot:
    emoji: "🎯"
    os: ["darwin", "linux"]
---

# CPO Skill — Chief Product Officer

Turn brain dumps into shipping software.

**Philosophy:** Every feature has a user, a problem, and a measurable outcome. Ship small, learn fast, iterate.

---

## Workflow

Read `instructions/workflow.md` for the 5-step process:
1. Extract → 2. Organize → 3. Prioritize → 4. Spec → 5. Package

---

## Prioritization

Read `instructions/rice-scoring.md` for RICE formula and scoring guide.

**RICE = (Reach × Impact × Confidence) / Effort**

---

## Story Sizing

Read `instructions/story-sizing.md` for the core constraint:

**Each story must be completable in ONE context window.**

Sizing: XS/S/M only. If L or XL, split it.

---

## Before Shipping Any Plan

Read `examples/good/` for what quality looks like.

Read `examples/bad/anti-patterns.md` for anti-patterns to avoid.

---

## After Generating Plan

Run `eval/checklist.md` for quality gates.

Run `eval/advisory-board.md` — 3 personas review in parallel:
- 🎯 **Shreyas** (PM) — Strategy, prioritization, user value
- 🛠️ **Kent** (Builder) — Implementation feasibility, story quality
- 👤 **Mom** (User) — Real-world usability, edge cases

Fix all 🔴 blockers before shipping.

---

## Output Format (compound-engineering compatible)

**Primary output:** `docs/plans/YYYY-MM-DD-NNN-<type>-<name>-plan.md`

Uses the compound-engineering plan format with YAML frontmatter:

```markdown
---
title: [Feature/Fix Title]
type: feat|fix|refactor
status: active
date: YYYY-MM-DD
---
```

Detail levels (from compound-engineering):
- **MINIMAL** — Simple bugs, clear features
- **MORE** (Standard) — Most features, team collaboration  
- **A LOT** (Comprehensive) — Major features, architectural changes

**Execute with:** `/ce:work docs/plans/<plan-file>.md` or `/lfg`

---

## Legacy Ralph Loop Format (optional)

If project uses `agents/prd.json` format instead:
- Use `templates/prd.json` for machine-readable spec
- Use `templates/progress.md` for tracking
- Execute with custom Ralph loop scripts

---

## Quick Commands

| Input | Action |
|-------|--------|
| "[voice dump]" | Full workflow: Extract → Prioritize → Plan |
| "Feedback on V1" | Process → Generate V2 Plan |
| "What's the roadmap?" | Show Now/Next/Later |
| "Ship it" | Package plan + `/ce:work` or `/lfg` instructions |
| "Scope this down" | Trim to P0 only, defer rest |
