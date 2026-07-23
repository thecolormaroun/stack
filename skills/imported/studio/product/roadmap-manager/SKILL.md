---
name: roadmap
description: "Now/Next/Later project planning and portfolio management"
---

# Roadmap Manager

Maintain living roadmaps with Now/Next/Later planning across all of your projects.

## Skill graph entry point
Start at: `./_graph/product/roadmap/roadmap.moc.md`

## When to Use
- `/roadmap` command
- Planning what to build next
- Reviewing project portfolio status
- After shipping a version (promote next items)
- Weekly review integration

## Framework: Now / Next / Later

Living roadmap at `./output/reference/studio-roadmap.md`.

See graph nodes:
- `./_graph/product/roadmap/studio.product.roadmap.now-next-later.md`
- `./_graph/product/roadmap/studio.product.roadmap.capacity-rules.md`
- `./_graph/product/roadmap/studio.product.roadmap.update-process.md`

Template:

```markdown
# Studio Roadmap — Updated [Date]

## 🔴 NOW (This Week)
Active builds, in-progress work.
| Project | Phase | Status | Owner | ETA |
|---------|-------|--------|-------|-----|
| [Project] | [V/Phase] | 🟡 In Progress | Studio | [Date] |

## 🟡 NEXT (Next 2 Weeks)
Queued and scoped, ready to start when capacity opens.
| Project | Scope | RICE | Blocker |
|---------|-------|------|---------|
| [Project] | [Description] | [Score] | [None / waiting on X] |

## 🟢 LATER (This Quarter)
Validated ideas with rough scope.
| Project | Description | RICE | Dependencies |
|---------|-------------|------|-------------|
| [Project] | [What] | [Score] | [What needs to happen first] |

## 🧊 ICEBOX
Good ideas, not yet prioritized or scoped.
| Idea | Source | Date Added |
|------|--------|-----------|
| [Idea] | [Brain dump / conversation] | [Date] |

## ✅ SHIPPED
| Project | Version | Shipped | Notes |
|---------|---------|---------|-------|
| [Project] | V[N] | [Date] | [Link / outcome] |
```

## Process

### 1. Gather Current State
```bash
# Active projects with progress files
find ./projects -name "progress.md" -exec sh -c 'echo "=== $1 ===" && head -8 "$1"' _ {} \;

# Studio tasks
# List open tasks from your tracker
# Example: gh issue list --state open

# Recently completed
# List completed tasks
# Example: gh issue list --state closed --limit 10
```

### 2. Update Roadmap
- **Ship it:** Move completed NOW → SHIPPED with date and outcome
- **Promote:** Move highest NEXT → NOW when capacity opens
- **Re-score:** Re-evaluate LATER items if context changed (new feedback, priorities shifted)
- **Add:** New ideas from brain dumps → ICEBOX
- **Prune:** Remove items that are no longer relevant (log why)

### 3. Capacity Check
you is a solo builder on parental leave with limited time:
- **Max 1 active build** in NOW at a time
- **Max 2-3 items** in NEXT (don't overcommit)
- When estimating, account for: baby interruptions, energy levels, context switching cost
- Prefer small, shippable increments over ambitious multi-week builds

### 4. Save & Communicate
- Save roadmap → `./output/reference/studio-roadmap.md`
- Send summary to you to the team if significant changes
- Integrate with Sunday weekly life review (life-review-council skill)

## Cadence
- **Weekly:** Review during Sunday life review cron
- **On-demand:** When projects complete or new ideas arrive
- **Monthly:** Full re-prioritization with RICE scores
- **After every ship:** Update immediately
