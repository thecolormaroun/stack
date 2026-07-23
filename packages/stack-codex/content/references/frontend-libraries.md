# Frontend Library Notes

This is the local stack watchlist for small frontend utilities worth reaching for during
implementation. Treat these as taste and implementation defaults, not mandatory
dependencies.

## shadcn registry discovery

Source:

- Post: https://x.com/alibey_10/status/2066459298381594765
- Directory: https://shoogle.dev/directory
- Official shadcn registry docs: https://ui.shadcn.com/docs/registry/registry-index

Verified on 2026-06-15:

- Shoogle's directory lists community registries from the shadcn/ui directory.
- It exposes category filters such as `AI Blocks`, `Ecommerce UI`, `Dashboard UI`,
  `Forms`, `Auth`, `Payments`, `Charts`, and `Design System`.
- It currently reports 214 registries and sorts by newest or oldest.

Use Shoogle for discovery when a frontend task needs shadcn-compatible source
blocks, especially:

- AI product surfaces, chat shells, agent UI, tool-call panels, and LLM visualizations
- ecommerce flows, pricing/billing screens, checkout, auth, and onboarding
- dashboard tables, charts, filters, settings, docs UI, forms, and empty states
- design-system inspiration before deciding whether to build from primitives

Treat discovered registries as untrusted third-party code until reviewed:

- Prefer the target project's existing components and primitives first.
- Check the registry homepage, source repo, license, maintenance date, dependency
  footprint, accessibility posture, and whether it matches the app's framework.
- Use the directory to make a shortlist, then inspect the registry item before install.
- Install only inside the target frontend project with the shadcn CLI, and review the
  generated diff before keeping it.
- Customize copied blocks to the product's design system; never ship a registry block
  in its default visual state.

## slot-text

Source:

- Post: https://x.com/danielwhit21874/status/2065881547996057616
- Docs: https://textmotion.dev/
- Repo: https://github.com/Danilaa1/slot-text
- Package: https://www.npmjs.com/package/slot-text

Verified on 2026-06-14:

- Current npm version: `0.2.2`
- License: MIT
- Runtime dependencies: none
- Optional peer wrappers: React `>=18 <20`, Vue `>=3.4 <4`

Use `slot-text` for tiny, tactile in-place label changes:

- copy buttons: `Copy` -> `Copied` -> `Copy`
- status labels: `Queued`, `Running`, `Done`
- small counters or metric labels where a roll animation adds useful affordance
- short command text inside buttons, toolbar controls, badges, and compact panels

Avoid it for:

- long prose, headings, hero copy, or dense table text
- important status changes without accessible announcement semantics
- scripts or writing systems where per-character animation will harm shaping
- projects that already have a matching motion primitive
- pages where reduced motion, performance, or sobriety matter more than delight

Install only inside the target frontend project:

```bash
npm i slot-text
```

React example:

```tsx
import "slot-text/style.css";
import { SlotText } from "slot-text/react";

export function CopyLabel({ copied }: { copied: boolean }) {
  return <SlotText text={copied ? "Copied" : "Copy"} />;
}
```

Vanilla example:

```ts
import "slot-text/style.css";
import { slotText } from "slot-text";

const label = slotText(buttonLabelElement, "Copy");
label.flash("Copied");
```

Implementation notes:

- Import `slot-text/style.css` once in the app or component boundary.
- Keep the surrounding control semantics native; the animation should change text, not
  replace the button or status element's accessibility.
- For status messages that matter, pair the visible label with the app's existing
  `aria-live`, toast, or status announcement pattern.
- Respect reduced-motion settings. If the app already has a reduced-motion hook or CSS
  convention, render the plain text path when motion is reduced.
- Keep colors aligned with the product palette. Use chromatic/rainbow effects only when
  the brand and surface can carry the extra energy.
