---
name: tdd
description: Test-driven development with red-green-refactor loop. Write tests first, make them pass, then refactor.
---

# TDD Skill

Build features test-first with the red-green-refactor loop.

**The idea:** Write a failing test, make it pass with minimal code, then refactor. Never write production code without a failing test.

---

## Workflow

Read `instructions/workflow.md` for the loop:

```
RED → GREEN → REFACTOR → repeat
```

1. **RED:** Write a failing test for one small behavior
2. **GREEN:** Write minimal code to make it pass
3. **REFACTOR:** Clean up without changing behavior

---

## Rules

Read `instructions/rules.md` for the discipline:

- One test at a time
- Smallest possible step
- No production code without failing test
- Refactor only when green

---

## Before Writing Tests

Read `examples/good/` for well-structured test patterns.

Read `examples/bad/anti-patterns.md` for test smells to avoid.

---

## After Test Pass

Run `eval/checklist.md`:
- Test isolation check
- Coverage check
- Refactor opportunity check

---

## Quick Reference

| Step | Question |
|------|----------|
| RED | "What's the next behavior I need?" |
| GREEN | "What's the simplest code that passes?" |
| REFACTOR | "How can I clean this up?" |
