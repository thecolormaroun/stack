---
name: layout
description: "Grid systems, spacing scale, and responsive design"
---

# Layout Strategy

Grid systems, responsive design, and spacing scales.

## Skill graph entry point
Start at: `./_graph/design/layout.moc.md`

## When to Use
- Setting up page structure for a new project
- Reviewing responsive behavior
- Establishing spacing system

## Spacing Scale (8px Base)

| Token | Value | Use |
|-------|-------|-----|
| `space-1` | 4px | Tight groupings, icon padding |
| `space-2` | 8px | Related elements, input padding |
| `space-3` | 12px | Form gaps, list items |
| `space-4` | 16px | Card padding, between groups |
| `space-6` | 24px | Section padding (mobile) |
| `space-8` | 32px | Section gaps |
| `space-12` | 48px | Major section breaks |
| `space-16` | 64px | Page section spacing |
| `space-24` | 96px | Hero/feature sections |

**Rule:** Use only scale values. No magic numbers.

## Grid System

### Container Widths
| Breakpoint | Container | Columns | Gutter |
|-----------|-----------|---------|--------|
| Mobile (<640px) | 100% - 32px | 4 | 16px |
| Tablet (640-1024px) | 100% - 48px | 8 | 24px |
| Desktop (1024-1280px) | 1024px | 12 | 24px |
| Wide (1280+) | 1200px | 12 | 32px |

### Layout Patterns
```
# Full-width hero
[============================================]

# Content + sidebar (8/4)
[================================] [========]

# Three cards (4/4/4)
[==========] [==========] [==========]

# Centered content (2 + 8 + 2)
  [================================]
```

## Responsive Rules

1. **Mobile-first always** — start with mobile, enhance up
2. **Stack on mobile** — side-by-side layouts become vertical
3. **Touch targets:** 44px minimum on mobile
4. **Breakpoint content, not devices** — break when the layout breaks
5. **Hide with purpose** — don't just hide elements on mobile, restructure

## your Layout Preferences
- **Generous whitespace** — let content breathe
- **Clear visual hierarchy** — size, weight, and space create structure
- **Full-bleed images/sections** — break the container for impact
- **Sticky navigation** — always accessible
- **Cards with depth** — subtle shadows or borders, not flat
- **Max content width: 65ch** for readability on wide screens

## your Rules

From [[Visual Design Primacy]] and [[Typography Exists to Honor Content]]:

### Visual Hierarchy Creates Meaning
> "The typographic page is a map of the mind; it is frequently a map of social order."

Layout reveals relationships:
- What's important vs subordinate
- The logic and flow of thought
- How ideas relate to each other

**How to establish hierarchy:**
- Size differences signal importance
- Weight differences (bold vs regular)
- Spacing creates groupings
- Color draws attention selectively

### Shape the Page to Honor the Text
> "Shape the page and frame the text blocks so that it honors and reveals every element, every relationship between elements, and every logical nuance of the text."

Every layout decision should make the content's structure visible. Ask:
- Does this layout reveal the content's logic?
- Are relationships between elements clear?
- Would someone understand the hierarchy without reading?

### Spacing Philosophy
Use an 8px base scale religiously. No magic numbers.

**Proximity principle:** Related items should be closer together than unrelated items. The space between things tells users what belongs together.

**Breathing room:** Generous whitespace isn't wasted space—it reduces cognitive load and draws focus to what matters.

### The Invisible Design Goal
> "If the boundaries and spaces between thoughts look more important than the spaces themselves, then the typographer has failed."

The best layout is one you don't notice—you just absorb the content effortlessly. If users are noticing your design choices, something's competing with the content.
