---
name: knip
description: Find and remove unused files, dependencies, and exports using knip.
---

# Knip Skill

Find and remove dead code.

**Command:** `npx knip`

---

## When to Use

- After removing features
- Before major refactors
- Periodic codebase cleanup
- Reducing bundle size

---

## Workflow

Read `instructions/workflow.md`:

```bash
# Find unused code
npx knip

# Fix automatically (careful!)
npx knip --fix

# Show only specific types
npx knip --include files,dependencies
```

---

## What Knip Finds

| Type | Description |
|------|-------------|
| **Unused files** | Files not imported anywhere |
| **Unused dependencies** | Package.json deps not imported |
| **Unused exports** | Exported but never imported |
| **Unused types** | TypeScript types defined but unused |
| **Duplicate exports** | Same thing exported multiple times |

---

## After Running

Run `eval/checklist.md`:
- Review each finding
- Verify not false positive
- Remove or mark as intentional

---

## Quick Reference

```bash
# Full scan
npx knip

# Specific category
npx knip --include dependencies

# Auto-fix (dangerous)
npx knip --fix

# Ignore pattern
npx knip --ignore "*.test.ts"
```
