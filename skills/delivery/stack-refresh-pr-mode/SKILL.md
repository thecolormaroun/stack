---
name: stack-refresh-pr-mode
description: Refresh, verify, and publish the versioned Stack capability runtime through a review-safe branch or pull request without writing directly to main.
---

# Stack Refresh PR Mode

Use this workflow when asked to update Stack packages, validate a Stack change,
or publish a reviewed Stack revision into Claude and Codex.

Stack is the source of truth. Do not install raw folders from another workspace,
copy capabilities directly into global skill roots, or treat a plugin cache as
the catalog.

## Source order

1. Read the repository `README.md`, `registry/upstreams.json`, and
   `upstreams.lock.json`.
2. Inspect the current Stack branch, worktree, and remote.
3. Run `python3 scripts/sync-upstreams.py`. This verifies immutable pins and
   bundled package integrity; it does not mutate a live runtime.
4. Run `python3 scripts/stack-doctor.py` and the relevant tests.
5. Review every upstream pin or capability change before committing it.

## Refresh and publication

Keep source changes on a non-main branch and use a pull request. The minimum
repository gate is:

```sh
python3 scripts/classify-capabilities.py --check
python3 scripts/build-capability-registry.py --check
python3 scripts/apply-skill-layout.py --dry-run
python3 scripts/sync-upstreams.py
python3 -m unittest discover -s tests
scripts/security/scan-sensitive-content.sh
git diff --check
```

After the source revision is committed and the checkout is clean, install it
into the namespaced Claude and Codex targets:

```sh
python3 scripts/bootstrap-stack.py --install \
  --deployment-root "$HOME" \
  --staging-root "$HOME/.local/share/stack/stages" \
  --receipts-dir "$HOME/.local/state/stack/runtime-receipts"
python3 scripts/stack-doctor.py --deployment-root "$HOME"
```

The installer verifies pinned external packages, compiles only catalogued
capabilities, switches both targets atomically, and writes rollback receipts.
Never edit `.claude/skills/stack` or `.codex/skills/stack` by hand.

## Updating a package

An upstream update is complete only when its canonical source, immutable pin,
lock entry, export paths, license posture, package tests, and runtime discovery
all agree. A newer upstream commit is not automatically trusted. If the
checkout is dirty, the origin differs, or an export moved, stop publication and
retain the last-known-good pin.

Repository-owned Stack-Codex exports are bundled under
`packages/stack-codex/content`. Their sorted content digest must match the
package manifest, upstream registry, lock, and tests.

## Outcome classification

- `completed`: source gates, clean install, Claude discovery, and Codex
  discovery passed.
- `completed-with-warnings`: the runtime passed, but an optional provider or
  unrelated local tool needs attention.
- `blocked`: the source is dirty at publication time, a pin/origin/export is
  untrusted, either runtime fails discovery, or the branch cannot be shipped
  safely.

Report the branch and commit, package pins changed, test result, installation
receipt, both target discovery results, pull request or merge state, and any
remaining live scheduler gate.

## Hard stops

Stop before force-pushing, deleting user changes, changing protected
configuration, exposing secrets, or bypassing a failed pin, runtime, approval,
or publication check.
