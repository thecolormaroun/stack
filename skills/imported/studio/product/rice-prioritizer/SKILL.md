---
name: rice
description: "RICE scoring and feature prioritization"
---

# RICE Prioritizer

Score and prioritize features/projects using the RICE framework with your weighting preferences.

## Skill graph entry point
Start at: `./_graph/product/prioritization/studio.product.prioritization.rice.md`
Also see: `./_graph/product/prioritization/studio.product.prioritization.rice-filters.md`

## When to Use
- Multiple features competing for attention
- `/roadmap` needs prioritized backlog
- you asks "what should I build next?"

## RICE Scoring

| Factor | Scale | How to Score |
|--------|-------|-------------|
| **Reach** | 1-10 | How many users/sessions affected per quarter |
| **Impact** | 0.25, 0.5, 1, 2, 3 | Minimal → Massive improvement |
| **Confidence** | 20-100% | How sure are we about estimates |
| **Effort** | Person-weeks | Engineering + design time (conservative) |

**Score = (Reach × Impact × Confidence) / Effort**

## Process

### 1. List Candidates
Gather all features/ideas from:
- task tracker entrys tagged #product
- Brain dump backlog
- Roadmap items

### 2. Score Each

```markdown
## RICE Scorecard

| Feature | Reach | Impact | Confidence | Effort | Score |
|---------|-------|--------|-----------|--------|-------|
| [Feature A] | 8 | 2 | 80% | 2w | 6.4 |
| [Feature B] | 3 | 3 | 60% | 4w | 1.35 |
```

### 3. Apply your Filters
After RICE scoring, apply qualitative filters:
- **Joy factor** — Does building this excite you? (personal projects especially)
- **Learning value** — Does this teach a new skill or technique?
- **Portfolio value** — Does this showcase design/product ability?
- **Dependency unlock** — Does this unblock other high-value work?

### 4. Output Priority Stack
Ordered list with rationale, saved to project roadmap.

## Integration
- Input: Feature list from any source
- Output: Prioritized backlog with scores
- Next: roadmap-manager for timeline planning
