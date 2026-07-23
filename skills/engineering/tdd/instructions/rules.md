# TDD Rules

## The Three Laws (Uncle Bob)

1. **You may not write production code until you have a failing test**
2. **You may not write more test than is sufficient to fail**
3. **You may not write more production code than is sufficient to pass**

## Practical Rules

### One Test at a Time
- Finish RED-GREEN-REFACTOR before starting next test
- Don't write multiple failing tests
- Don't skip ahead

### Smallest Possible Step
- Test one behavior, not a feature
- Write minimal code to pass
- Resist temptation to "while I'm here..."

### Stay Green
- Never leave tests red at end of session
- Commit when green
- Revert if stuck red too long

### Test Behavior, Not Implementation
❌ `expect(cart._items.length).toBe(1)` (testing internals)
✅ `expect(cart.itemCount).toBe(1)` (testing behavior)

### Refactor Only When Green
- Green = safe to change
- Red = fix the test first
- Never refactor while red

## What to Test

### Test Behaviors
- "When I do X, Y should happen"
- User-observable outcomes
- Public API surface

### Don't Test
- Private methods directly
- Implementation details
- Third-party libraries
- Trivial getters/setters

## Test Naming

**Pattern:** `should [expected behavior] when [condition]`

```typescript
it('should return empty array when cart is new')
it('should increase count when item added')
it('should throw when item is null')
```

## When TDD Is Hard

### Complex Setup
- Extract setup to beforeEach
- Use builder patterns
- Consider if design is wrong

### External Dependencies
- Mock at boundaries
- Use dependency injection
- Test integration separately

### UI Code
- Test logic separately from rendering
- Use component testing for interactions
- Snapshot tests for regression

## When to Skip TDD

- Exploratory spikes (but throw away the code)
- One-off scripts
- Prototype validation

But: if you're keeping the code, add tests.
