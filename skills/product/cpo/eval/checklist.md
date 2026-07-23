# CPO Quality Checklist

Run this checklist after generating any PRD or prd.json.

## PRD Checklist

| # | Check | Pass/Fail |
|---|-------|-----------|
| 1 | **Executive summary** — 2-3 sentences, clear what and why | |
| 2 | **Problem statement** — Specific pain points, not vague | |
| 3 | **Success metrics** — Measurable, time-bound | |
| 4 | **Scope boundaries** — Clear in/out of scope for this version | |
| 5 | **RICE scores** — Every feature prioritized with scores | |
| 6 | **P0 count ≤3** — Realistic must-haves | |
| 7 | **Original brain dump preserved** — In appendix | |
| 8 | **Open questions surfaced** — Unresolved items flagged | |

## User Story Checklist

| # | Check | Pass/Fail |
|---|-------|-----------|
| 1 | **Fits one context window** — No XL stories | |
| 2 | **Clear title** — No "and-and-and" | |
| 3 | **Acceptance criteria present** — 3-7 items | |
| 4 | **"Typecheck passes" included** — Every story | |
| 5 | **Dependency order correct** — Schema → API → UI | |
| 6 | **Size labeled** — XS/S/M (no L/XL) | |
| 7 | **Priority labeled** — P0/P1/P2 | |
| 8 | **Dependencies listed** — If any exist | |

## prd.json Checklist

| # | Check | Pass/Fail |
|---|-------|-----------|
| 1 | **Valid JSON** — Parses without error | |
| 2 | **Branch name set** — Uses `ralph/` prefix | |
| 3 | **Stories match PRD** — Same IDs, same order | |
| 4 | **All stories have AC** — Non-empty arrays | |
| 5 | **Priority numbers** — 0 for P0, 1 for P1, etc. | |
| 6 | **passes: false** — All start unshipped | |

## Quality Gates

### Gate 1: Story Size
```
Every story answers:
"Can this be implemented in <2 hours of focused work?"
```
- [ ] No story exceeds M size
- [ ] No story has >7 acceptance criteria

### Gate 2: Dependency Graph
```
For each story, all dependencies already exist or come earlier in the list.
```
- [ ] No forward references
- [ ] Schema before API before UI

### Gate 3: Human Review
```
"Would this PRD make sense to a new engineer?"
```
- [ ] Context provided
- [ ] No assumed knowledge
- [ ] Clear done definition

## Scoring

- **8/8 PRD + 8/8 Story + 6/6 prd.json** = Ready for /lfg
- **Missing 1-2 items** = Fix before shipping
- **Missing 3+ items** = Back to drafting

## Common Failures

| Failure | Fix |
|---------|-----|
| XL story | Split into 3-4 smaller stories |
| Missing typecheck AC | Add to every story |
| Wrong dependency order | Reorder: schema → API → UI |
| No success metrics | Add measurable goal + timeframe |
| Everything P0 | Demote to P1/P2, keep only 2-3 true P0s |
