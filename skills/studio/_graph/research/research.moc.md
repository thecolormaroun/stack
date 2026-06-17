---
id: research.moc
description: (no description)
name: Research (MOC)
description: Entry point for Studio research knowledge (competitive intel, taste mining, synthesis templates).
inputs:
  - research_request: "A product or market question to investigate"
  - competitor_url: "Specific competitor or product to analyze"
  - design_inspiration_need: "Request for taste/aesthetic direction"
outputs:
  - competitive_analysis: "Landscape map, competitor teardowns, gap analysis"
  - taste_profile: "Curated aesthetic direction with references"
  - synthesis_doc: "Research findings synthesized into actionable brief"
triggers:
  - "/design-intelligence — weekly design digest + taste compounding loop"
  - "/tastemining — design inspiration from web + bookmarks"
  - "/competitive — market analysis, gap analysis"
depends_on:
  - "Arc bookmarks and history (read-only intake)"
  - "Field Theory/X bookmarks (read-only intake)"
  - "GBrain source roots for imported bookmark deltas"
  - "Web search and fetch tools"
feeds_into:
  - "[[product.moc]] — competitive insights inform PRD and positioning"
  - "[[design.moc]] — taste profiles inform visual direction and creative direction"
---

# Research — MOC

Research feeds both product and design. Run research BEFORE committing to a product direction or visual identity.

## When to use which sub-domain

| Task | Load this |
|------|-----------|
| Who are the competitors? | [[competitive.moc]] |
| What changed in Maroun's saved design inspiration this week? | [[studio.research.design-intelligence-loop]] |
| What should this look/feel like? | [[tastemining.moc]] |

## Competitive
- [[competitive.moc]] — landscape discovery, deep dives, gap analysis

## Taste mining
- [[studio.research.design-intelligence-loop]] — weekly digest, bookmark backfill, skill update candidates
- [[tastemining.moc]] — sources, workflow, your taste profile
