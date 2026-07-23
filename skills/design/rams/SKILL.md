---
name: rams
description: Accessibility and visual design review inspired by Dieter Rams. "Good design is as little design as possible."
---

# RAMS Skill

Accessibility + visual design review. Named after Dieter Rams.

**Philosophy:** "Good design is as little design as possible." Focus on what's essential.

---

## Workflow

Use this review process:

1. Read the requested file before making assessments.
2. Run the accessibility audit against WCAG 2.1 AA.
3. Run the visual-design audit against the Rams principles.
4. Report findings with severity, exact line references, and concrete fixes.

---

## WCAG Checks

Read `instructions/wcag-checklist.md` for:
- Color contrast (4.5:1 text, 3:1 UI)
- Keyboard navigation
- Focus indicators
- Screen reader support
- Touch targets (44px min)

Prioritize these failures:

| Severity | Check |
|---|---|
| Blocker | Images without useful alt text; icon-only buttons without an accessible name; inputs without labels; non-semantic click targets without keyboard behavior; links without destinations. |
| Should fix | Removed focus outlines without replacement; missing keyboard handlers; color-only status; undersized touch targets. |
| Consider | Broken heading hierarchy; positive `tabIndex`; ARIA roles missing required attributes. |

---

## Rams Principles

Read `instructions/rams-principles.md` for the 10 principles:
1. Innovative
2. Useful
3. Aesthetic
4. Understandable
5. Unobtrusive
6. Honest
7. Long-lasting
8. Thorough
9. Environmentally friendly
10. As little design as possible

---

## After Review

Run `eval/checklist.md`:
- WCAG compliance checks
- Visual design checks
- Performance checks

The report must group blocker, should-fix, and polish findings; include a short summary count; and offer implementation only when the user asked for fixes. Do not report generic taste preferences as accessibility violations.

---

## Quick Commands

| Severity | Meaning |
|----------|---------|
| 🔴 Blocker | Must fix — accessibility violation |
| 🟡 Should fix | Quality suffers without it |
| 🟢 Polish | Nice to have improvement |
