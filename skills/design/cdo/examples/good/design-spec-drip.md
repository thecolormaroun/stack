# Example: Drip v2 Design Spec (Good)

This design spec demonstrates CDO workflow executed well.

## What Makes This Good

1. **Clear visual foundation** — Dark theme (#000000), single accent (lime #C8FF00), purpose-driven color
2. **Systematic tokens** — Every color, spacing, and typography value is a token, not a magic number
3. **Component-driven** — Each card has explicit specs: dimensions, states, data format
4. **Accessibility considered** — WCAG AA contrast ratios, 44px touch targets, semantic HTML
5. **Animation philosophy** — Spring physics, GPU-only transforms, explicit durations

## Design Spec Excerpt

### Color Tokens
```css
--background: #000000;
--surface: #111111;
--surface-elevated: #1a1a1a;
--accent-primary: #C8FF00;  /* Lime — primary actions, positive metrics */
--accent-secondary: #7B68EE; /* Purple — sleep data */
--accent-tertiary: #4488FF;  /* Blue — hydration, water */
--semantic-warning: #FFD700; /* Amber — caution states */
--semantic-danger: #FF4444;  /* Red — negative trends, alerts */
```

### Card Component Spec
```
## Component: MetricCard

Purpose: Display a single health metric with trend visualization
Context: Dashboard grid, 3-column layout on desktop

Dimensions:
- Min-width: 200px
- Padding: 24px
- Border-radius: 16px
- Background: var(--surface)

States:
- Default: surface background, white text
- Hover: subtle glow (box-shadow with accent at 10% opacity)
- Loading: skeleton pulse animation

Typography:
- Metric value: 48px, weight 600, var(--text-primary)
- Label: 14px, weight 400, var(--text-secondary)
- Trend: 12px, weight 500, colored by direction
```

### Animation Spec
```
Transitions:
- Hover states: 150ms ease-out
- Page transitions: 300ms spring (stiffness: 300, damping: 30)
- Chart reveals: staggered 50ms per element

GPU-only properties:
- transform (scale, translate)
- opacity
- filter (for blur effects only)

Never animate:
- width/height
- margin/padding
- top/left/right/bottom
```

## Why This Worked

- Designer could implement without questions
- Developer knew exact values and behaviors
- QA could verify against spec
- Future changes have clear token to update
