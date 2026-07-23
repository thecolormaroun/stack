# Upstream Resolution

Stack treats Compound Engineering and GStack as pinned external packages. A
clean Stack clone verifies their declared origins and commits through
`scripts/bootstrap-stack.py`; an installation stages only their declared
exports into the same runtime skill namespace as this bundle.

## Runtime-first resolution

Invoke installed capabilities by name instead of assuming an external
workspace layout:

- GStack: `autoplan`, `office-hours`, `design-consultation`, `review`, `qa`,
  `ship`, and other declared GStack exports.
- Compound Engineering: `ce-ideate`, `ce-brainstorm`, `ce-plan`, `ce-work`,
  `ce-code-review`, `ce-simplify-code`, `ce-test-browser`,
  `ce-commit-push-pr`, and other declared Compound Engineering exports.

The runtime compiler publishes each declared export as a sibling skill. When a
named upstream capability is unavailable, do not search arbitrary home
directories or silently substitute a different package. Use the inline
fallback documented by the calling Stack skill and report that the package
enhancement was unavailable.

## Repository and cache discovery

For package health or maintenance, resolve the Stack checkout:

```bash
STACK_REPO_DIR="${STACK_REPO:-$(git rev-parse --show-toplevel)}"
```

Run the shipped doctor or bootstrap tools from that checkout. Bootstrap owns
the external checkout cache beneath the explicit `--deployment-root` as
`.stack-packages/`; skills must not mutate it directly.

## Command intent map

- `lfg`: plan -> work -> simplify -> review -> verify -> optional ship
- `mega`: larger composition of ideate, plan, lfg, and verification
- `ideate`: shape product and UX, then produce a buildable plan
- `review`: findings-first risk review
- `ship`: verified delivery with explicit approval for external mutation
- `sync`: verify Stack metadata and optionally run the shipped bootstrap path
