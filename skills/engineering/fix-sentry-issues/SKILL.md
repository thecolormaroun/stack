---
name: fix-sentry-issues
description: Discover, triage, and fix production issues from Sentry with root-cause analysis.
---

# Fix Sentry Issues

Find and fix production errors systematically.

**Philosophy:** Fix root cause, never silence symptoms first.

---

## Workflow

Read `instructions/workflow.md`:

1. **Discover** — Pull unresolved issues from Sentry
2. **Triage** — Prioritize by user impact and frequency
3. **Investigate** — Find root cause via stack trace + context
4. **Fix** — Address root cause, not just symptom
5. **Verify** — Confirm fix in production

---

## Prioritization

Read `instructions/triage.md`:

| Priority | Criteria |
|----------|----------|
| **P0** | >100 users affected, data loss, security |
| **P1** | >10 users affected, broken feature |
| **P2** | <10 users, degraded experience |
| **P3** | Edge case, cosmetic |

---

## Before Fixing

Read `examples/bad/anti-patterns.md`:

🚨 **Never silence without diagnosing**
🚨 **Never catch-all exceptions**
🚨 **Never ignore recurring errors**

---

## After Fixing

Run `eval/checklist.md`:
- Root cause identified
- Fix addresses cause (not symptom)
- Tests added to prevent regression
- Sentry issue resolved

---

## Quick Reference

```bash
# List unresolved issues
sentry issues list --status unresolved

# Get issue details
sentry issues get ISSUE_ID

# Mark resolved
sentry issues resolve ISSUE_ID
```
