# Studio Handoff Format

## File Structure in Project Directory

After CPO processing, the project should have:

```
~/Projects/[project-name]/
├── agents/
│   └── prd.json              # Ralph loop execution spec
├── specs/
│   ├── prd-v1.md             # V1 PRD (shipped)
│   └── prd-v2.md             # V2 PRD (current)
├── progress.md               # Studio ground truth
├── src/                      # Source code
└── ...
```

## prd.json Spec (Ralph Loop Compatible)

The `agents/prd.json` file is read by Studio's `/lfg` compound engineering loop:

```
/lfg Phase 3: Implement V2 user stories from prd.json
```

This triggers Studio to:
1. Read `progress.md` as ground truth
2. Read `agents/prd.json` for the story list
3. Pick first story where `passes: false`
4. Implement it in one context window
5. Run checks (typecheck, lint, test)
6. Commit: `feat: US-001 - [Story Title]`
7. Update `prd.json`: set `passes: true`
8. Update `progress.md`: check off task
9. Append learnings to `progress.txt`
10. Loop to next story

## Story Sizing Guidelines

Each story MUST be completable in one `/lfg` iteration:

### ✅ Right-Sized Stories
- Add/modify a database table or schema
- Create a single API endpoint or server action
- Build one UI component or page section
- Add search/filter to an existing list
- Fix a specific bug with clear reproduction
- Add form validation rules
- Create a reusable component

### ❌ Too Large (split these)
- "Build the entire [feature]" → Split into data + API + UI
- "Redesign the [page]" → Split into layout + components + interactions
- "Add authentication" → Split into schema + middleware + UI + sessions
- "Migrate to [new approach]" → Split into setup + migrate + verify + cleanup

### Story Dependency Order
1. **Schema/Data** — Database changes, type definitions
2. **Backend/Logic** — Server actions, API routes, business logic
3. **UI/Components** — React components, pages, layouts
4. **Integration** — Connecting UI to backend, state management
5. **Polish** — Animations, error handling, loading states, edge cases

## Branch Naming

Always use `ralph/` prefix for compound engineering compatibility:

```
ralph/v2-noah-noms-improvements
ralph/v1-initial-build
ralph/v3-search-and-filters
```

## Handoff Message Template

When handing off to Studio, use this format:

```
@R2StudioBot New build ready: [Project] V[N]

📋 PRD: specs/prd-v[N].md
🔄 Ralph spec: agents/prd.json ([N] user stories)
📊 Progress: progress.md
🌿 Branch: ralph/v[N]-[slug]

Execute with:
/lfg Phase 3: Implement V[N] user stories from prd.json

Stories ordered by dependency. Each fits one context window.
Start US-001, work sequentially.
```

## Progress Tracking During Execution

Studio updates `progress.md` as it works:

```markdown
## Implementation Plan
- [x] 1. US-001: Add food categories schema ✅
- [x] 2. US-002: Create category API endpoints ✅
- [ ] 3. US-003: Build category filter UI ← CURRENT
- [ ] 4. US-004: Add search functionality
- [ ] 5. US-005: Favorites system
```

## Completion Signal

When all stories pass:
```markdown
## Status: ✅ RALPH_DONE
Completed: YYYY-MM-DD
Branch: ralph/v2-noah-noms-improvements
Stories: 8/8 passed
```
