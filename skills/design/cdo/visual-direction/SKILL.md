---
name: visual-direction
description: "Establish visual brand direction, color palettes, mood, and aesthetic foundation for design projects. References Maroun's curated taste profile and design inspiration to create cohesive visual identity."
parent: cdo
---

# Visual Direction Skill

Establish the visual foundation for any design project. You translate product personality and user needs into concrete visual decisions: color palettes, visual hierarchy, brand expression, and aesthetic mood.

**Core competency:** Creating visual languages that feel premium, intentional, and aligned with Maroun's design sensibility.

---

## When to Load This Skill

- **Brand Direction**: Establishing visual personality for new products
- **Color Strategy**: Creating accessible, cohesive color palettes  
- **Visual Hierarchy**: Defining emphasis and information priority
- **Aesthetic Foundation**: Setting the visual mood and style direction
- **Reference Integration**: Mining inspiration from curated references

---

## Visual Foundation Framework

### 1. Brand Personality Assessment

Translate product goals into visual personality:

| Product Goal | Visual Personality | Color Direction | Visual Weight |
|-------------|-------------------|----------------|---------------|
| **Trust & Reliability** | Professional, Confident | Blues, Grays | Medium-Bold |
| **Approachability** | Friendly, Warm | Earth tones, Soft colors | Light-Medium |
| **Innovation** | Modern, Dynamic | Bold colors, High contrast | Bold |
| **Premium Experience** | Sophisticated, Refined | Muted tones, Rich accents | Medium, Elegant |
| **Efficiency** | Clean, Minimal | Monochromatic, Single accent | Light |

### 2. Color Psychology & Application

#### Primary Color Selection
Consider the emotional and functional impact:

```scss
// Primary Brand Color Criteria
--primary-accessibility: [Must pass AA contrast ratio (4.5:1) against white]
--primary-uniqueness: [Differentiated from major competitors]  
--primary-versatility: [Works across light/dark themes]
--primary-psychology: [Supports intended brand personality]
```

#### Color Palette Architecture

**Foundation Palette** (5 colors max):
```scss
--color-primary: [Brand identity color]
--color-secondary: [Supporting/accent color]  
--color-neutral-base: [Primary text/background]
--color-success: [Positive actions/feedback]
--color-error: [Warnings/errors]
```

**Extended Palette** (for complex interfaces):
```scss
// Neutral Scale (9 steps)
--color-neutral-50: [Lightest backgrounds]
--color-neutral-100: [Light backgrounds] 
--color-neutral-200: [Subtle borders]
--color-neutral-300: [UI element borders]
--color-neutral-400: [Disabled text]
--color-neutral-500: [Secondary text] 
--color-neutral-600: [Primary text light]
--color-neutral-700: [Primary text]
--color-neutral-900: [Darkest elements]

// Primary Scale (5 steps)  
--color-primary-100: [Light backgrounds/hover]
--color-primary-300: [Borders/inactive states]
--color-primary-500: [Main brand color]
--color-primary-700: [Hover/active states]
--color-primary-900: [High contrast text]
```

### 3. Visual Hierarchy Principles

#### Information Priority Levels
1. **Primary**: Hero content, main CTAs, critical information
2. **Secondary**: Supporting content, secondary actions
3. **Tertiary**: Meta information, labels, captions

#### Hierarchy Techniques
| Priority | Color | Size | Weight | Spacing |
|----------|-------|------|--------|---------|
| **Primary** | High contrast | Large | Bold | Generous |
| **Secondary** | Medium contrast | Medium | Regular-Medium | Moderate |
| **Tertiary** | Low contrast | Small | Regular | Tight |

---

## Color System Generation

### Accessibility-First Approach

Always validate color choices against WCAG AA standards:

```javascript
// Contrast Ratio Requirements
Normal Text (16px+): 4.5:1 minimum contrast
Large Text (24px+): 3:1 minimum contrast  
UI Components: 3:1 minimum contrast
```

### Brand Color Development Process

1. **Define Core Brand Color** 
   - Start with primary brand color (500 level)
   - Validate accessibility against white/dark backgrounds
   - Adjust hue/saturation if needed

2. **Generate Color Scale**
   - Create 5-9 tints and shades
   - Maintain consistent perceived lightness steps
   - Test contrast ratios at each level

3. **Select Complementary Colors**
   - Choose secondary color (complementary or analogous)
   - Validate harmony with primary palette
   - Ensure sufficient differentiation for various use cases

4. **Add Semantic Colors**
   - Success (green family, but test against brand)
   - Warning (yellow/orange, ensure visibility)  
   - Error (red family, accessible and clear)

### Color Palette Template

Generate color specifications in this format:

```scss
/* [Project Name] Color Palette */
/* Generated: [Date] by R2 CDO Visual Direction */

/* Primary Brand Colors */
--color-primary-50: #[hex] /* Background tint */
--color-primary-100: #[hex] /* Light backgrounds */ 
--color-primary-200: #[hex] /* Subtle UI elements */
--color-primary-300: #[hex] /* Borders, inactive */
--color-primary-400: #[hex] /* Muted text */
--color-primary-500: #[hex] /* Main brand color */
--color-primary-600: #[hex] /* Hover states */
--color-primary-700: #[hex] /* Active states */
--color-primary-800: #[hex] /* High emphasis */
--color-primary-900: #[hex] /* Maximum contrast */

/* Neutral Grays */
--color-neutral-50: #[hex]   /* Lightest background */
--color-neutral-100: #[hex]  /* Light background */
--color-neutral-200: #[hex]  /* Subtle borders */
--color-neutral-300: #[hex]  /* UI element borders */
--color-neutral-400: #[hex]  /* Disabled text */
--color-neutral-500: #[hex]  /* Secondary text */
--color-neutral-600: #[hex]  /* Primary text on light */
--color-neutral-700: #[hex]  /* Primary text */
--color-neutral-800: #[hex]  /* High contrast text */
--color-neutral-900: #[hex]  /* Maximum contrast */

/* Semantic Colors */
--color-success: #10b981    /* Green-500 equivalent */
--color-warning: #f59e0b    /* Amber-500 equivalent */
--color-error: #ef4444      /* Red-500 equivalent */
--color-info: #3b82f6       /* Blue-500 equivalent */

/* Usage Examples */
/* 
Background: neutral-50, neutral-100
Text: neutral-700, neutral-900  
Borders: neutral-200, neutral-300
Interactive: primary-500, primary-600 (hover)
Success states: success
Destructive: error
*/
```

---

## Reference Integration System

### Curating Visual Inspiration

When Maroun adds design references to `references/`, categorize and integrate:

#### Reference Categories
```
references/
├── color-palettes/       ← Inspiring color combinations
├── visual-hierarchy/     ← Examples of effective information design  
├── brand-personalities/  ← Visual brand expressions to learn from
├── interface-patterns/   ← UI patterns and layouts
└── typography-pairing/   ← Font combinations and type treatments
```

#### Reference Analysis Template
```markdown
## Reference: [Source/Title]
**URL/Source:** [Link or attribution]
**Category:** [color-palettes|visual-hierarchy|etc]
**Added:** [Date]

### What Works
- [Specific design element that works well]
- [Another effective aspect]

### Applicable Patterns
- [How this could apply to our projects]  
- [Specific technique to adopt/adapt]

### Color Analysis (if relevant)
- **Primary Colors:** [Hex codes]
- **Contrast Ratios:** [Accessibility notes]
- **Harmony:** [Color theory explanation]

### Typography Notes (if relevant)
- **Fonts Used:** [Font families]
- **Hierarchy:** [How typography creates information priority]
- **Readability:** [What makes the type effective]
```

### Inspiration Mining Process

When generating visual direction for a project:

1. **Search References** for relevant inspiration
2. **Extract Patterns** that apply to current project needs
3. **Adapt (Don't Copy)** — use inspiration to inform original decisions  
4. **Document Rationale** — explain how references influenced choices

---

## Lebanese Design Sensibility

Integrate Maroun's cultural aesthetic background:

### Visual Characteristics
- **Rich, warm color palettes** — Drawing from Mediterranean and Middle Eastern color traditions
- **Generous whitespace** — Influenced by Arabic calligraphy's relationship with space  
- **Sophisticated typography** — Appreciation for both Latin and Arabic letterform beauty
- **Pattern and texture** — Subtle references to architectural and textile traditions
- **Hospitality through design** — Welcoming, generous, premium but not pretentious

### Implementation Guidelines
- **Color warmth** — Prefer warm grays over cool grays unless specifically needed
- **Accent colors** — Rich jewel tones, warm metallics, deep earth tones as options
- **Spatial rhythm** — More generous spacing than minimal Western trends
- **Detail orientation** — Fine attention to micro-interactions and visual refinement

---

## Output Specifications

### Visual Direction Document
```markdown
# Visual Direction: [Project Name]

## Brand Personality
**Primary Traits:** [3-4 personality words]
**Visual Mood:** [Description of intended feeling/atmosphere]
**Differentiation:** [How this stands apart from competitors]

## Color Strategy
[Generated color palette with usage guidelines]

## Visual Hierarchy
**Primary Elements:** [Color, size, weight specifications]
**Secondary Elements:** [Supporting visual specifications]  
**Tertiary Elements:** [Detail and metadata specifications]

## Reference Integration
**Inspiration Sources:** [Key references that influenced decisions]
**Adaptation Notes:** [How inspiration was interpreted for this project]

## Technical Specifications
**Accessibility:** [Contrast ratios and compliance notes]
**Responsive Considerations:** [How colors/hierarchy adapt across devices]
**Dark Mode:** [Color adaptations if needed]

## Next Steps
- [ ] Integrate with typography skill for complete type + color system
- [ ] Apply to layout strategy for spatial relationships
- [ ] Validate with UX patterns for interactive element styling
```

---

## Quality Checklist

Before finalizing visual direction:

### Accessibility Validation
- [ ] All text-background combinations pass WCAG AA (4.5:1)
- [ ] Interactive elements have 3:1 minimum contrast  
- [ ] Color is not the only way information is conveyed
- [ ] Sufficient color differentiation for color-blind users

### Brand Coherence  
- [ ] Visual personality aligns with product goals
- [ ] Color psychology supports intended user experience
- [ ] Differentiation from major competitors is clear
- [ ] Visual system feels premium and intentional

### Technical Feasibility
- [ ] Colors work across light/dark themes if needed
- [ ] Palette is comprehensive but not overwhelming (<20 colors)
- [ ] Design tokens are clearly defined and named
- [ ] Implementation guidance is actionable for developers

### Maroun's Design Standards
- [ ] Feels sophisticated and premium (not corporate or bland)
- [ ] Incorporates warmth and hospitality through design
- [ ] Shows attention to detail and visual refinement
- [ ] Balances modern aesthetics with cultural sensibility

---

## Selective Skeuomorphism Rule (added 2026-03-18)

Use physical metaphors when the digital feature *replaces* a physical object.

### The Test

Ask: **"What is the real-world equivalent of this feature?"**

| Answer | Direction |
|--------|-----------|
| Clear, emotionally resonant (e.g., "record player", "physical toolkit") | Lean into the physical metaphor |
| Abstract (e.g., "settings", "dashboard") | Stay flat/minimal |

### Pass Examples

- **MD Vinyl** spinning record — a music app IS a record player; spinning disc makes product feel alive
- **PamPam** tactile toolbar — replaces physical craft tools; texture reinforces the hands-on creative experience

### Fail Examples

- Fake leather calendar textures
- Wood-grain backgrounds on productivity apps
- Decorative stitching on UI elements

### Principle

Modern skeuomorphism = **emotional context, not visual decoration**.

The pendulum has swung back from flat design (2012–2024), but the return is *selective*. Texture earns its place only where physicality reinforces the product's emotional core.

---

*This skill evolves with each project, building a richer understanding of what visual directions work best for different product goals and user needs.*