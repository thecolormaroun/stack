# TDD Checklist

## Per-Cycle Checklist

Run after each RED-GREEN-REFACTOR:

| # | Check | Pass/Fail |
|---|-------|-----------|
| 1 | **Test failed first** — Saw red before green | |
| 2 | **Minimal code** — No extra features added | |
| 3 | **Refactor done** — Cleaned up after green | |
| 4 | **Tests still pass** — Green after refactor | |
| 5 | **Committed** — Changes saved | |

## Test Quality Checklist

| # | Check | Pass/Fail |
|---|-------|-----------|
| 1 | **Tests behavior** — Not implementation | |
| 2 | **One assertion focus** — Tests one thing | |
| 3 | **Self-contained** — No external dependencies | |
| 4 | **Descriptive name** — "should X when Y" | |
| 5 | **Fast** — Runs in <100ms | |

## Coverage Checklist

| # | Check | Pass/Fail |
|---|-------|-----------|
| 1 | **Happy path** — Normal flow tested | |
| 2 | **Edge cases** — Empty, null, boundary | |
| 3 | **Error cases** — Invalid input handled | |
| 4 | **No dead code** — All branches reachable | |

## Refactor Checklist

| # | Check | Pass/Fail |
|---|-------|-----------|
| 1 | **No duplication** — DRY principle | |
| 2 | **Clear names** — Intent obvious | |
| 3 | **Small functions** — Single responsibility | |
| 4 | **Tests unchanged** — Same assertions | |

## Session End Checklist

| # | Check | Pass/Fail |
|---|-------|-----------|
| 1 | **All green** — No failing tests | |
| 2 | **Committed** — Work saved | |
| 3 | **Coverage stable** — Didn't decrease | |
| 4 | **No TODOs** — Or tracked if deferred | |

## Quality Gates

### Gate 1: Red First
```
Did I see the test fail before writing code?
```
If no → you're not doing TDD.

### Gate 2: Minimal Green
```
Did I write more code than needed to pass?
```
If yes → delete the extra. Test it separately.

### Gate 3: Clean Refactor
```
Is the code better after refactor?
```
If not better → refactoring worked.
If worse → revert.
