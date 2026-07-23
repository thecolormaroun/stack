# Transitions.dev Motion Catalog

Source: https://transitions.dev
Upstream repo: https://github.com/Jakubantalik/transitions.dev
Upstream skill path: `skills/transitions-dev`

This catalog is for choosing motion patterns. Use
[source.json](source.json) for update metadata, and use the extractor script
when you need exact source-backed CSS or React snippets.

## Motion Tokens

| Token Type | Values | Use |
| --- | --- | --- |
| Duration | 40ms stagger, 80ms micro, 150ms quick, 250ms fast, 350ms medium, 400ms slow, 500ms emphasis | Keep timing consistent across the UI. |
| Easing | smooth decel `cubic-bezier(0.22, 1, 0.36, 1)`, `ease-in-out`, `ease-out`, linear, two bouncy overshoots | Match the physical feel to the state change. |
| Distance | 4px, 6px, 8px, 12px, 30px | Small travel reads as settling; large travel is reserved for emphasis. |
| Scale | 0.96, 0.97, 0.98, 0.99 | Surfaces enter from slightly under full size. |
| Blur | 2px, 3px, 8px | Use briefly during travel, then return to blur 0. |

## Transition Index

| Transition | Source Key | Generated File | Use When | Implementation Cue |
| --- | --- | --- | --- | --- |
| Card resize | `p4` | `01-card-resize.md` | A compact card or row expands to show detail. | Isolate the resizing surface and keep surrounding layout stable. |
| Number pop-in | `p9` | `02-number-pop-in.md` | KPI, counter, balance, price, or total changes. | Re-enter digits with small travel, blur, and stagger. |
| Notification badge | `p1` | `03-notification-badge.md` | A small count appears on a bell, inbox, or button. | Move the badge, not the trigger. Use a spring-like scale on the dot. |
| Text states swap | `p6` | `04-text-states-swap.md` | Button/status text changes in the same slot. | Keep both states mounted or width-locked; crossfade with 4px travel and blur. |
| Menu dropdown | `p2` | `05-menu-dropdown.md` | A menu or popover grows from a trigger. | Use transform origin from the trigger and close faster than open. |
| Modal open/close | `p7` | `06-modal.md` | A centered dialog needs focused attention. | Fade plus scale from 0.96; use backdrop dimming. |
| Panel reveal | `p3` | `07-panel-reveal.md` | A drawer/detail panel slides into an existing region. | Use Y travel, opacity, slight blur, and clipping during motion. |
| Page side-by-side | `p8` | `08-page-side-by-side.md` | Wizard or list-detail views move between adjacent pages. | Slide/fade pages with about 8px travel and optional stagger. |
| Icon swap | `p5` | `09-icon-swap.md` | Copy/check, play/pause, expand/collapse, sun/moon. | Keep both icons in the DOM; animate opacity, scale, and blur. |
| Success check | `p10` | `10-success-check.md` | A save, upload, send, payment, or submit completes. | Compose fade, rotate, bob, blur, and SVG path draw. |
| Avatar group hover | `p11` | `11-avatar-group-hover.md` | Horizontal stack of avatars, chips, tags, or reactions. | Lift hovered item and nearby items with distance falloff. |
| Error state shake | `p12` | `12-error-state-shake.md` | Invalid input or failed validation needs correction. | Shake in short segments, then fade error border/message back to neutral. |
| Input clear with dissolve | `p13` | `13-input-clear-dissolve.md` | Search/filter text clears with an X button. | Use JS only if the per-word streak is worth the complexity. |
| Skeleton loader and reveal | `p14` | `14-skeleton-reveal.md` | Placeholder content resolves into real content. | Pulse skeleton children, then crossfade/cross-blur to content in the same slot. |
| Shimmer text | `p15` | `15-shimmer-text.md` | A loading/thinking label should feel alive. | Mask a gradient sweep through duplicated text; disable under reduced motion. |
| Tabs sliding | `p16` | `16-tabs-sliding.md` | A segmented control or tab bar changes active option. | Measure the active tab and animate pill transform plus width. |
| Tooltip open/close | `p17` | `17-tooltip.md` | Hover/focus hint appears near a trigger. | Delay entrance only; exit immediately to avoid sticky UI. |
| Texts reveal | `p18` | `18-texts-reveal.md` | Headline and support text enter with rhythm. | Stagger primary and secondary lines; exit with a quiet fade in place. |

## Choosing The Pattern

- Trigger plus small dot: notification badge.
- Trigger plus anchored surface: dropdown.
- Centered overlay: modal.
- Detail surface inside existing layout: panel reveal.
- Two full states or steps: page side-by-side.
- Same element changes dimensions: card resize.
- Same element changes text: text states swap.
- Same slot changes icon: icon swap.
- Number changes: number pop-in.
- Completed action: success check.
- Horizontal stack hover: avatar group hover.
- Invalid form state: error state shake.
- Search clear: input clear with dissolve.
- Data loading into known layout: skeleton loader and reveal.
- Loading label: shimmer text.
- Segmented control: tabs sliding.
- Hover/focus hint: tooltip.
- Headline/support copy entry: texts reveal.

If two patterns fit, prefer the lower-overhead one. A dropdown beats a modal for
anchored choices. A text swap beats a panel reveal for a label change. A success
check beats a full celebration modal for a normal completed action.

## Implementation Rules

- Install only the chosen transition's CSS and hooks.
- Preserve exact property lists; do not collapse to `transition: all`.
- Preserve `@media (prefers-reduced-motion: reduce)`.
- Use transform, opacity, and small filter changes before layout animation.
- Keep `will-change` scoped to elements that actually animate.
- Do not add a motion dependency for these snippets.
- For React projects, adapt orchestration into the existing component style
  instead of introducing a new animation abstraction.
