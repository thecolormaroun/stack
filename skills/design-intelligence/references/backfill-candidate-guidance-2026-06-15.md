---
id: design-intelligence.backfill-candidate-guidance-2026-06-15
name: Backfill Candidate Guidance 2026-06-15
description: Candidate taste guidance synthesized from the 2026 OpenClaw outage backfill.
---

# Backfill Candidate Guidance - 2026-06-15

Status: `candidate - pending eval`.

This reference turns the historical backfill packets into reviewable taste/skill candidates. It is intentionally narrow: source collection stayed read-only, and this file does not promote anything into the default runtime by itself.

## Evidence Summary

Backfill window: `2026-04-01..2026-06-15`.

Source packet root:
`/Users/maroun/hermes/tmp/design-intelligence-backfill/2026-04-01..2026-06-15`

Normalized candidate counts:

| Source | Candidates |
| --- | ---: |
| Field Theory/X bookmarks | 192 |
| Arc history | 179 |
| Arc sidebar/bookmarks | 24 |
| Curated web | 0, marked `not_fetched_by_manifest_script` |
| GBrain X bookmarks | 0 candidates in packets; Field Theory reported 318 missing markdown files |

The GBrain delta is an ingestion/process signal, not permission to write GBrain roots. Curated web being degraded means web-source themes should be corroborated in a future weekly run before becoming defaults.

## Promoted Candidates For Eval

### 1. Reference-Backed Taste Uses Concrete Sources

Evidence:
- 33 reference/taste matches in the synthesis-agent pass.
- 10 weekly windows.
- Sources: Field Theory/X bookmarks and Arc history/sidebar.
- Domains/categories included design reference libraries, interface inspiration sites, shape/language references, and saved design workflow links.

Guidance:
- Pull from concrete reference sets before inventing: saved links, pattern libraries, visual vocabulary, reference boards, and side-by-side comparisons.
- Treat references as design infrastructure. They should shape the vocabulary, hierarchy, interaction model, and component choices, not sit in a generic inspiration appendix.
- If a reference source is degraded or unreachable, mark the limitation and do not promote a claim as default taste.
- Translate dense references responsively. If a source pattern uses a wide grid or table, preserve its comparison logic on mobile with priority columns, stacked row cards, or contained scrolling that does not widen the page.

Idempotency:
- Existing CDO guidance already asks for inspiration. This candidate makes references operational: inspect, compare, and translate them into specific decisions before producing a UI.

Rollback:
- Remove this section and the matching bullets in `SKILL.md`; leave source packets untouched.

### 2. Component Registry Patterns Are Ingredients

Evidence:
- 12 registry/component matches.
- 5 weekly windows.
- Sources: Field Theory/X bookmarks and Arc history.
- Domains/categories included X design bookmarks, `ui.shadcn.com`, and `registry.directory`.

Guidance:
- Use registries to identify component anatomy, state coverage, and useful primitives.
- Do not copy registry defaults as the finished aesthetic.
- If using shadcn/ui or registry blocks, customize tokens, radii, density, shadows, empty/error/loading states, and product-specific data before considering the result complete.

Idempotency:
- Existing taste guidance already says not to ship generic shadcn defaults. This candidate sharpens that rule by treating registries as pattern libraries for coverage and states, not just as code sources.

Rollback:
- Remove this section and the matching bullets in `SKILL.md`; leave source packets untouched.

### 3. Named Motion Must Explain State

Evidence:
- 23 motion/microinteraction matches.
- 9 weekly windows.
- Sources: Field Theory/X bookmarks, Arc history, and Arc sidebar.
- Domains/categories included X design bookmarks, `60fps.design`, `framer.com`, and transition libraries.

Guidance:
- Choose motion only when it clarifies a state change: selection, reveal, sorting, loading, dismissal, validation, or navigation.
- Name the transition pattern in the design/code reasoning, then specify trigger, duration/easing, interruption behavior, and reduced-motion fallback.
- Avoid `transition-all`, decorative perpetual motion, or animation that compensates for weak hierarchy.

Idempotency:
- Existing motion guidance covers craft and reduced motion. This candidate adds a sharper intake-derived rule: motion must be selected from a named state-change pattern, not sprinkled on as polish.

Rollback:
- Remove this section and the matching bullets in `SKILL.md`; leave source packets untouched.

### 4. AI Design Workflows Need A Visible Design Tree

Evidence:
- 190 AI design workflow/prompting matches.
- All 11 weekly windows.
- Sources: Field Theory/X bookmarks, Arc history, and Arc sidebar.
- Domains/categories included X design workflow bookmarks, `claude.ai`, Figma, builder/prototype tools, and local preview surfaces.

Guidance:
- For AI-assisted design tools, expose the design tree as the product surface: brief, generated directions, comparison criteria, chosen branch, iterations, and eval/QA state.
- Prefer inspectable artifacts and branch comparisons over a chat-only shell.
- When making an agentic design interface, show where the model is deciding, where the user can steer, and what evidence supports promotion.

Idempotency:
- Existing product guidance asks for real workflows. This candidate is specific to AI design products and the self-improving design loop Maroun is rebuilding.

Rollback:
- Remove this section and the matching bullets in `SKILL.md`; leave source packets untouched.

### 5. Variation And Critique Are Part Of Taste

Evidence:
- 21 variation/critique-loop matches in the synthesis-agent pass.
- 7 weekly windows, plus every weekly promotion packet repeated the eval requirement.
- Sources: Field Theory/X bookmarks, Arc history, and the generated promotion packets.

Guidance:
- When exploring a taste direction, generate multiple candidates, compare side by side, score against the rubric, then refine the selected branch.
- Treat critique artifacts, eval traces, and comparison criteria as part of the design workflow, not as optional reporting.
- Promote only the candidate that survives review and beats the baseline gate.
- A candidate with page-level horizontal overflow at 390px is a hard fail even if the desktop composition is stronger.
- For before/after redesign outputs, make the redesigned experience the default active view. Keep the legacy "before" state contained, scrollable within its own panel if necessary, and subordinate to the improved workflow.
- Check top-level shells as well as tables. Sidebars, sticky mobile headers, nav strips, metrics, charts, dialogs, and filter bars must use `min-width:0`, `max-width:100%`, wrapping, or contained overflow so `document.documentElement.scrollWidth` never exceeds `window.innerWidth`.

Idempotency:
- Existing promotion rules define the gate. This candidate brings the same loop into design generation so the artifact being evaluated is not a one-shot.

Rollback:
- Remove this section and the matching bullets in `SKILL.md`; leave source packets untouched.

## Watchlist, Not Promoted

Visual-finish tokens appeared repeatedly, including gradients, overlays, depth, typography, and surface polish. Keep this as a narrow future patch for `make-interfaces-feel-better` or CDO finish references because it overlaps existing polish rules.

Portfolio and visual-craft references appeared often, but the matches mix portfolios, brand sites, product pages, and working sessions. Use them as landing/portfolio inspiration, not operational-tool defaults.

Configurator and checkout references appeared in only 2 weekly windows and only from Arc history. Hold as a future source theme until more corroboration appears.
