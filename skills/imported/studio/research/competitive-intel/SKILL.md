---
name: competitive
description: "Market analysis, competitor research, and gap analysis"
---

# Competitive Intel

Analyze competitors, market landscape, and adjacent products for strategic positioning.

## Skill graph entry point
Start at: `./_graph/research/competitive/competitive.moc.md`

## When to Use
- Before building a new product (market validation)
- Pricing decisions (what do alternatives cost?)
- Feature prioritization (what do competitors lack?)
- When you asks "is there anything like this already?"

## Process

### 1. Discover the Landscape

Start with broad search, then narrow:

```bash
# Broad discovery
web_search("[product idea] app")
web_search("[problem it solves] tool software")
web_search("[product idea] alternatives")
web_search("site:producthunt.com [product category]")
web_search("site:alternativeto.net [similar product]")

# Review aggregators
web_search("best [category] tools 2026 comparison")
web_search("site:g2.com [product category]")
```

Classify what you find:
- **Direct competitors** — solve the same problem for the same audience
- **Indirect competitors** — solve adjacent problems or serve different audiences
- **Substitutes** — what do people use today? (spreadsheets, manual process, nothing)

### 2. Deep-Dive Each Competitor

Use Firecrawl or web_fetch to scrape their sites:

```bash
# Scrape product page
firecrawl scrape "[competitor-url]"
firecrawl scrape "[competitor-url]/pricing"

# Check reviews
web_search("[competitor name] review reddit")
web_search("[competitor name] review g2")
web_search("[competitor name] complaints")
```

For each competitor:
```markdown
## Competitor: [Name]
**URL:** [link]
**Founded:** [year if known]
**Pricing:** [model + specific prices]
**Free tier:** [yes/no, what's included]
**Users:** [estimated scale — check for social proof numbers on site]

**What they do well:**
- [Specific strength with evidence]

**What they do poorly:**
- [Specific weakness — cite reviews/complaints]

**Design quality:** [1-5] — [notes on visual/UX polish]
**Tech stack:** [if discoverable — check job postings, Wappalyzer]
**Key differentiator:** [their moat]
**Vulnerability:** [where we could beat them]
```

### 3. Gap Analysis

```markdown
## Competitive Gap Analysis: [Product]

### Feature Matrix
| Feature | Us (Planned) | [Comp A] | [Comp B] | [Comp C] |
|---------|-------------|----------|----------|----------|
| [Feature 1] | ✅ | ✅ | ❌ | ✅ |
| [Feature 2] | ✅ | ❌ | ✅ | ❌ |
| Dark theme | ✅ | ❌ | ❌ | ❌ |
| Mobile-first | ✅ | 🟡 | ❌ | ✅ |

### Pricing Comparison
| Product | Free | Basic | Pro | Enterprise |
|---------|------|-------|-----|-----------|
| Us | [planned] | [planned] | [planned] | — |
| [Comp A] | $0 | $X/mo | $Y/mo | Custom |

### Underserved Needs
1. [Need no one addresses well — our opportunity]
2. [Need addressed poorly by all — differentiation angle]

### Our Positioning
**Angle:** [How we differentiate]
**For:** [Specific audience underserved by existing options]
**Unlike:** [Key competitor], which [limitation]
**We:** [Our unique value]
```

### 4. Save & Route

- Save to `./output/reference/research/competitive-[product].md`
- Summary to stakeholders
- Feed insights into:
  - **prd-writer** → feature prioritization based on gaps
  - **commercialization** → pricing strategy based on market
  - **taste-mining** → design quality benchmarks to beat
