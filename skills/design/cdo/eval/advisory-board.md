# CDO Advisory Board

After generating a design spec or UI code, run it through these three reviewer personas in parallel. Each brings a different lens.

## The Reviewers

### 1. 🎨 The Designer (Jony)
**Perspective:** Visual craft, attention to detail, emotional impact
**Asks:**
- Does this feel premium or generic?
- Is there visual hierarchy? Where does the eye go first?
- Are the animations purposeful or decorative?
- Would I be proud to put this in a portfolio?

**Red flags:**
- "It works but feels flat"
- "The spacing is inconsistent"
- "This looks like every other app"
- "The colors don't evoke the right emotion"

### 2. 👩‍💻 The Engineer (Grace)
**Perspective:** Implementation quality, performance, maintainability
**Asks:**
- Can I implement this without guessing?
- Are the specs complete enough to build?
- Will this perform well? (GPU animations, no layout thrash)
- Is the component structure sensible?

**Red flags:**
- "What happens on mobile?"
- "These values don't follow a system"
- "This animation will cause jank"
- "I need to know the error states"

### 3. 🧑‍🦯 The Advocate (Ada)
**Perspective:** Accessibility, inclusivity, edge cases
**Asks:**
- Can a keyboard user navigate this?
- Do the colors have sufficient contrast?
- Are touch targets large enough?
- Does this work with screen readers?

**Red flags:**
- "No focus indicators"
- "Contrast ratio is below 4.5:1"
- "Touch targets are too small"
- "This relies on color alone to convey meaning"

## Review Protocol

1. **Present the artifact** — Design spec or UI code
2. **Each reviewer evaluates** — Identify 0-3 issues from their lens
3. **Severity rating:**
   - 🔴 **Blocker** — Must fix before shipping
   - 🟡 **Should fix** — Quality suffers without it
   - 🟢 **Nice to have** — Polish item
4. **Synthesize feedback** — Prioritize blockers, then should-fix
5. **Iterate** — Address feedback, re-review if blockers existed

## Example Review

**Artifact:** Dashboard card component spec

**Jony (Designer):**
- 🟡 "The hover state is too subtle — increase shadow spread"
- 🟢 "Consider a micro-animation on the trend indicator"

**Grace (Engineer):**
- 🔴 "Missing loading state spec — I don't know what to show"
- 🟡 "The responsive breakpoint behavior isn't defined"

**Ada (Advocate):**
- 🔴 "No focus state for keyboard navigation"
- 🟡 "The trend color (green/red) needs an icon or label for colorblind users"

**Synthesis:**
- 2 blockers: loading state + focus state
- 3 should-fix: hover state, responsive, colorblind support
- 1 nice-to-have: trend animation

**Action:** Fix blockers, iterate, then address should-fix items.

## When to Skip

- Quick prototypes (but tag as "not reviewed")
- Internal tools (but still need accessibility basics)
- Experiments/spikes (but note known gaps)

Never skip for:
- User-facing features
- Shipped products
- Design system components
