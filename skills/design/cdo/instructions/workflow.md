# CDO Core Workflow

```
Plan File (from CPO)
    ↓
┌─────────────────────┐
│   1. UNDERSTAND     │  Parse product goals, user needs, constraints
│   2. RESEARCH       │  Reference design system, gather inspiration
│   3. STRATEGIZE     │  Visual direction, information architecture
│   4. SPECIFY        │  Detailed design specs for each component/flow
│   5. ENRICH         │  Append design spec to plan file
└─────────────────────┘
    ↓
Ready for /ce:work or /lfg
```

## Input

CDO reads a **plan file** from CPO, typically at:
```
docs/plans/YYYY-MM-DD-NNN-<type>-<name>-plan.md
```

The plan contains product requirements, user stories, and acceptance criteria.

## Step 1: Parse Requirements

Extract design-relevant information from the plan:

| Requirement Type | Design Question | Specialty Needed |
|-----------------|----------------|------------------|
| **User Goals** | What experience supports this goal? | UX Patterns |
| **Content Structure** | How should information be organized? | Layout Strategy |
| **Brand Requirements** | What visual tone matches the product? | Visual Direction |
| **Technical Constraints** | What platforms/devices need support? | Design System |
| **Accessibility Needs** | What inclusivity standards apply? | UX Patterns + Typography |

## Step 2: Visual Strategy

Load `visual-direction/SKILL.md` to establish:
- **Personality**: Premium, approachable, professional, playful
- **Visual weight**: Light, balanced, bold
- **Color strategy**: Monochromatic, complementary, accent-driven
- **Aesthetic references**: Draw from `references/` directory

## Step 3: Information Architecture

Load `ux-patterns/SKILL.md` and `layout-strategy/SKILL.md` for:
- Navigation patterns
- Content hierarchy
- User flows
- Mobile considerations
- Grid system and spacing scale

## Step 4: Typography & Visual System

Load `typography/SKILL.md` and `design-system/SKILL.md` for:
- Typography scale (H1-H6, body, UI text)
- Font pairing
- Design token system (colors, spacing, typography)

## Step 5: Component Specifications

Create detailed specs for each UI component using established system.

## Step 6: Enrich Plan File

**Append** design specification to the plan file under `## Design Specification`:

```markdown
## Design Specification

### Visual Direction
- Theme: [dark/light/system]
- Primary color: [hex]
- Accent color: [hex]
- Typography: [font stack]

### Layout
- Grid: [columns, gutter, margins]
- Breakpoints: [mobile, tablet, desktop]
- Spacing scale: [4px base, or custom]

### Components
[Component specs for each UI element in the plan]

### Interactions
- Transitions: [duration, easing]
- Hover states: [description]
- Loading states: [skeleton, spinner, etc.]

### Accessibility
- Contrast ratios: [WCAG AA/AAA]
- Focus indicators: [style]
- Motion: [respect prefers-reduced-motion]
```

This keeps everything in one file for `/ce:work` to consume.

## Output

The enriched plan file is ready for compound-engineering:
```bash
/ce:work docs/plans/YYYY-MM-DD-NNN-<type>-<name>-plan.md
```

Or run the full autonomous workflow:
```bash
/lfg
```
