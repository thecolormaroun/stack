# Example: Noah's Noms V2 PRD (Good)

This PRD demonstrates CPO workflow executed well.

## What Makes This Good

1. **Clear brain dump extraction** — Every item categorized (bug/feature/improvement)
2. **RICE scoring** — Quantified prioritization, not gut feel
3. **Right-sized stories** — Each fits in one context window
4. **Dependency ordering** — Schema → API → UI → Polish
5. **Every story has AC** — Including "Typecheck passes"

## PRD Excerpt

```markdown
# PRD: Noah's Noms V2

**Author:** Maroun (via R2 CPO)
**Date:** 2026-03-10
**Status:** Approved

## Executive Summary
V2 adds favorites and fixes age display bugs. Based on 2 weeks of daily use feedback.

## Scope

### In Scope (V2)
| Priority | Feature | RICE | Effort |
|----------|---------|------|--------|
| P0 | Fix age display bug | N/A (bug) | S |
| P0 | Add favorites | 4.3 | M |
| P1 | Filter by age | 2.8 | S |

### Out of Scope (V3+)
- Allergy warnings (needs research)
- Meal planning (large effort)

## User Stories

### US-001: Fix age display calculation
**As a** parent, **I want** ages to display correctly, **so that** I can trust the app.

**Acceptance Criteria:**
- [ ] "6 months" shows for 180-210 day range
- [ ] Edge cases (premature, adjusted age) handled
- [ ] Typecheck passes

**Size:** S | **Priority:** P0

### US-002: Add Food.isFavorite to schema
**As a** developer, **I want** favorites in the data model, **so that** UI can use it.

**Acceptance Criteria:**
- [ ] Food type includes optional `isFavorite: boolean`
- [ ] Migration handles existing data
- [ ] Typecheck passes

**Size:** XS | **Priority:** P0 | **Dependencies:** None

### US-003: Add toggleFavorite API endpoint
**As a** developer, **I want** an API to toggle favorites, **so that** UI can call it.

**Acceptance Criteria:**
- [ ] POST /api/foods/:id/favorite toggles state
- [ ] Returns updated Food object
- [ ] Typecheck passes

**Size:** S | **Priority:** P0 | **Dependencies:** US-002
```

## prd.json Excerpt

```json
{
  "project": "NoahsNoms",
  "branchName": "ralph/v2-favorites",
  "userStories": [
    {
      "id": "US-001",
      "title": "Fix age display calculation",
      "acceptanceCriteria": [
        "6 months shows for 180-210 day range",
        "Edge cases handled",
        "Typecheck passes"
      ],
      "priority": 0,
      "passes": false
    }
  ]
}
```

## Why This Worked

- Studio executed all 5 stories in one overnight session
- Zero context loss between stories
- No manual intervention needed
- V2 shipped next morning
