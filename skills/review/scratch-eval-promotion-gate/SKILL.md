---
name: scratch-eval-promotion-gate
description: "Run or audit scratch-only eval and judge-gate workflows without mutating source corpora. Use for Zettelkasten autoresearch prompt iteration, deterministic verifier passes, Gemini/Antigravity judge gates, source-grounding checks, claim-boundary checks, quota/readiness blockers, and promotion decisions."
---

# Scratch Eval Promotion Gate

Use this skill when a candidate prompt, evaluator, or research workflow must prove itself before promotion. The default posture is scratch-only until all gates pass with concrete artifacts.

## Evidence Order

1. Read the current run artifact or plan under `tmp/` first.
2. Inspect the harness scripts and expected thresholds before running anything.
3. Check quota/readiness gates before spending fixture or judge calls.
4. Use memory only for prior guardrails, then verify live files or counters when cheap.

## Scratch-Only Rules

- Keep generated artifacts under the repo's `tmp/` tree unless Maroun explicitly approves promotion.
- Do not write to Vault, source corpora, importer state, LaunchAgents, credentials, browser profiles, or production systems.
- Do not mark sources processed.
- Do not lower thresholds to make a candidate pass.
- Do not print secrets or raw sensitive source material.
- Unset model-provider environment variables for subprocesses when the local harness requires it.

## Validation Ladder

Prefer the repo's existing harness over ad hoc scripts. A good run records:
- readiness and quota state before spending;
- deterministic verifier command, result count, and threshold;
- judge-gate command and rubric dimensions, such as source grounding and claim boundaries;
- exact artifact paths for logs, reports, and closeout packet;
- pass/fail decision tied to the configured threshold.

If quota, auth, thin sources, or missing fixtures block the run before the harness executes, mark the result as readiness-blocked rather than quality-failed.

If repeated thin-source, incomplete-capture, placeholder, or source-depth failures stabilize across reruns, stop treating them as ordinary prompt quality misses. Classify them as `readiness/source-remediation-blocked`, preserve the blocker class in the closeout, and recommend the smallest source or fixture remediation before another retry loop.

## Promotion Rule

Recommend promotion only when the candidate passes the configured deterministic and judge gates, produces source-faithful output, preserves boundaries, and leaves a durable artifact that another run can inspect.

If it fails, report the smallest next fix: prompt change, fixture change, source collection issue, quota wait, or harness bug. Do not promote from narrative confidence.

## Closeout

Use this shape:

```text
Verdict:
Gate:
Artifacts:
What changed:
What did not change:
Blocker or next fix:
Promotion recommendation:
```
