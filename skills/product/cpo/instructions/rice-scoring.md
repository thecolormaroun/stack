# RICE Scoring Guide

## The Formula

**RICE Score = (Reach × Impact × Confidence) / Effort**

## Factor Definitions

### Reach (1-10)
How many users/sessions will this affect per quarter?

| Score | Meaning |
|-------|---------|
| 10 | Every user, every session |
| 7-9 | Most users, frequently |
| 4-6 | Some users or occasionally |
| 1-3 | Few users or rare edge case |

### Impact (0.25-3)
How much does it improve the experience when it hits?

| Score | Meaning |
|-------|---------|
| 3 | Massive — life-changing for those affected |
| 2 | High — clear, noticeable improvement |
| 1 | Medium — nice to have |
| 0.5 | Low — minor polish |
| 0.25 | Minimal — almost imperceptible |

### Confidence (50%, 80%, 100%)
How sure are we about Reach and Impact estimates?

| Score | Meaning |
|-------|---------|
| 100% | Data-backed or shipped before |
| 80% | Strong hypothesis, some evidence |
| 50% | Gut feel, untested assumption |

### Effort (1-10)
Engineering time in story points.

| Score | Meaning |
|-------|---------|
| 1 | An hour or less |
| 2-3 | Half day to a day |
| 4-5 | A few days |
| 6-7 | A week |
| 8-10 | Multiple weeks |

## Example Scoring

**Feature: Add favorites to baby food app**
- Reach: 8 (most active users would use this)
- Impact: 2 (high — saves time daily)
- Confidence: 80% (users have asked for this)
- Effort: 3 (a day or two)

**RICE = (8 × 2 × 0.8) / 3 = 4.3**

**Feature: Add allergy warnings**
- Reach: 3 (only affects users with allergies)
- Impact: 3 (massive for those affected — safety)
- Confidence: 80%
- Effort: 5 (needs research + UI + data)

**RICE = (3 × 3 × 0.8) / 5 = 1.4**

Favorites wins on RICE, but allergies might win on risk/liability.

## When RICE Isn't Enough

Override RICE for:
- **Safety issues** — always P0 regardless of reach
- **Legal/compliance** — must ship
- **Technical debt** — blocking other work
- **Strategic bets** — low confidence but high upside

Note the override reason in the PRD.
