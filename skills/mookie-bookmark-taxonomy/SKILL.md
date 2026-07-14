---
name: mookie-bookmark-taxonomy
description: "Classify Hermes/Mookie bookmark batches into useful GBrain graph taxonomy updates. Use when Maroun asks to summarize, tag, categorize, domain-map, entity-map, or recommend graph pages for recent X/bookmark captures, AI/design/productivity bookmark sets, weekly adoption packets, or Mookie self-improvement candidates without mutating source corpora."
---

# Mookie Bookmark Taxonomy

Use this skill when a bookmark batch needs to become graph-ready knowledge: categories, domains, entities, related page suggestions, and next ingestion improvements.

## Source Order

1. Read `~/hermes/MOOKIE.md`, `~/hermes/KNOWLEDGE.md`, and `~/hermes/PILOT.md` when present.
2. Read the relevant Hermes skill routing reference if the task is broad:
   - `~/hermes/skills/autonomous-ai-agents/hermes-agent/references/mookie-skill-routing-and-graph.md`
3. Use current bookmark evidence from the requested artifact, GBrain query output, local session log, or `~/.ft-bookmarks/md` when explicitly in scope.
4. Use recent session/automation evidence only as support; do not present stale memory as current bookmark truth.

## Classification Workflow

For each batch:

1. Identify the unit of work: individual bookmark, author/entity, category, domain, or weekly adoption theme.
2. Assign a primary classification first, then secondary classifications only when they add routing value.
3. Prefer stable graph pages over one-off labels:
   - `[[categories/tool]]`, `[[categories/technique]]`, `[[categories/design]]`, `[[categories/productivity]]`, `[[categories/ai-news]]`, `[[categories/ai-agent]]`;
   - `[[domains/ai]]`, `[[domains/design]]`, `[[domains/health]]`, `[[domains/career]]`, `[[domains/parenting]]`;
   - `[[entities/<name>]]` only for recurring authors, companies, products, or people with enough repeated evidence.
4. Separate taxonomy from substance. If the available data is only URLs, author names, or shells, recommend title/body/summary extraction instead of pretending the topic is deeply understood.
5. When the batch has operational value for Mookie, add a concise "adoption candidate" note: what Hermes/Mookie should try, what source supports it, and what validation would prove it useful.

If the prompt requires machine-readable classification, return exactly the requested shape. For JSON-only prompts, do not add markdown fences or explanatory prose.

If the prompt asks for a wiki or knowledge-base page, keep taxonomy separate from narrative synthesis:

- taxonomy fields should be stable graph labels;
- narrative sections should summarize repeated bookmark evidence;
- graph-update suggestions should name the target page and the reason it reduces future routing ambiguity.

## Output Shape

Return a compact, source-faithful report:

```text
Primary classifications:
- <bookmark or cluster>: <primary> plus <secondary, if useful>

Graph updates:
- Create/update <page>: <why this page is useful>

Adoption candidates:
- <candidate>: <what Mookie should try next and how to validate it>

Evidence gaps:
- <gap>: <smallest next extraction or source improvement>
```

## Boundaries

- Do not write to Vault, `.ft-bookmarks`, GBrain, source corpora, or browser profiles unless Maroun explicitly asks.
- Do not expose private, financial, credential-shaped, health, household, or sensitive bookmark details. Paraphrase and label sensitive lanes.
- Do not overfit to one viral post. Require repeated evidence before recommending a new entity or category page.
- Do not browse or open authenticated social pages unless the user explicitly asks for live web validation.

## Quality Bar

A good output makes the graph easier to use next time. It should reduce duplicate labels, name thin-source gaps honestly, and turn repeated bookmark themes into concrete Mookie/Hermes actions only when the evidence supports them.
