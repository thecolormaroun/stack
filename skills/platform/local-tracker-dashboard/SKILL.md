---
name: local-tracker-dashboard
description: "Create, update, or validate a local static HTML tracker dashboard from Maroun's project handoffs, plans, packing lists, trip notes, order/status updates, or task checklists. Use when Maroun asks for a minimalist visual tracker, local checklist dashboard, persistent to-do artifact, or browser-verified static planning page."
---

# Local Tracker Dashboard

Use this skill to turn an active local plan into a compact, useful dashboard that Maroun can actually work from. The dashboard should be a static local artifact with persistent checklist state and a clear verification pass in `agent-browser`.

## Source Order

1. Read the handoff, plan, packing list, markdown tracker, or existing dashboard named by the user.
2. Search the target workspace for adjacent source docs with `rg --files` and `rg` before adding new structure.
3. If the user explicitly asks to use email/calendar or another sensitive connector, extract only the concrete status fields needed for the tracker and paraphrase sensitive evidence.
4. Use official/public sources only for facts that could change, such as permits, route closures, reservation requirements, or venue rules.

## Dashboard Rules

- Build the actual working tracker as the first screen, not a landing page.
- Keep it self-contained unless the repo already has a frontend stack that should be reused.
- Prefer stable IDs for checklist items so localStorage state survives content edits.
- Distinguish status states such as `ordered`, `arrived`, `packed`, `printed`, `reserved`, and `blocked`; do not collapse them into one checked state.
- Keep personal, financial, health, credential, and email details out of visible text unless they are necessary and explicitly requested.
- Do not use browser profiles or external accounts unless the user explicitly asks.

## Implementation

1. Update the existing artifact if one exists; otherwise create one in the project's existing `plans/`, `docs/`, or equivalent planning folder.
2. Use plain HTML/CSS/JS for a local file unless the surrounding project already expects a framework.
3. Add sections that match the work, for example route/logistics, next gates, buy/order status, packing, documents, verification, and source links.
4. Use concise visible text. The page should support action, not explain itself.
5. If a markdown checklist also exists, update it only when the dashboard and markdown are both active user-facing artifacts.

## Verification

Use `agent-browser` by default:

```bash
command -v agent-browser
agent-browser open file:///absolute/path/to/dashboard.html
```

Then verify:

- the page loads with no browser errors;
- expected new sections and checklist items exist in the DOM;
- at least one checkbox or persisted control survives reload through localStorage;
- desktop and mobile widths do not overlap or hide task text.

If `agent-browser` is unavailable, report that blocker and use a simpler static inspection plus a browser command Maroun can run.

## Closeout

Report:

- dashboard path;
- source docs used;
- status changes made;
- browser verification performed;
- any sensitive source used, paraphrased at a high level;
- next physical/manual gate for Maroun.
