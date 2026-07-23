# RAMS Review Checklist

## Accessibility Checklist

| # | Check | Pass/Fail |
|---|-------|-----------|
| 1 | **Contrast ≥4.5:1** — Normal text passes | |
| 2 | **Keyboard navigable** — All interactions work | |
| 3 | **Focus visible** — Can see where you are | |
| 4 | **Touch targets ≥44px** — Mobile friendly | |
| 5 | **Alt text present** — Images described | |
| 6 | **Semantic HTML** — Proper headings, landmarks | |
| 7 | **Form labels** — All inputs labeled | |
| 8 | **Error messages** — Clear, in text not just color | |

## Visual Design Checklist

| # | Check | Pass/Fail |
|---|-------|-----------|
| 1 | **Hierarchy clear** — Eye knows where to go | |
| 2 | **Spacing consistent** — Uses design tokens | |
| 3 | **Typography readable** — Size, weight, line-height | |
| 4 | **Colors purposeful** — Not decorative | |
| 5 | **Animations intentional** — Guide, don't distract | |
| 6 | **Responsive** — Works at all breakpoints | |

## Rams Principles Checklist

| # | Principle | Question | Pass/Fail |
|---|-----------|----------|-----------|
| 1 | Innovative | Better way exists? | |
| 2 | Useful | Solves real problem? | |
| 3 | Aesthetic | Feels good? | |
| 4 | Understandable | Self-explanatory? | |
| 5 | Unobtrusive | Gets out of the way? | |
| 6 | Honest | No dark patterns? | |
| 7 | Long-lasting | Will age well? | |
| 8 | Thorough | Edge cases handled? | |
| 9 | Environmentally friendly | Performant? | |
| 10 | As little as possible | Nothing to remove? | |

## Performance Checklist

| # | Check | Pass/Fail |
|---|-------|-----------|
| 1 | **No layout thrash** — Animations GPU-only | |
| 2 | **Images optimized** — Right format, lazy loaded | |
| 3 | **Bundle reasonable** — No unnecessary deps | |
| 4 | **LCP <2.5s** — Largest paint fast | |

## Quality Gates

### Gate 1: Accessibility Blockers
```
Any WCAG AA violation?
```
🔴 Fix before shipping.

### Gate 2: Visual Harmony
```
"Would Dieter Rams approve?"
```
🟡 Should fix if no.

### Gate 3: Performance
```
"Does it feel fast?"
```
🟡 Should fix if sluggish.

## Severity Guide

| Severity | Meaning | Action |
|----------|---------|--------|
| 🔴 Blocker | A11y violation, unusable | Must fix |
| 🟡 Should fix | Quality issue | Fix before ship |
| 🟢 Polish | Could be better | Track for later |
