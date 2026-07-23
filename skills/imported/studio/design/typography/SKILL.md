---
name: typography
description: "Type scale, font pairing, and readability rules"
---

# Typography

Type scale, font pairing, and readability rules for your projects.

## Skill graph entry point
Start at: `./_graph/design/typography.moc.md`

## When to Use
- Setting up a new project's type system
- Reviewing text hierarchy and readability
- `/design` when typography decisions needed

## Type Scale (Default)

Based on a 1.25 ratio (Major Third), optimized for screen:

| Token | Size | Weight | Line Height | Use |
|-------|------|--------|-------------|-----|
| `display` | 3rem (48px) | 700 | 1.1 | Hero headlines |
| `h1` | 2.25rem (36px) | 700 | 1.2 | Page titles |
| `h2` | 1.75rem (28px) | 600 | 1.25 | Section heads |
| `h3` | 1.375rem (22px) | 600 | 1.3 | Sub-sections |
| `body` | 1rem (16px) | 400 | 1.6 | Body text |
| `body-sm` | 0.875rem (14px) | 400 | 1.5 | Secondary text |
| `caption` | 0.75rem (12px) | 500 | 1.4 | Labels, metadata |

## Font Pairing Rules

### your Preferred Stack
- **Headlines:** Geometric sans (Inter, Geist, Satoshi)
- **Body:** Humanist sans or system stack
- **Mono:** JetBrains Mono, Geist Mono, or Fira Code
- **Display/accent:** Variable width fonts for impact

### Pairing Principles
1. **Max 2 families** — one for headings, one for body (mono is free)
2. **Contrast in style, harmony in proportion** — pair geometric + humanist, not two geometrics
3. **Variable fonts preferred** — fewer requests, more flexibility
4. **System fonts for performance** — use when custom fonts aren't worth the load

## Readability Rules
- **Body text:** 16px minimum, 1.5-1.6 line height
- **Line length:** 45-75 characters (max-width: 65ch recommended)
- **Paragraph spacing:** 1em minimum between paragraphs
- **Dark mode:** Reduce font weight slightly (optical adjustment), use off-white (#E5E7EB not #FFFFFF)
- **Contrast:** WCAG AA minimum (4.5:1 body, 3:1 large text)

## Implementation (Tailwind)
```js
// tailwind.config.js
fontSize: {
  'display': ['3rem', { lineHeight: '1.1', fontWeight: '700' }],
  'h1': ['2.25rem', { lineHeight: '1.2', fontWeight: '700' }],
  'h2': ['1.75rem', { lineHeight: '1.25', fontWeight: '600' }],
  'h3': ['1.375rem', { lineHeight: '1.3', fontWeight: '600' }],
  'body': ['1rem', { lineHeight: '1.6', fontWeight: '400' }],
  'body-sm': ['0.875rem', { lineHeight: '1.5', fontWeight: '400' }],
  'caption': ['0.75rem', { lineHeight: '1.4', fontWeight: '500' }],
}
```

## your Rules

From [[Typography Exists to Honor Content]] and [[The Elements of Typographic Style]]:

### The Core Principle
> "Typography exists to honor content." — Bringhurst

All typographic decisions serve one purpose: reveal and honor the text's meaning, not showcase the designer's skill. Typography should be invisible infrastructure—if you're noticing the design, you're not absorbing the content.

### Always Do This
1. **Read the text before designing it** — can't honor what you don't understand
2. **Discover outer logic in inner logic** — the text tells you how it wants to be designed
3. **Use REM, not PX** — respect user accessibility settings, respect user agency

### Typography Rules
- **66 characters per line** is ideal measure (balance between choppy and hard to track)
- **Single word space between sentences** — not two
- **Indent only if preceded by another paragraph** — no need if preceded by heading/image
- **Dark faces need more line height** than light ones
- **Block quotes**: Change ONE thing (face type, size, OR indent) — one is more than enough

### The Test
> "If the boundaries and spaces between thoughts look more important than the spaces themselves, then the typographer has failed."

Ask: Is the reader noticing my design or absorbing the content? Good typography = effortless. Bad typography = visible.

### Why This Matters
The typographic page is a map of the mind. It reveals how ideas relate, what's important vs subordinate, the logic and flow of thought. Shape the page to honor every element and every relationship in the text.
