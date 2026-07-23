# User Story Sizing Rules

## The Core Constraint

**Each story must be completable in ONE context window.**

This is non-negotiable. Oversized stories cause:
- Context loss mid-implementation
- Partial commits
- Broken builds
- Ralph loop failures

## Sizing Heuristics

| Size | Scope | Typical Pattern |
|------|-------|-----------------|
| **XS** | Single function or config change | "Add a constant", "Fix typo" |
| **S** | One component or one API endpoint | "Add button", "New route" |
| **M** | Feature slice: schema + backend + UI | "Add favorites feature" |
| **L** | Multiple related components | **⚠️ Consider splitting** |
| **XL** | Cross-cutting change | **🚫 Must split** |

## Splitting Strategies

### By Layer
Break vertically:
1. Schema/types first
2. Backend/API second
3. UI third
4. Polish/edge cases last

### By User Flow
Break horizontally:
1. Happy path first
2. Error states second
3. Edge cases third

### By Component
Break by UI surface:
1. List view
2. Detail view
3. Create/edit form
4. Delete flow

## Dependency Ordering

Order stories so each builds on the last:

```
US-001: Add Food type to schema
US-002: Add getFoods API endpoint (depends on US-001)
US-003: Add FoodList component (depends on US-002)
US-004: Add FoodDetail view (depends on US-003)
US-005: Add favorites toggle (depends on US-003)
```

Never:
- Reference code that doesn't exist yet
- Skip schema when adding data
- Build UI before API exists

## Acceptance Criteria Rules

Every story must include:
- [ ] Specific, verifiable behavior
- [ ] `Typecheck passes` (always)
- [ ] `No regressions` (if touching existing code)

Example:
```markdown
**Acceptance Criteria:**
- [ ] FoodList shows all foods from API
- [ ] Loading state shows skeleton
- [ ] Empty state shows helpful message
- [ ] Typecheck passes
- [ ] Existing tests still pass
```

## Red Flags

🚩 Story is too big if:
- Acceptance criteria > 7 items
- Multiple files across layers
- "and" appears in the title multiple times
- Estimated > 2 hours of focused work

🚩 Story is too vague if:
- No acceptance criteria
- "Make it work" or "Fix issues"
- No clear "done" definition
