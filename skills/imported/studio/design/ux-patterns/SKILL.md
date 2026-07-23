---
name: ux
description: "User flows, interaction patterns, and accessibility"
---

# UX Patterns

User flows, interaction patterns, and accessibility standards.

## Skill graph entry point
Start at: `./_graph/design/design.moc.md` and follow links (progressive disclosure).
- If this is a high-stakes flow, see: `./_graph/design/patterns/studio.design.patterns.premium-interaction-patterns.md`

## When to Use
- Designing user flows and navigation
- Reviewing interaction patterns for consistency
- Ensuring accessibility compliance

## Navigation Patterns

### App Navigation
- **Sidebar** (desktop) → **Bottom tabs** (mobile) for apps
- **Top nav** for marketing/content sites
- Max 5-7 top-level items
- Active state must be visually obvious

### Page Transitions
- Use shared layout animations (Motion.dev `layoutId`)
- Maintain scroll position on back navigation
- Show loading skeletons, not spinners (content-shaped placeholders)

## Interaction Patterns

### Forms
- **Inline validation** — validate on blur, not keystroke
- **Error messages** below the field, not in toasts
- **Submit button** shows loading state, prevents double-submit
- **Success** — redirect or clear with confirmation, not just a toast
- **Autosave** for long forms (debounced 1-2s)

### Lists & Tables
- **Empty states** — always design them (illustration + CTA)
- **Loading** — skeleton rows matching data shape
- **Pagination** vs **infinite scroll** — paginate for data-heavy, infinite for feeds
- **Sort/filter** — persist in URL params for shareability
- **Bulk actions** — checkbox select + floating action bar

### Modals & Overlays
- **Confirm destructive actions** — "Delete X?" with explicit action name
- **Escape to close** — always
- **Focus trap** — keyboard focus stays in modal
- **Backdrop click** to close (except for important forms)

### Feedback
- **Optimistic updates** — show change immediately, rollback on error
- **Toast notifications** — auto-dismiss (5s), manual dismiss for errors
- **Progress indicators** — determinate when possible, indeterminate only when unknown

## Accessibility (WCAG 2.1 AA)

### Must-Have
- **Color contrast:** 4.5:1 body text, 3:1 large text/UI
- **Keyboard navigation:** All interactive elements focusable, logical tab order
- **Focus indicators:** Visible focus rings (don't remove outlines)
- **Alt text:** All images, icons have labels
- **ARIA labels:** Interactive elements without visible text
- **Reduced motion:** Respect `prefers-reduced-motion`

### Testing
```bash
# Lighthouse accessibility audit
npx lighthouse <url> --only-categories=accessibility
```

## your UX Preferences
- Speed over perfection — fast interactions feel premium
- Progressive disclosure — don't overwhelm, reveal complexity gradually
- Keyboard shortcuts for power users
- Dark/light toggle accessible from any page
- Data density on desktop, simplicity on mobile

## your Rules

From [[System 1 vs System 2]], [[One Thing at a Time]], [[Celebratory Moments]], and [[Design for Emotional Barriers]]:

### Design for System 1, Not System 2
> "Most tools for thought assume users operate in System 2 mode—rational, deliberate. In reality, most daily work happens in System 1—reactive, panicky, just trying to keep up."

Your users aren't thinking deeply. They're over-promised, late to meetings, struggling with their inbox. Design for overwhelmed, reactive users—not idealized ones. If your product requires System 2 engagement to work, users will abandon it.

**What this means:**
- Minimize setup and configuration
- Default to useful behavior
- Work automatically in background
- Don't require ongoing maintenance
- Capture value even when user is distracted

### One Thing at a Time
Present users with a single clear action or piece of information at each step. Cognitive overload kills momentum.

**How to apply:**
- One question per screen (especially for complex/emotional info)
- Hide optional fields until core info is complete
- Primary action should be obvious, secondary actions de-emphasized
- Remove competing CTAs on critical flows

**When to break this rule:** Dashboards (users need overview), power user tools (experts want density), comparison tasks.

### Build Momentum
Show users their progress with every action. Each completed step should visibly move them forward.

**Momentum builders:**
- Progress bars (works best when finite and accurate)
- Step counters (3 of 7 complete)
- Checkmarks appearing, sections collapsing as "done"
- Encouraging copy ("Great! You're halfway there")
- Start with easiest questions to build confidence

### Celebratory Moments
> "An application is a conversation. Break work into thematic sections, and when those sections are complete, create celebratory moments."

Long flows without breaks create fatigue. Strategic pauses with positive reinforcement re-energize users.

**Where to celebrate:**
- After completing thematically related sections
- Before context switches (financial info → personal info)
- After difficult or emotional sections
- Natural mental breakpoints

**Restraint:** Don't celebrate trivial actions. Don't interrupt flow state unless section is truly complete.

### Design for Emotional Barriers
> "There's a bigger emotional challenge than a functional challenge in many product experiences."

You can have perfect UX functionally—clear buttons, logical flow—and users will still abandon if emotional barriers are too high.

**Common emotional barriers:**
- Shame/inadequacy ("I should understand this better")
- Anxiety/fear (fear of wrong decisions, exposing sensitive info)
- Overwhelm (too much new information at once)

**How to address:**
- Acknowledge difficulty: "Many people find this confusing—here's a simple explanation"
- Build confidence progressively (start with easy wins)
- Reduce stakes: "You can change this later"
- Give space for difficult decisions
- Don't be playful about serious topics

### Calm Confidence Over Delight
> "We don't design for delight—we design to create calm and confidence. Respect you and the seriousness of their task."

**When users arrive feeling anxious:**
- Delightful design says: "This is fun and easy!" (feels dismissive)
- Calm confident design says: "This matters, and we'll help you get it right"

**When delight IS appropriate:**
- After major accomplishments (celebration moments)
- In non-critical flows (browsing, exploring)
- When user is already confident
- In tools used daily (can afford personality)
