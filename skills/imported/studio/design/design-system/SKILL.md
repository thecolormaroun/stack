---
name: designsystem
description: "Design tokens, component patterns, colors, and motion"
---

# Design System

Design tokens, component library patterns, and interaction states. These are your **default starting tokens** — use them directly for quick starts, or use the CDO visual-direction skill (`./cdo/visual-direction/SKILL.md`) to create custom palettes from scratch.

## Skill graph entry point
Start at: `./_graph/design/designsystem.moc.md`

## When to Use
- Starting a new project that needs consistent design language
- Building reusable components
- Quick-start tokens when you don't need custom visual direction

## New Project Setup Workflow
1. **Start here** — copy the default tokens below as your baseline
2. **Customize colors?** → Load CDO visual-direction skill for brand-specific palettes
3. **Customize type?** → Load typography skill for font pairing and scale adjustments
4. **Layout decisions?** → Load layout-strategy skill for grid and spacing
5. **Generate `tailwind.config.js`** with all tokens combined
6. Save project tokens to `./project/design-tokens.css`

## Color Tokens

### Dark Theme (Default)
```css
--bg-primary: #0A0A0B;      /* App background */
--bg-secondary: #141416;     /* Card/surface */
--bg-tertiary: #1C1C1F;      /* Elevated surface */
--bg-hover: #242428;          /* Interactive hover */

--text-primary: #F0F0F0;     /* Main text */
--text-secondary: #A0A0A8;   /* Supporting text */
--text-tertiary: #606068;    /* Disabled/muted */

--border-default: #2A2A30;   /* Subtle borders */
--border-strong: #404048;    /* Emphasis borders */

--accent: #3B82F6;           /* Primary action (blue) */
--accent-hover: #2563EB;     /* Primary hover */
--success: #22C55E;
--warning: #F59E0B;
--error: #EF4444;
```

### Light Theme
```css
--bg-primary: #FFFFFF;
--bg-secondary: #F8F8FA;
--bg-tertiary: #F0F0F2;
--text-primary: #111111;
--text-secondary: #6B6B76;
--accent: #2563EB;
```

## Component Tokens

| Token | Value | Use |
|-------|-------|-----|
| `radius-sm` | 6px | Buttons, inputs |
| `radius-md` | 10px | Cards, dropdowns |
| `radius-lg` | 16px | Modals, large surfaces |
| `radius-full` | 9999px | Pills, avatars |
| `shadow-sm` | 0 1px 2px rgba(0,0,0,0.1) | Subtle lift |
| `shadow-md` | 0 4px 12px rgba(0,0,0,0.15) | Cards |
| `shadow-lg` | 0 8px 24px rgba(0,0,0,0.2) | Modals, popovers |

## Component Patterns

### Buttons
- **Primary:** Filled accent, white text, hover darkens
- **Secondary:** Ghost/outline, accent border, accent text
- **Destructive:** Red fill for dangerous actions
- **Sizes:** sm (32px), md (40px), lg (48px)
- **States:** default, hover, active, disabled, loading

### Cards
- Background: `bg-secondary`
- Border: `border-default` (1px)
- Padding: `space-4` to `space-6`
- Radius: `radius-md`
- Hover: Subtle border color change or shadow lift

### Inputs
- Height: 40px (md), 32px (sm)
- Border: `border-default`, focus: `accent`
- Radius: `radius-sm`
- Padding: 12px horizontal

## Motion Tokens
```css
--duration-fast: 100ms;    /* Micro-interactions */
--duration-normal: 200ms;  /* State changes */
--duration-slow: 350ms;    /* Entrances/exits */
--easing-default: cubic-bezier(0.4, 0, 0.2, 1);
--easing-bounce: cubic-bezier(0.34, 1.56, 0.64, 1);
```

Use Motion.dev (`motion/react`) for React animations. Never CSS animations for complex sequences.

## Anti-Slop Rules (from compound-engineering)
- No placeholder content in production
- No lorem ipsum that ships
- No generic stock-photo vibes
- No gratuitous gradients or glassmorphism without purpose
- Every visual choice should have a reason

## Related Skills
- **CDO visual-direction** (`./cdo/visual-direction/`) — Deep custom color/brand direction from scratch
- **typography** (`./design/typography/`) — Font pairing, type scale, readability
- **layout-strategy** (`./design/layout-strategy/`) — Grid, spacing, responsive
- **ux-patterns** (`./design/ux-patterns/`) — Interaction patterns, accessibility
- **asset-generation** (`./design/asset-generation/`) — AI-generated visuals

## your Rules

From [[Atomic Design]], [[Build Once Use Everywhere]], and [[Systems and Modularity Lead to Quality at Scale]]:

### Systems Enable Excellence at Scale
> "We make long-term investments into brand, UI patterns, and process such that we never lose track of quality, craft, and delight at scale. With great assets, we can focus on composition." — Henry Modisett (OpenAI)

Quality doesn't survive scale by accident. Systems encode quality into the infrastructure itself—they free designers to focus on composition rather than construction.

### Build Once, Use Everywhere
Build components with the explicit goal of reusing them everywhere, not just the immediate use case.

**The math:**
- One-off component: 30 min × 10 features = 300 min of button building
- Reusable component: 2 hours initially, used 50 times = massive savings

**Tipping point:** Usually after 3-4 uses, reusability pays for itself.

**When building, ask:**
- "Will we need this pattern again?"
- "What variations might we need?"
- "Can this work for both use cases X and Y?"
- "Is this flexible enough without being too flexible?"

**Red flags:**
- "We'll make it reusable later" (you won't)
- Copying components instead of using existing
- "This use case is unique" (rarely true)

### Atomic Design Hierarchy
Break interfaces into fundamental building blocks:

| Level | Description | Examples |
|-------|-------------|----------|
| **Atoms** | Most basic, cannot be broken down | Buttons, inputs, labels, icons |
| **Molecules** | Combination of atoms | Search bar (input + button + icon) |
| **Organisms** | Complex combinations of molecules | Navigation bar, form sections |
| **Templates** | Page blueprints, content-agnostic | Wireframe-level layouts |
| **Pages** | Templates filled with real content | What users actually see |

**Why this matters:**
- Build complexity systematically
- Reuse at every level
- Consistency by default
- Fix once, fixed everywhere

### What Makes Components Reusable
1. **Flexible but opinionated** — props for common variations, constraints that enforce consistency
2. **Well-documented** — when to use, props, examples
3. **Production-ready** — all states handled (loading, error, empty, success), accessibility built in, edge cases considered

### UX and UI Cannot Be Separated
> "Your UI directly affects the UX. Visual design isn't decorative—it's functional."

The idea of having "UX designers" hand off to "UI designers" is outdated. Button hierarchy affects what users click. Color draws attention. Typography affects trust. Spacing affects cognitive load.

Integrated ownership = faster iteration + coherent products.
