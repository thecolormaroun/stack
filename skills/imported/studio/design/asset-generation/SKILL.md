---
name: assets
description: "AI-generated visuals using Nano Banana Pro"
---

# Asset Generation

Generate custom visual assets using AI tools for your projects.

## Skill graph entry point
Start at: `./_graph/design/assets.moc.md`

## When to Use
- Need custom icons, illustrations, or hero images
- OG images / social cards
- Placeholder art during development that looks polished

## Tools

### Nano Banana Pro (Gemini Image Gen)
Primary tool for generating images. Use the `nano-banana-pro` skill.

```bash
# Generate an image
nano-banana "A dark, futuristic dashboard interface with glowing blue accents, minimal, premium feel"
```

**Best for:** Hero images, illustrations, conceptual art, social cards
**Not ideal for:** Icons (too detailed), precise UI mockups, text in images

### Prompt Patterns for your Aesthetic
```
# Dark/sci-fi project assets
"[Subject], dark background, neon blue accents, minimal, futuristic, clean lines, high contrast"

# Lebanese/cultural elements
"[Subject], Lebanese cedar motifs, warm gold tones, geometric patterns, elegant"

# Product screenshots (enhanced)
"Clean product interface mockup, dark theme, showing [feature], premium software aesthetic"
```

### OG Image Generation
For social sharing cards:
- **Size:** 1200x630px
- **Content:** Product name + tagline + visual
- **Style:** Match project's design system colors
- Can generate with Nano Banana or build HTML → screenshot

### Icon Patterns
For app icons, prefer:
1. Simple geometric shapes
2. Mono-weight line style OR filled
3. Match the design system's accent color
4. Export as SVG when possible

## Output
- Save generated assets to `./project/assets/`
- Name clearly: `hero-dark.png`, `og-image.png`, `icon-512.png`
- Generate multiple sizes if needed (favicon, OG, hero)

## Quality Rules
- No generic stock-photo vibes
- Every asset should feel intentional and project-specific
- If AI generation looks off, iterate on the prompt (2-3 attempts)
- Human review before shipping — you approves final assets

## your Rules

From [[Taste in Product Design]] and [[Design Efficiency Killed the Magic]]:

### Taste as the Ultimate Filter
> "Taste is developing a refined sense of judgment and finding the balance that produces a pleasing and integrated whole." — Ken Kocienda

AI can generate images quickly, but taste is what separates good from great. The job isn't to accept the first output—it's to iterate until the result serves the product's overall vision.

**The taste test:** Does this asset create a pleasing, integrated whole with the rest of the design? Or does it feel disconnected?

### Magic Over Efficiency
> "When everything is measured, beauty starts to feel like waste. That's a mistake. People don't fall in love with logic, they fall in love with presence, feeling, or 'vibes'."

Don't settle for "good enough" assets. The industry optimized so hard for efficiency that we killed the magic. Brands like Linear, Framer, Notion invest in visual identity as competitive differentiation.

**What this means for assets:**
- Invest time getting it right, not just done
- Custom always beats generic
- Aesthetics signal maturity and care
- If it doesn't feel special, iterate

### Use AI to Accelerate Taste, Not Replace It
> "Visual designers who thrive in this era will be the ones who use AI to accelerate taste, not replace it."

AI is a tool for rapid exploration. Generate many options, use your taste to select and refine. The designer's judgment is irreplaceable—AI just gets you to options faster.

### Anti-Slop Standards
Every generated asset must pass these checks:
- [ ] Does it avoid generic stock-photo vibes?
- [ ] Is it intentional and project-specific?
- [ ] Does it match the design system's aesthetic?
- [ ] Would I be proud to ship this?
- [ ] Does you approve?

### Know the Difference Between Polish and Vibe
> "The next wave of great visual designers won't just know how to make things beautiful. They'll know how to make things *felt*. They know the difference between polish and vibe."

Polish = technically well-executed. Vibe = emotionally resonant.

A perfectly rendered generic image has polish but no vibe. Aim for assets that make users *feel* something—not just look professional.
