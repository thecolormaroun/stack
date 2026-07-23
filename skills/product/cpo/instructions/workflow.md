# CPO Core Workflow

```
Brain Dump (voice/text)
    ↓
┌─────────────────────┐
│   1. EXTRACT        │  Parse ideas, features, feedback, bugs, decisions
│   2. ORGANIZE       │  Categorize, deduplicate, map to existing roadmap
│   3. PRIORITIZE     │  RICE scoring, dependency analysis
│   4. SPEC           │  Generate plan with acceptance criteria
│   5. PACKAGE        │  Output compound-engineering compatible files
└─────────────────────┘
    ↓
Execute: /ce:work or /lfg
```

## Step 1: Process the Brain Dump

Extract & classify every item:

| Category | Signal Words | Example |
|----------|-------------|---------|
| **🐛 Bug** | "broken", "wrong", "doesn't work", "fix" | "Ages are wrong for some foods" |
| **✨ Feature** | "add", "I want", "would be cool", "need" | "Want to save favorites" |
| **🔧 Improvement** | "better", "faster", "easier", "annoying" | "Food list is too long" |
| **🎯 Strategic** | "vision", "goal", "eventually", "phase 2" | "Want this to be THE baby food app" |
| **❓ Open Question** | "should we", "not sure", "what if" | "Should we add allergies?" |

## Step 2: Prioritize with RICE

| Factor | Question | Scale |
|--------|----------|-------|
| **Reach** | How many users/sessions affected? | 1-10 |
| **Impact** | How much does it improve the experience? | 0.25 (minimal) to 3 (massive) |
| **Confidence** | How sure are we about reach/impact? | 50%, 80%, 100% |
| **Effort** | Engineering effort in story points | 1 (hour) to 10 (week+) |

**RICE Score = (Reach × Impact × Confidence) / Effort**

Group into:
- **P0 — Must Have (this version):** Bugs + highest RICE features
- **P1 — Should Have:** High RICE, reasonable effort
- **P2 — Nice to Have:** Lower RICE or high effort
- **Backlog:** Strategic items for future versions

## Step 3: Choose Detail Level

Match complexity to plan depth (from compound-engineering):

| Level | When to Use | Sections |
|-------|-------------|----------|
| **MINIMAL** | Simple bugs, small features | Problem, Acceptance Criteria, Context |
| **MORE** | Most features, team work | + Background, Technical, Success Metrics, Risks |
| **A LOT** | Major features, architecture | + Phases, Alternatives, System Impact, Resources |

## Step 4: Generate Plan File

**Filename format:** `docs/plans/YYYY-MM-DD-NNN-<type>-<name>-plan.md`

```bash
# Determine daily sequence number
today=$(date +%Y-%m-%d)
last_seq=$(ls docs/plans/${today}-*-plan.md 2>/dev/null | grep -oP "${today}-\K\d{3}" | sort -n | tail -1)
next_seq=$(printf "%03d" $(( ${last_seq:-0} + 1 )))
```

**Examples:**
- ✅ `2026-03-18-001-feat-user-dashboard-plan.md`
- ✅ `2026-03-18-002-fix-login-timeout-plan.md`
- ❌ `feat-new-thing-plan.md` (missing date)

## Step 5: Hand Off

```
Plan ready: [Project] [Feature]

📋 Plan: docs/plans/YYYY-MM-DD-NNN-<type>-<name>-plan.md
🚀 Execute: /ce:work docs/plans/<plan>.md
   or: /lfg [feature description]

Acceptance criteria defined. Ready for implementation.
```

## Integration with compound-engineering

CPO outputs are designed to work with:
- `/ce:plan` — If user wants compound-engineering to do additional research/planning
- `/ce:work` — Direct execution from CPO-generated plan
- `/lfg` — Full autonomous workflow (plan → work → review → ship)

The plan format matches what `/ce:work` expects, so CPO can skip to execution.
