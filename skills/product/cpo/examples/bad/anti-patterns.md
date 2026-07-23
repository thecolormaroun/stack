# CPO Anti-Patterns to Avoid

These patterns lead to failed builds, unclear specs, and wasted cycles.

## PRD Anti-Patterns

### 1. No Acceptance Criteria
❌ "Add favorites feature"
✅ "Add favorites feature" with 5 specific, verifiable criteria

Why it's bad: No way to know when it's done. Agent guesses, ships wrong thing.

### 2. Kitchen Sink PRD
❌ V1 with 47 user stories
✅ V1 with 5-8 stories, rest in V2+

Why it's bad: Never ships. Scope creep. Context overflow.

### 3. Missing Typecheck AC
❌ Acceptance criteria without "Typecheck passes"
✅ Every story includes "Typecheck passes"

Why it's bad: Agent ships broken code that fails silently.

### 4. Wrong Dependency Order
❌ US-001: Build FavoriteButton UI → US-002: Add favorites to schema
✅ US-001: Add favorites to schema → US-002: Build FavoriteButton UI

Why it's bad: Story 1 fails because types don't exist yet.

### 5. Vague Success Metrics
❌ "Users should like it"
✅ "Favorites used by 50% of active users within 2 weeks"

Why it's bad: No way to measure success. Can't learn from outcome.

## Story Sizing Anti-Patterns

### 6. XL Stories
❌ "Implement entire favorites system including schema, API, UI, and tests"
✅ Split into 4 separate stories

Why it's bad: Exceeds context window. Agent loses track mid-story.

### 7. And-And-And Titles
❌ "Add favorites button and persist to storage and sync with server and show toast"
✅ "Add favorites button" → "Persist favorites" → "Sync favorites" → "Show toast"

Why it's bad: Each "and" is a separate concern. Split them.

### 8. No Clear Done Definition
❌ "Make the app better"
✅ "Reduce initial load time to <2 seconds measured by Lighthouse"

Why it's bad: Agent doesn't know when to stop. Infinite loop.

## Prioritization Anti-Patterns

### 9. Everything is P0
❌ 15 P0 stories in one PRD
✅ 2-3 P0 (must have), 3-5 P1 (should have), rest P2 or backlog

Why it's bad: If everything is urgent, nothing is. No focus.

### 10. RICE Without Confidence Adjustment
❌ Reach: 10, Impact: 3, Effort: 2 → Score: 15 (gut feel)
✅ Reach: 10, Impact: 3, Confidence: 50%, Effort: 2 → Score: 7.5 (honest)

Why it's bad: Overestimates uncertain features. Wrong priorities.

### 11. Ignoring Effort
❌ "This is important so we should do it" (3-month effort)
✅ "This is important but 3 months — can we ship a smaller version first?"

Why it's bad: Blocks other high-value work. Never ships.

## Brain Dump Anti-Patterns

### 12. Not Capturing Original
❌ Summarize brain dump, lose original
✅ Keep original in appendix, summarize above

Why it's bad: Lose nuance and context. Can't revisit later.

### 13. Missing Open Questions
❌ Assume answers to unclear requirements
✅ Surface "❓ Open Questions" and resolve before spec

Why it's bad: Agent builds wrong thing. Rework.

### 14. No Version Context
❌ PRD with no reference to what shipped before
✅ PRD references V1, explains what's new

Why it's bad: No continuity. Can't track evolution.
