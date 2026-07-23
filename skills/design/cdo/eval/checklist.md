# CDO Quality Checklist

Run this checklist after generating any design spec or UI code.

## Design Spec Checklist

| # | Check | Pass/Fail |
|---|-------|-----------|
| 1 | **Color tokens defined** — All colors are tokens, not hex values in components | |
| 2 | **Spacing tokens defined** — Consistent scale (4, 8, 12, 16, 24, 32, 48, 64) | |
| 3 | **Typography scale defined** — H1-H6, body, UI text with line heights | |
| 4 | **Component states specified** — Default, hover, active, disabled, loading, error | |
| 5 | **Responsive behavior defined** — Breakpoints and layout changes | |
| 6 | **Accessibility addressed** — Contrast ratios, touch targets, focus states | |
| 7 | **Animation specs included** — Durations, easing, which properties animate | |
| 8 | **No magic numbers** — Every value traces to a token or has rationale | |
| 9 | **Implementation checklist provided** — Clear handoff to engineering | |

## UI Code Checklist

| # | Check | Pass/Fail |
|---|-------|-----------|
| 1 | **No AI tells** — No purple gradients, Inter font, 3-column grids, emoji icons | |
| 2 | **Tokens used** — CSS variables or design tokens, not hardcoded values | |
| 3 | **GPU-only animations** — Only transform, opacity, filter animated | |
| 4 | **Focus states present** — Visible keyboard navigation | |
| 5 | **Touch targets ≥44px** — Mobile-friendly interaction areas | |
| 6 | **Error states handled** — Loading, empty, error conditions considered | |
| 7 | **No defensive comments** — Code is self-documenting | |
| 8 | **Type safety** — No `any` assertions | |
| 9 | **Responsive** — Works on mobile-first, scales up | |

## Quality Gates

### Gate 1: Deslop Pass
```bash
# Run deslop skill on generated code
# All AI slop removed?
```
- [ ] Unnecessary comments removed
- [ ] Defensive checks simplified
- [ ] Style inconsistencies fixed

### Gate 2: RAMS Pass
```bash
# Run rams skill for accessibility
# WCAG 2.1 AA compliant?
```
- [ ] Color contrast ≥4.5:1 for text
- [ ] Focus indicators visible
- [ ] Semantic HTML used

### Gate 3: React Doctor Pass (if React)
```bash
npx react-doctor@latest . --verbose
# Score ≥80?
```
- [ ] No errors
- [ ] Warnings addressed or justified

### Gate 4: Human Review
```
"Would a staff engineer/designer approve this?"
```
- [ ] Premium feel, not generic
- [ ] Differentiated, not template-y
- [ ] Attention to detail evident

## Scoring

- **9/9 checks + all gates pass** = Ship it
- **7-8 checks** = Minor iteration needed
- **<7 checks** = Back to design phase

## Common Failures

| Failure | Fix |
|---------|-----|
| Missing loading states | Add skeleton screens |
| No focus styles | Add `focus-visible` outline |
| Magic numbers | Extract to tokens |
| AI purple gradient | Pick brand-appropriate colors |
| Hardcoded strings | Use i18n or constants |
