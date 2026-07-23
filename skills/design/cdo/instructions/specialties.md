# Design Specialties

CDO orchestrates multiple design specialties. Load the appropriate skill based on work type:

## 🎯 Visual Direction (`visual-direction/SKILL.md`)
**When to use:** Brand direction, color palette, mood, visual hierarchy
- Color theory and accessible palettes
- Visual hierarchy and emphasis
- Brand personality and tone
- Inspiration mining from references

## 📝 Typography (`typography/SKILL.md`)
**When to use:** Type scale, font pairing, readability optimization
- Type scale and rhythm
- Font pairing and hierarchy
- Readability for different contexts (mobile, web, print)
- Accessibility considerations

## 📐 Layout Strategy (`layout-strategy/SKILL.md`)
**When to use:** Grid systems, spacing, responsive design
- Grid systems and breakpoints
- Spacing scales and rhythm
- Responsive behavior patterns
- Component composition rules

## 🎨 Design System (`design-system/SKILL.md`)
**When to use:** Component libraries, design tokens, systematic design
- Design token architecture
- Component specifications
- Interaction states and animations
- Cross-platform consistency

## 🤝 UX Patterns (`ux-patterns/SKILL.md`)
**When to use:** User flows, interaction patterns, accessibility
- Navigation patterns and information architecture
- Form design and input patterns
- Accessibility guidelines (WCAG compliance)
- Mobile-first interaction patterns

## 🛡️ UI/UX Pro Max (`ui-ux-pro-max/SKILL.md`)
**When to use:** Project kickoff — generates industry-specific design systems
- 67 UI styles with industry matching
- 96 color palettes by industry with accessibility ratios
- 57 curated font pairings with Google Fonts links
- Design system generator: `python3 scripts/design_system.py "description"`

## 🎨 Taste Skill (`taste-skill/SKILL.md`)
**When to use:** During implementation — enforces premium code quality
- Control dials: DESIGN_VARIANCE, MOTION_INTENSITY, VISUAL_DENSITY
- "100 AI Tells" ban list (Inter font, purple gradients, centered heroes)
- Framer Motion best practices
- Performance guardrails

## Integration Skills

| Skill | Purpose |
|-------|---------|
| `deslop/` | Post-build: removes AI comments, defensive checks |
| `simplify/` | Code refinement: clarity, naming, nesting reduction |
| `rams/` | WCAG accessibility + Dieter Rams visual design review |
| `react-doctor/` | React health scan (47+ rules, 0-100 score) |
| `favicon/` | Complete favicon generation from source image |
