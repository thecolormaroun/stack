# 12 Principles of Animation for Product UI

A compact implementation and review lens distilled from Raphael Salaja’s **[12 Principles of Animation](https://www.raphaelsalaja.com/library/12-principles-of-animation)** (accessed 2026-08-15). The original principles come from Disney animation; this reference translates them for interface work rather than treating them as permission to make every app bounce.

## Use this before implementation

For a proposed motion sequence, write down:

1. **Purpose:** What does it clarify: feedback, hierarchy, state, spatial continuity, or an important consequence?
2. **Frequency:** Is it high-frequency, occasional, or a rare moment of delight? High-frequency motion should usually disappear.
3. **Primary action:** What must the user notice or understand first?
4. **Motion budget:** Which one or two principles make that outcome clearer? Delete the rest.
5. **Verification:** Check it in reduced motion, under CPU pressure, and at 0.25× speed before calling it finished.

## Principles translated to UI

| Principle | Product-UI translation | Good use | Guardrail |
| --- | --- | --- | --- |
| **Squash and stretch** | Tiny shape or scale changes can communicate softness, weight, and responsive state. | An icon morphing between related states; subtle press feedback. | Keep it restrained. It becomes cartoon noise fast. Never use `scale(0)` for entrances. |
| **Anticipation** | Briefly reveal the consequence of a consequential action before it commits. | A hold-to-delete fill; a drag threshold; a pending destructive state. | Do not add a wind-up to routine taps. It must not make users wait. |
| **Staging** | Sequence a complex transition so attention lands on the primary change. | Backdrop first, then drawer/modal, then the primary control. | Do not animate the whole room at once. One focal point per beat. |
| **Straight ahead / pose to pose** | Design the meaningful states first, then let transitions interpolate between them. | Define closed, opening, open, and dismissing states for a sheet. | Do not keyframe every intermediate pixel without a reason. |
| **Follow-through / overlapping action** | Slight staggering or spring settling can keep related elements from moving as a rigid block. | A short 30–80ms list stagger; a springy but controlled drag release. | Do not turn latency into “naturalism.” Interaction must remain responsive and interruptible. |
| **Slow in / slow out** | Use easing to make changes legible and responsive. | Strong ease-out for arrivals and feedback; an intentional curve for on-screen movement. | Validate the direction against the actual interaction. Prefer observed feel over a rote label; never use a slow start that delays feedback. |
| **Arcs** | Curved paths can make large or playful movements feel intentional. | Bringing an object forward in a landing-page demo; a playful spatial transition. | Rare in dense product UI. Straight paths are usually clearer and cheaper. |
| **Secondary action** | Add a quiet reinforcing cue after the primary state change. | A confirmation check gaining a brief accent after a successful submit. | The secondary cue cannot compete with, delay, or obscure the main result. |
| **Timing** | Duration expresses priority and perceived speed. | Fast tooltips/popovers; deliberate hold-to-confirm; a consistent motion scale. | Most product UI should stay under 300ms. Consistency beats arbitrary variety. |
| **Exaggeration** | Amplify motion only when visibility or emotional meaning genuinely matters. | An error shake; an onboarding milestone; a rare successful completion. | Use sparingly. Frequent exaggeration trains users to ignore it. |
| **Solid drawing** | Preserve visual depth, hierarchy, and physical coherence through transforms. | Trigger-origin popovers; perspective-aware 3D illustration; layered surfaces. | Avoid gratuitous 3D. Keep transform origin, shadow, scale, and perspective internally consistent. |
| **Appeal** | Motion should reinforce the product’s character and make the interaction feel intentional. | Warm, lightly playful consumer flows; crisp, calm professional tools. | “Delightful” is not an excuse for visual debt, dropped frames, or inaccessible motion. |

## Shipping checklist

- [ ] The primary action is clear without the motion.
- [ ] Motion adds one concrete kind of understanding or feedback.
- [ ] The sequence has a focal point and does not animate everything simultaneously.
- [ ] It responds immediately, can be interrupted where appropriate, and preserves input responsiveness.
- [ ] It uses `transform` and `opacity` for continuous motion where possible.
- [ ] `prefers-reduced-motion` keeps the state change understandable with less movement.
- [ ] Timing, easing, and amplitude match the product’s personality and are consistent with similar components.
- [ ] The result was viewed at slow speed and on a representative device or CPU-throttled browser.

## Relationship to the existing standards

This reference is an ideation and sequencing layer. `STANDARDS.md` remains the precise implementation/review source for duration budgets, easing curves, transform-origin, springs, performance, gestures, and accessibility.
