# CPO Advisory Board

After generating a PRD, run it through these three reviewer personas in parallel.

## The Reviewers

### 1. 🎯 The PM (Shreyas)
**Perspective:** Product strategy, prioritization, user value
**Asks:**
- Is the problem worth solving?
- Are we building the right thing for the right users?
- Is the scope realistic for this version?
- Will we learn something valuable from shipping this?

**Red flags:**
- "This doesn't solve a real problem"
- "Scope is too ambitious for V1"
- "No clear success metric"
- "Features don't connect to user outcomes"

### 2. 🛠️ The Builder (Kent)
**Perspective:** Implementation feasibility, technical risk, story quality
**Asks:**
- Can each story be implemented in one context window?
- Are dependencies correctly ordered?
- Are acceptance criteria verifiable?
- Is there hidden complexity in any story?

**Red flags:**
- "This story is too big"
- "Missing dependency on X"
- "AC is vague — how do I know when it's done?"
- "This will require changes across many files"

### 3. 👤 The User (Mom)
**Perspective:** Real-world usability, edge cases, confusion
**Asks:**
- Would a normal person understand this feature?
- What happens when things go wrong?
- Are we missing obvious use cases?
- Will this actually get used?

**Red flags:**
- "I don't understand what this does"
- "What if I accidentally tap this?"
- "Where did my data go?"
- "This seems like a lot of steps"

## Review Protocol

1. **Present the PRD** — Full document including stories
2. **Each reviewer evaluates** — Identify 0-3 issues from their lens
3. **Severity rating:**
   - 🔴 **Blocker** — PRD fails, must fix
   - 🟡 **Should fix** — Quality/success suffers without it
   - 🟢 **Nice to have** — Polish item
4. **Synthesize feedback** — Prioritize blockers first
5. **Iterate** — Address feedback, re-review if blockers existed

## Example Review

**Artifact:** Noah's Noms V3 PRD — Meal Planning

**Shreyas (PM):**
- 🟡 "No success metric for meal planning — how do we know if it worked?"
- 🟢 "Consider a simpler V3.0 before full meal planning (V3.1)"

**Kent (Builder):**
- 🔴 "US-005 is XL — 'implement entire meal planning UI' needs splitting"
- 🟡 "US-003 depends on US-004 but US-004 comes after — reorder"

**Mom (User):**
- 🔴 "What if I don't want to meal plan? Can I skip it?"
- 🟡 "How do I know what to buy at the store?"

**Synthesis:**
- 2 blockers: Story too big + missing opt-out path
- 3 should-fix: Success metric, dependency order, shopping list
- 1 nice-to-have: Version scope advice

**Action:** Split US-005, add skip option, fix order, add metric.

## When to Skip

- Quick fixes or bug-only releases
- Internal tooling (but still need Builder review)
- Experiments with explicit "learning" goal

Never skip for:
- User-facing features
- Features affecting data
- V1 of any product
