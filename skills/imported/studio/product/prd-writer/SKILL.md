---
name: prd
description: "Generate PRD + prd.json for compound-engineering /lfg pipeline"
---

# PRD Writer

Generate comprehensive Product Requirements Documents and machine-readable `prd.json` that compound-engineering's `/lfg` pipeline can execute directly.

## Skill graph entry point
Start at: `./_graph/product/product.moc.md`.
Key node: `./_graph/product/prd/studio.product.prd.prd-outline.md`

## When to Use
- After brain-dump processing, when scope is clear
- `/prd` command
- When a project needs formal requirements before building
- Version upgrades based on user feedback

## Process

### 1. Gather Inputs
- Creative brief or brain dump summary (from brain-dump-processor)
- Existing specs, design direction, or prior PRD versions
- your verbal requirements
- Competitive research (if available from research dept)
- Technical constraints (existing codebase, stack, APIs)

### 2. Generate PRD

Save to `./project/specs/prd-v[N].md`:

```markdown
# PRD: [Product/Feature Name] V[N]

**Author:** Product Team
**Date:** YYYY-MM-DD
**Status:** Draft | In Review | Approved | In Progress | Shipped

## Executive Summary
[2-3 sentences: what we're building, why, for whom]

## Problem Statement
[What's broken or missing. User quotes/feedback if available.]

## Goals & Success Metrics
| Goal | Metric | Target |
|------|--------|--------|
| [Goal] | [How measured] | [Specific target] |

## Scope

### In Scope (this version)
| Priority | Feature | RICE Score | Effort |
|----------|---------|------------|--------|
| P0 | [Feature] | [score] | S/M/L |
| P1 | [Feature] | [score] | S/M/L |

### Out of Scope (deferred)
- [Feature] → V[N+1]
- [Feature] → Backlog

## User Stories

### US-001: [Title]
**As a** [persona], **I want** [action], **so that** [benefit].

**Acceptance Criteria:**
- [ ] [Specific, verifiable criterion]
- [ ] [Another criterion]
- [ ] Typecheck passes
- [ ] No regressions in existing functionality

**Size:** S/M/L | **Priority:** P0/P1/P2 | **Dependencies:** [or None]

[Repeat for each user story...]

## Technical Architecture
- **Stack:** [Framework, language, infra]
- **Data model:** [Key entities and relationships]
- **APIs:** [External integrations needed]
- **Hosting:** [Where it runs]

## Design Requirements
- [Visual direction — reference design dept specs if available]
- [Key screens/flows to design]
- [Responsive targets]
- [Reference your established taste profile]

## Risks & Mitigations
| Risk | Impact | Mitigation |
|------|--------|-----------|
| [Risk] | [H/M/L] | [Plan] |

## Open Questions
1. [Unresolved item — tag @user if needs his input]

## Appendix: Raw Feedback
[Preserve original brain dump/feedback for reference]
```

### 3. Generate prd.json for /lfg

This is what compound-engineering reads. Each user story becomes one iteration.
Save to `./project/agents/prd.json`:

```json
{
  "project": "[ProjectName]",
  "branchName": "ralph/v[N]-[feature-slug]",
  "description": "[One-line version description]",
  "userStories": [
    {
      "id": "US-001",
      "title": "[Story title]",
      "description": "As a [persona], I want [action], so that [benefit]",
      "acceptanceCriteria": [
        "[Criterion 1]",
        "[Criterion 2]",
        "Typecheck passes"
      ],
      "priority": 1,
      "passes": false,
      "notes": ""
    }
  ]
}
```

**Critical Sizing Rules:**
- Each user story MUST be completable in ONE context window
- Order stories by dependency: schema → backend → UI → polish
- Include "Typecheck passes" in EVERY story's acceptance criteria
- Use `ralph/` branch prefix for compound-engineering
- If a story feels too big, split it into sub-stories

### 4. Generate progress.md

Save to `./project/progress.md`:

```markdown
# Progress: [Project] V[N]

**Last Updated:** YYYY-MM-DD
**Current Phase:** Ready for Build
**PRD:** specs/prd-v[N].md
**Branch:** ralph/v[N]-[feature-slug]

## Implementation Plan
- [ ] 1. US-001: [Title] ← CURRENT
- [ ] 2. US-002: [Title]
- [ ] 3. US-003: [Title]

## Decisions Log
| Date | Decision | Rationale |

## Notes
- Generated from brain dump on [date]
- Execute with: /lfg Phase 3: Implement V[N] user stories from prd.json
```

### 5. Hand Off to Studio Build

```
New build ready: [Project] V[N]

📋 PRD: specs/prd-v[N].md
🔄 Build spec: agents/prd.json ([N] user stories)
📊 Progress: progress.md
🌿 Branch: ralph/v[N]-[feature-slug]

Stories ordered by dependency. Each fits one context window.
Execute: /lfg Phase 3: Implement V[N] user stories
```

## Defaults (your Preferences)
- Conservative time estimates (pad 30%)
- Next.js + Tailwind unless specified otherwise
- Dark theme default with light mode support
- Mobile-first responsive
- Vercel deployment unless specified
- Motion.dev for animations (`motion/react`)
- Every estimate is a single number (not a range)
