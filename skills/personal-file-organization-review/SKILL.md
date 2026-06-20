---
name: personal-file-organization-review
description: "Review Maroun's personal file organization plans and execution proposals across Desktop, Downloads, Google Drive, Cryptomator Vault, RoonDrive, Patch archives, Backblaze, and GBrain routing. Use when asked to critique, stress-test, validate, or improve file cleanup plans, manifest-backed moves, duplicate handling, Vault boundaries, or no-inbox direct processing."
---

# Personal File Organization Review

Use this skill to review file-organization plans before execution. The standard is not "tidy folders"; it is fewer chores, reversible moves, protected sensitive data, and useful GBrain routing.

## Review Posture

Review as a code reviewer would: findings first, ordered by risk. Prefer concrete fixes over general advice. Cite the plan file, manifests, scripts, or memory evidence used.

Default outcome: direct processing with manifests. Do not invent a user-facing inbox unless Maroun explicitly asks for one.

## Evidence Order

1. Read the current plan or artifact under review.
2. Read any generated manifests, move ledgers, duplicate reports, or post-run verification files.
3. Search memory only for current boundaries and prior decisions, then verify live files when cheap.
4. Inspect scripts only when execution behavior or safety depends on them.

## Invariants

Flag the plan if it violates any of these:
- No visible inbox workflow as the main user burden.
- Every processed file needs both a storage decision and a GBrain decision.
- Vault, tax, medical, identity, credential, genetic, Apple Health, and private finance content stays protected.
- Sensitive files may use metadata or approved sanitized summaries for GBrain, not raw body ingestion.
- Patch material stays together as a portfolio archive; duplicates are review-only unless proven safe.
- RoonDrive, PhotoStructure, Photos libraries, old laptop snapshots, `.bzvol`, and generated app internals are not casual delete targets.
- Backblaze is disaster recovery, not an organizing source of truth.
- Moves need durable manifests with source, destination, hash or stable identity, reason, confidence, review flag, and rollback enough to audit.
- Logs and reports must be redacted when paths or filenames expose sensitive personal data.

## Risk Checks

Look especially for:
- review manifests turning into a hidden inbox;
- classifier trust boundaries missing for cloud LLM/API use;
- broad GBrain metadata exhaust over millions of files;
- review-only manifests that contain only `path,reason` instead of enough routing, confidence, sensitivity, and rollback context to make a decision;
- missing standalone GBrain routing manifests or missing `gbrain_action` coverage after an execution run;
- ambiguous duplicate deletion in media libraries or backups;
- stale archive cleanup before unique Patch assets are preserved;
- work shared-drive placeholders or external account surfaces being treated as local cleanup targets;
- success claims without post-run verification.

## Manifest Shape Audit

When execution artifacts already exist, do a shape audit before judging quality:
- list manifest filenames and row counts;
- inspect headers only unless row bodies are necessary and safe;
- confirm move manifests include storage destination, reason, confidence, review flag, and rollback/audit identity;
- confirm review-required manifests include enough fields to avoid becoming a second inbox;
- confirm GBrain routing is present as a standalone manifest or explicit per-row `gbrain_action` coverage;
- confirm post-run verification ties claims back to manifest counts.

## Output Shape

Use:

```text
Findings
1. [severity] Title - evidence and fix.

Open Questions
- Only questions that block safe execution.

Verdict
- Ready, revise before execution, or blocked.

Verification Gate
- The specific manifest, dry-run, hash check, or post-run artifact that proves the next step.
```

If no issues are found, say that clearly and name residual risks or missing test coverage.
