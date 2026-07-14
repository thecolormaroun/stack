---
name: local-finance-interface
description: "Build or audit local-only household finance interfaces from sanitized source artifacts. Use for CSP-style monthly finance dashboards, Ledger/Zouzou/where-to-live synthesis, Claude Design artifact preservation, read-only reviewed finance facts, local planning assumptions, privacy audits, Playwright smoke checks, and monthly close workflow docs."
---

# Local Finance Interface

Use this skill when Maroun wants a private household finance app or audit that combines existing local finance/planning artifacts without turning the app into a new source of truth.

## Source Order

1. Read local project docs and plans first.
2. Inspect trusted sanitized finance state and monthly close status before treating a month as final.
3. Inspect legacy product/source artifacts such as Ledger specs, screenshots, design zips, and where-to-live dossiers as product inputs, not authoritative finance data.
4. Preserve imported design/source artifacts under the target project docs when they are part of the durable handoff.
5. Keep sensitive raw data summarized. Do not print raw transactions, account identifiers, screenshots, credentials, or OCR payloads.

## Product Boundary

- Build for local monthly household use unless Maroun explicitly asks for hosting.
- Reviewed finance facts stay read-only.
- Editable planning assumptions may be saved locally, but must be visibly separate from reviewed facts.
- The app may present goals, scenarios, dossiers, and close readiness, but it must not mutate Zouzou, Ledger databases, Copilot exports, bank data, Vault, credentials, or external accounts.
- Treat source freshness as first-class UI state: final, draft, stale, missing, blocked, or provisional.

## Implementation Ladder

Inspect project scripts before running them. In read-only or audit-only tasks, prefer the narrow existing privacy/local-only gate and do not regenerate bundles, reinstall dependencies, or run full verification unless the delegation allows source reads and generated artifact writes.

Prefer the existing project stack. For a Vite/React local app, use this ladder when scripts exist and the task allows normal local verification:

```bash
npm ci
npm run verify
npm audit --json
```

If there is no unified `verify` script yet, create one that covers:
- source bundle generation from sanitized local inputs;
- unit tests for derived finance/planning behavior;
- TypeScript/build checks;
- privacy/local-only audit;
- Playwright desktop and mobile smoke checks.

Do not add network calls, hosted auth, bank/Plaid/Copilot/Gmail connections, or account sync unless explicitly requested.

## Privacy Checks

The closeout should be able to say:
- no external runtime requests are required for the app to work;
- raw finance markers are absent from the DOM/build output;
- generated bundles contain aggregate/sanitized data only;
- CSP or equivalent browser posture blocks unexpected network usage;
- local storage is used only for planning assumptions or local UI state.

## Design Handling

When Maroun provides Claude Design or other design artifacts, preserve the exact design direction as source material before implementation. Recreate the interaction and information architecture faithfully unless Maroun explicitly asks to reinterpret it.

## Closeout

Report:

```text
What Maroun can open:
Source facts used:
What is editable vs read-only:
Privacy/local-only evidence:
Verification:
Known tradeoffs:
Next monthly workflow:
```
