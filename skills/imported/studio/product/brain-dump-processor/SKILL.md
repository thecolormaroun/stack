---
name: braindump
description: "Process voice/text dumps into structured creative briefs"
---

# Brain Dump Processor

Process raw voice notes, text dumps, and unstructured ideas into structured, actionable creative briefs. This is the entry point to the Studio pipeline.

## Skill graph entry point
Start at: `./_graph/product/braindump.moc.md`

## When to Use
- you sends a voice note with ideas, feedback, or feature requests
- Unstructured text about what he wants built
- `/braindump` command
- Post-usage feedback on shipped products

## Process

### 1. Extract & Classify Every Item

Parse the raw input. Every discrete idea, request, or observation gets classified:

| Category | Signal Words | Action |
|----------|-------------|--------|
| **🐛 Bug** | "broken", "wrong", "doesn't work", "fix" | Immediate — goes to P0 |
| **✨ Feature** | "add", "I want", "would be cool", "need" | Score with RICE |
| **🔧 Improvement** | "better", "faster", "easier", "annoying" | Score with RICE |
| **🎯 Strategic** | "vision", "goal", "eventually", "phase 2" | Roadmap/Later bucket |
| **💡 Design** | "look", "feel", "style", "layout", "color" | Route to Design dept |
| **❓ Open Question** | "should we", "not sure", "what if" | Flag for you |

**Rules:**
- Extract EVERYTHING — don't skip items that seem minor
- Preserve your exact words for context (quotes)
- Infer implicit requirements from his preferences (USER.md)
- Note emotional signals — excitement = higher priority, frustration = P0

### 2. Generate Brain Dump Summary

```markdown
## Brain Dump Summary — [Project] [Date]

### Source
[Voice note / text / conversation — timestamp]

### 🐛 Bugs (fix now)
1. [Bug description] — [severity: critical/major/minor]

### ✨ New Features
1. [Feature] — [who benefits] — [rough size: S/M/L]

### 🔧 Improvements
1. [What to improve] — [why it matters]

### 💡 Design Direction
- [Visual/UX cues mentioned]

### 🎯 Strategic Direction
- [Vision/goal/direction noted]

### ❓ Open Questions (need your input)
1. [Question — why it matters for scoping]

### Implicit Requirements (inferred)
- [From your preferences: dark theme, premium feel, etc.]
- [From project context: existing stack, design system]
```

### 3. Determine Next Step

Based on what was extracted:

| Situation | Route To |
|-----------|----------|
| New product idea, scope unclear | Ask clarifying questions first |
| Clear feature set, ready to spec | `prd-writer` → generate PRD + prd.json |
| Feedback on shipped product | Map to roadmap → generate V(N+1) PRD |
| Design-heavy request | `visual-direction` or `design-system` skill |
| Just bugs | Skip PRD, create tasks directly in your task tracker |
| Strategic/vision dump | `roadmap-manager` to update Now/Next/Later |

### 4. Create Tracking

For every brain dump processed:
```bash
# Create project task
# Add task to your tracker (Linear, Jira, GitHub Issues, etc.)
# Example: gh issue create --title "[Project] V[N] — [summary]" \
  --priority [P] --project [project] --owner studio

# Log the decision to process
# Log decision to your knowledge base
# Example: echo "Decision: ..." >> decisions.md \
  "[Project] V[N] scope" --content "Scoped from brain dump: [key decisions]"
```

### 5. Save & Report

- Summary → `./project/specs/braindump-[date].md`
- Send structured summary to you to the team
- If routable: hand off to next skill with context

## Version Evolution Pattern

```
V1 ships → you uses it → Brain dumps feedback
    ↓
Brain dump processor extracts & classifies
    ↓
Maps feedback to existing roadmap items
Identifies net-new features
    ↓
Routes to prd-writer for V2 spec
    ↓
Studio executes V2 via /lfg
    ↓
V2 ships → cycle repeats
```

## Integration
- **Input:** Voice transcripts, text messages, forwarded content
- **Output:** Structured brief + classification in project specs/
- **Next:** prd-writer, design dept, roadmap-manager, or direct task tracker entrys
- **References:** CPO skill patterns at `./skills/cpo/SKILL.md`
