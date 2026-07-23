# Brain Dump Extraction Patterns

## Voice Transcript Signals

### Feature Requests
- "I want to be able to..."
- "It would be cool if..."
- "We need a way to..."
- "Can you add..."
- "There should be..."
- "What about adding..."

### Bug Reports
- "This is broken..."
- "It's showing the wrong..."
- "This doesn't work when..."
- "[X] should be [Y] but it's [Z]"
- "I tried to [action] and it [failed]"

### Improvements
- "This is too [slow/confusing/cluttered]..."
- "It would be better if..."
- "The [X] is annoying because..."
- "Why can't I just..."
- "Make this [simpler/faster/prettier]"

### Strategic Direction
- "The vision is..."
- "Eventually I want this to..."
- "The killer feature would be..."
- "Think of it like [competitor] but..."
- "Phase 2 should be..."

### Priorities (explicit)
- "The most important thing is..."
- "First we need to..."
- "Don't worry about [X] yet"
- "The MVP is..."
- "[X] is a must-have, [Y] is nice-to-have"

## Extraction Rules

1. **One item per extracted feature** — don't merge multiple ideas
2. **Preserve the user's language** — use their words in descriptions
3. **Flag ambiguity** — if something could mean multiple things, ask
4. **Capture the "why"** — not just what they want, but why they want it
5. **Note emotional intensity** — strong feelings indicate priority
6. **Identify implicit features** — things they assume but don't say explicitly
7. **Separate vision from next-version** — don't over-scope

## Common Brain Dump Anti-Patterns

| Pattern | How to Handle |
|---------|---------------|
| "Build everything at once" | Break into versioned phases |
| "Make it like [complex app]" | Extract specific features, not the whole app |
| "It should just work" | Ask for specific acceptance criteria |
| Contradictory requirements | Flag as open question, ask for resolution |
| Feature disguised as bug | Classify as improvement, not bug |
