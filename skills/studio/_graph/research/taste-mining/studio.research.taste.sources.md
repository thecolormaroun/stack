---
id: studio.research.taste.sources
name: Taste Mining Sources
description: Where to pull inspiration (Tier 1, X bookmarks, galleries).
when_to_use:
  - inspiration
---

# Taste Mining Sources

## Tier 0 — Maroun Bookmark Streams (always mine weekly)

| Source | Local Surface | Focus | Notes |
|--------|---------------|-------|-------|
| **Arc Bookmarks** | `~/Library/Application Support/Arc/StorableSidebar.json` | Saved design sites, galleries, products, portfolios | Read-only. Use Arc History only to enrich recency. |
| **Field Theory / X Bookmarks** | `~/.ft-bookmarks/bookmarks.db` and `~/.ft-bookmarks/md/bookmarks/` | Maroun's newest design inspo saves | Read-only. Use `synced_at` for capture recency and `posted_at` for content recency. |
| **GBrain Bookmark Roots** | `~/.gbrain/source-roots/x-bookmarks-native` and `~/.gbrain/source-roots/saved-links` | Already-imported bookmark memory and deltas | Compare against live Field Theory; do not mutate roots during intake. |

## Tier 1 — Curated Web Sources (always mine weekly)

| Source | URL | Focus | Notes |
|--------|-----|-------|-------|
| **Brian Lovin** | https://brianlovin.com/writing | Design × engineering quality, taste, QA loops | Treasure trove. Mine every new post. Former GitHub/Meta design. |
| **Design Spells** | https://designspells.com | Interaction design details | JS-heavy, needs browser scrape |
| **Handheld Design** | https://handheld.design | Mobile design patterns | Substack, Design Picks series |
| **Featured Mobile** | https://featuredmobile.com | Curated mobile inspiration | JS-heavy |
| **Social Bookmarks** | Field Theory/X + Arc | Design saves | Required weekly input via [[studio.research.design-intelligence-loop]] |

## Tier 2 — Periodic Scan

- Awwwards (trends, not awards)
- Dribbble (visual patterns, not likes)
- Behance (case studies)
- Mobbin (mobile patterns database)
- Refactoring UI tips
- Tailwind UI patterns

## How to Mine

1. Build a read-only source manifest from Tier 0 plus Tier 1 every week.
2. For each finding: extract the pattern, name it, write the "apply this" action
3. If durable: propose a permanent note; do not write it by default.
4. If actionable for Studio: propose a skill/checklist update with evidence and an idempotency check.
5. If Brian Lovin: always create permanent note (his writing is reference-grade)
6. Before promoting a skill update: run the Codex design eval gate and require no hard fails.

## Historical Backfill

Use `[[studio.research.design-intelligence-loop]]` for the outage catch-up. Default initial window: `2026-04-01` through the current run date, chunked by week.
