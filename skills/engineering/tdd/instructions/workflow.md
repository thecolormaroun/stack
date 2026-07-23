# TDD Workflow

## The Red-Green-Refactor Loop

```
┌─────────────────┐
│      RED        │  Write a failing test
│  (test fails)   │  for one small behavior
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│     GREEN       │  Write minimal code
│  (test passes)  │  to make test pass
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│    REFACTOR     │  Clean up code
│  (still green)  │  without changing behavior
└────────┬────────┘
         │
         └──────────▶ repeat
```

## Step 1: RED — Write a Failing Test

1. Pick ONE behavior to test
2. Write the test FIRST (before any code)
3. Run the test — it MUST fail
4. If it passes, something's wrong

**Good failing test:**
```typescript
it('should add item to cart', () => {
  const cart = new Cart();
  cart.add({ id: '1', price: 10 });
  expect(cart.items).toHaveLength(1);
});
// Fails: Cart doesn't exist yet
```

## Step 2: GREEN — Make It Pass

1. Write the MINIMUM code to pass
2. Don't anticipate future needs
3. Ugly code is fine (for now)
4. Run test — it MUST pass

**Minimal passing code:**
```typescript
class Cart {
  items: Item[] = [];
  add(item: Item) {
    this.items.push(item);
  }
}
// Test passes. Done.
```

## Step 3: REFACTOR — Clean Up

1. Tests are green — safe to refactor
2. Remove duplication
3. Improve naming
4. Simplify logic
5. Run tests after each change — stay green

**Refactored:**
```typescript
class Cart {
  private _items: Item[] = [];
  
  get items(): readonly Item[] {
    return this._items;
  }
  
  add(item: Item): void {
    this._items.push(item);
  }
}
// Still green. Better encapsulation.
```

## Step 4: Repeat

Pick the next behavior:
- "What if I add two items?"
- "What if the item already exists?"
- "What about the total?"

Each behavior = one RED-GREEN-REFACTOR cycle.

## Sizing Guidance

| Cycle Size | Time | Example |
|------------|------|---------|
| Too small | <1 min | "Test that Cart class exists" |
| Just right | 2-10 min | "Test that adding item increases count" |
| Too big | >15 min | "Test full checkout flow" |

If a cycle takes >15 min, break it down.
