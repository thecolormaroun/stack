---
name: tastemining
description: "Mine design inspiration from web and bookmarks"
---

# Taste Mining

Mine design inspiration from X bookmarks, web, and curated sources to build and refine your design taste profile.

## Skill graph entry point
Start at: `./_graph/research/taste-mining/tastemining.moc.md`

## When to Use
- `/research` when seeking design inspiration
- Before starting a new project's visual direction
- Building reference boards for specific aesthetics
- Periodically refreshing your taste profile

## Sources & How to Search

### X/Twitter Bookmarks (READ ONLY)
Design bookmarks are a great source. Configure your bookmark tool below.
```bash
# [Configure your bookmark source here]
```
Filter for: UI screenshots, product launches, design articles, interesting interactions.

### Web Search (Firecrawl or web_search)
```bash
# Search for design inspiration on specific topics
# Use web_search tool for broad discovery
web_search("best dark theme dashboard design 2026")
web_search("[project type] UI inspiration dribbble behance")
web_search("site:awwwards.com [aesthetic keyword]")

# Use Firecrawl to scrape specific galleries
firecrawl scrape "https://dribbble.com/search/[keyword]"
firecrawl scrape "https://www.awwwards.com/websites/[category]/"
```

### Curated Inspiration Sources (your picks)
**Always start here.** Full list: `./cdo/references/inspiration-sources.md`

| Source | Best For | URL |
|--------|----------|-----|
| **Brian Lovin /sites** | Full site quality | brianlovin.com/sites |
| **Design Spells** | Micro-interactions, delight | designspells.com |
| **Handheld Design** | Mobile patterns + rationale | handheld.design |
| **Featured Mobile** | Mobile app showcase | featuredmobile.com |
| **Are.na** (Tiny UI, ❖ interface, Delightful Interactions) | Deep aesthetic boards | are.na |
| **Cosmos** (Interface, Mobile UI, Elysian Space) | Curated visual research | cosmos.so |

### Broader Discovery (for specific searches)
| Source | Best For | How to Access |
|--------|----------|---------------|
| **Awwwards** | Site of the Day | `web_search("site:awwwards.com [topic]")` |
| **Dribbble** | Components (lower signal) | `web_search("site:dribbble.com [topic]")` |
| **Behance** | Case studies, process | `web_search("site:behance.net [topic]")` |
| **Mobbin** | Mobile UI patterns | `web_search("site:mobbin.com [pattern]")` |
| **Refero** | Real product screenshots | `web_fetch("https://refero.design/")` |

### Knowledge Base
```bash
# Search your knowledge base for design inspiration
```

### Designer Portfolios to Track
Scrape specific designers whose work aligns with your taste:
- Search for designers behind products you admire (Linear, Raycast, Arc, Vercel)
- Bookmark their portfolios for periodic review

## Process

### 1. Collect (10-20 references)
For the project's aesthetic direction, run 3-5 searches across different sources. Save screenshots or URLs.

### 2. Analyze Patterns
For each reference, extract:
- **Color approach** — palette, contrast, accent usage
- **Typography** — font choices, hierarchy, sizing
- **Layout** — grid, spacing, density
- **Motion** — animation style, transitions
- **Unique elements** — what makes it stand out
- **Design quality** — 1-5 rating with reasoning

### 3. Synthesize Direction
```markdown
## Taste Profile: [Project]

**Vibe:** [3-5 adjective summary]
**References:** [Links to 3-5 best examples with screenshots if possible]

### Visual DNA
- Colors: [palette direction with hex examples]
- Type: [font style direction with specific font suggestions]
- Layout: [density/spacing direction]
- Motion: [animation style with reference to Motion.dev patterns]

### What to steal
- [Specific element from Reference A — describe precisely]
- [Interaction pattern from Reference B — how it works]

### What to avoid
- [Anti-pattern identified — why it doesn't fit]
```

### 4. Save & Feed Forward
- Save to `./output/reference/research/taste-[project].md`
- If reusable patterns found → update CDO visual-direction skill references
- Feed directly into design-system skill for token selection
- Share findings with the team.

## Default Taste Profile
- Premium, dark, intentional
- Customize for your aesthetic
- Generous whitespace
- Subtle depth (shadows, not flat)
- Motion that feels purposeful, not decorative
- Data-rich interfaces done elegantly
- **Reference products:** Raycast, Linear, Arc, Vercel dashboard, Stripe docs
- **Avoid:** Corporate SaaS blandness, Material Design defaults, Bootstrap vibes
