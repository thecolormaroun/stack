---
name: ship
description: "Full pipeline: braindump → PRD → design → build"
---

# Ship — Full Creative Pipeline

Run the complete Studio pipeline from raw idea to shipped product.

## Skill graph entry point
Start at: `./_graph/studio.moc.md` then follow domain MOCs.

## When to Use
- `/ship [idea or voice dump]`
- When you wants end-to-end execution

## Pipeline

Execute each phase in sequence. Report progress after each step.

## Pipeline Controller (routing + artifacts)

### Step 0 — Decide: single-department vs full ship
Classify the request:
- **Full /ship** when it includes product + design + build (new feature/app, major iteration, “make it usable daily”).
- **Single department** when it’s clearly scoped to one lane (design tweak, pure research, pure product planning, pure engineering).

### Step 1 — Always produce an artifact
To keep Studio linear and compounding, every run must write at least one durable artifact:

**If full /ship:**
- Product → PRD + `prd.json`
- Design → tokens/spec notes
- Engineering → implemented stories + progress update
- Ship → QA checklist + release notes

**If single-department:**
- Write a short output note (brief/spec/checklist) that can be used as input later.

Artifacts should be referenced/linked in the Summary.

### Phase 1: Brain Dump Processing
Load `brain-dump-processor` skill. Extract and classify all items from the input.
- Output: Structured brief with categorized items
- Ask you to confirm scope before proceeding

### Phase 2: PRD Generation
Load `prd-writer` skill. Generate full PRD and prd.json.
- Output: `specs/prd-v[N].md` + `agents/prd.json` + `progress.md`
- Ask you to approve before building

### Phase 3: Design Direction
Load relevant design skills based on project needs:
- New visual identity? → CDO `visual-direction` skill
- Standard dark theme? → `design-system` defaults
- Custom typography? → `typography` skill
- Output: Design tokens and specs applied to project

### Phase 4: Build
Execute compound-engineering `/lfg` pipeline:
```bash
claude --dangerously-skip-permissions -p "/lfg Phase 3: Implement V[N] user stories from prd.json"
```
- Each user story executed sequentially
- Commit after each story
- Update progress.md

### Phase 5: Review
- Run local preview
- Check against acceptance criteria
- Lighthouse audit (performance + accessibility)
- Report results to you

## Rules
- **Always pause for approval** between Phase 2 (PRD) and Phase 4 (Build)
- **Design phase can be skipped** if using established design system
- **Budget check** before Phase 4 — estimate cost and confirm with you
- **Log everything** — lessons, decisions, tasks to your task tracker
