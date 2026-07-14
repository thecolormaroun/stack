---
name: gemini-zk-orchestrator
description: "Run or audit Maroun's Gemini Zettelkasten production-roadmap orchestrator. Use for Antigravity/Gemini quota readiness, five-lane ZK autoresearch status, central promotion gates, burn-in handoffs, provider registry checks, and deciding whether to spend, hold, or promote scratch Zettelkasten candidates."
---

# Gemini ZK Orchestrator

Use this skill when Gemini/Antigravity is part of Zettelkasten note generation, gardener bakeoff, source remediation, or autoresearch spenddown. The job is not to spend quota by default; the job is to read the controlling artifacts, prove readiness, and keep the central gate fail-closed.

## Evidence Order

1. Read the current board under `tmp/gemini-zettelkasten-autoresearch/`, especially the newest `ROADMAP_ORCHESTRATOR_STATUS_*.md`.
2. Read the source plan, usually `~/Projects/Zettelkasten/docs/plans/2026-06-30-002-feat-gemini-production-roadmap-plan.md`.
3. Inspect the specific gate artifacts for the lane: provider registry, quota stability, quota readiness, central promotion gate, burn-in handoff, process audit, and lane-specific readiness.
4. Inspect the scripts and tests under `scripts/zettelkasten/codex-eval/` before changing or running the pipeline.
5. Use memory only as prior context; live artifacts decide the current gate.

## Lane Model

Track the five lanes separately:

- Health/Attia source remediation;
- Finance/Ramit quality;
- permanent-note parity;
- gardener Gemini bakeoff;
- ops/cutover.

Each lane can be `PASS_HELD`, `PARTIAL_PASS_QUOTA_HELD`, `PASS_NOT_PROMOTED`, `BLOCKED_FAIL_CLOSED`, or another explicit artifact-backed state. Do not collapse a lane pass into roadmap promotion while the central gate is `DO_NOT_PROMOTE`.

## Readiness Ladder

Before any Gemini generation call, require:

```bash
env -u GEMINI_API_KEY -u GOOGLE_API_KEY python3 scripts/zettelkasten/codex-eval/gemini-quota-stability-audit.py --samples 3 --interval-seconds 1 --output-root tmp/gemini-zettelkasten-autoresearch/next-quota-stability-audit --write --json
env -u GEMINI_API_KEY -u GOOGLE_API_KEY python3 scripts/zettelkasten/codex-eval/gemini-provider-registry.py --output-root tmp/gemini-zettelkasten-autoresearch/next-provider-registry-quota-refresh --primary-quota-limit 95 --weekly-quota-limit 95 --write --json
python3 scripts/zettelkasten/codex-eval/gemini-quota-spenddown-readiness.py --provider-registry tmp/gemini-zettelkasten-autoresearch/next-provider-registry-quota-refresh/gemini-provider-registry.json --quota-stability tmp/gemini-zettelkasten-autoresearch/next-quota-stability-audit/quota-stability-audit.json --output-root tmp/gemini-zettelkasten-autoresearch/next-quota-readiness-after-stability-open --write --json
python3 scripts/zettelkasten/codex-eval/gemini-central-promotion-gate-audit.py --provider-registry tmp/gemini-zettelkasten-autoresearch/next-provider-registry-quota-refresh/gemini-provider-registry.json --quota-stability tmp/gemini-zettelkasten-autoresearch/next-quota-stability-audit/quota-stability-audit.json --quota-spenddown-readiness tmp/gemini-zettelkasten-autoresearch/next-quota-readiness-after-stability-open/quota-spenddown-readiness.json --output-root tmp/gemini-zettelkasten-autoresearch/next-central-gate-after-stability-open --write --json
python3 scripts/zettelkasten/codex-eval/gemini-process-audit.py --output-root tmp/gemini-zettelkasten-autoresearch/next-process-audit-before-model-call --write --json
```

Only continue to a model call when quota readiness is `READY_FOR_ONE_BOUNDED_GEMINI_GATE` or stronger, process audit passes, and the run queue names the lane and stop rule.

## Hard Stops

- Do not write to Vault, Fieldbook, source corpora, processed markers, LaunchAgents, provider defaults, live prompts, browser profiles, credentials, or external accounts.
- Do not print Gemini/Google keys, raw private note text, financial/health source passages, or credential-shaped values.
- Do not lower quality, duplicate, central-gate, or quota thresholds to make a candidate pass.
- Do not promote Gemini as default merely because a lane generated one good output. Promotion needs central-gate pass evidence.
- If quota is `STABLE_BLOCKED` or readiness is `BLOCKED_QUOTA`, stop and report the rerun-after time.

## Verification

For read-only validation, do not run the readiness ladder or any command with `--write`, `agy`, quota probing, process cleanup, or model calls; inspect existing artifacts and use JSON/static validation only.

For script changes, at minimum run the touched tests and syntax checks, for example:

```bash
python3 -m py_compile scripts/zettelkasten/codex-eval/gemini-quota-spenddown-readiness.py scripts/zettelkasten/codex-eval/gemini-central-promotion-gate-audit.py scripts/zettelkasten/codex-eval/gemini-burn-in-handoff.py
PYTHONPATH=scripts/zettelkasten/codex-eval python3 -m unittest scripts/zettelkasten/codex-eval/test_gemini_quota_spenddown_readiness.py scripts/zettelkasten/codex-eval/test_gemini_central_promotion_gate_audit.py scripts/zettelkasten/codex-eval/test_gemini_burn_in_handoff.py
```

For read-only audits, JSON-validate the gate artifacts and report the current lane board without running model calls.

## Closeout

Report:

```text
Current board:
Controlling artifacts:
Quota/provider state:
Central gate:
Lane decision:
Commands/checks run:
Model calls made:
Writes made:
Next gate:
Promotion recommendation:
```
