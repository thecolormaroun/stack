# TDD Anti-Patterns

## Process Anti-Patterns

### 1. Test After Code
❌ Write feature, then add tests
✅ Write test first, then code

Why it's bad: Tests become documentation, not design tool.

### 2. Big Bang Tests
❌ Write 10 tests, then implement all at once
✅ One test at a time, RED-GREEN-REFACTOR

Why it's bad: Lose the feedback loop. Hard to debug failures.

### 3. Skipping Refactor
❌ RED → GREEN → RED → GREEN (no refactor)
✅ RED → GREEN → REFACTOR → repeat

Why it's bad: Code rots. Technical debt accumulates.

### 4. Gold Plating
❌ Adding features "while I'm here" without tests
✅ If it's not tested, it doesn't exist

Why it's bad: Untested code breaks. Scope creep.

## Test Quality Anti-Patterns

### 5. Testing Implementation
❌ `expect(cart._items[0].id).toBe('1')`
✅ `expect(cart.getItem('1')).toBeDefined()`

Why it's bad: Tests break when refactoring. Brittle.

### 6. Multiple Assertions Testing Different Things
❌ One test checking add, remove, total, and empty
✅ Separate test for each behavior

Why it's bad: Hard to know what failed. Unclear intent.

### 7. Mystery Guest
❌ Test depends on external file or database state
✅ Test sets up all its own data

Why it's bad: Tests fail randomly. Can't run in isolation.

### 8. Assertion-Free Tests
❌ `it('should work', () => { cart.add(item); });`
✅ `it('should add item', () => { cart.add(item); expect(cart.items).toHaveLength(1); });`

Why it's bad: Test passes but proves nothing.

### 9. Copy-Paste Tests
❌ Same test repeated with minor variations
✅ Parameterized tests or shared setup

Why it's bad: Maintenance nightmare. Hard to update.

### 10. Testing Private Methods
❌ Exposing privates just to test them
✅ Test through public interface

Why it's bad: Tests coupled to implementation. Fragile.

## Naming Anti-Patterns

### 11. Vague Names
❌ `it('test1')` or `it('works')`
✅ `it('should return 0 when cart is empty')`

Why it's bad: Can't understand failure without reading code.

### 12. Implementation-Focused Names
❌ `it('calls the database')`
✅ `it('retrieves saved items')`

Why it's bad: Couples test to how, not what.

## Structural Anti-Patterns

### 13. Test Interdependence
❌ Test B depends on Test A's side effects
✅ Each test sets up its own state

Why it's bad: Order-dependent failures. Can't run in parallel.

### 14. God Test File
❌ 2000-line test file for one module
✅ Organize by behavior: `cart.add.test.ts`, `cart.remove.test.ts`

Why it's bad: Hard to find tests. Slow to run.
