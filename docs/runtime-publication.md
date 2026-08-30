# Runtime publication and recovery

Stack publishes compiled runtime outputs, never a direct copy of the raw
`skills/` tree. This ensures that a runtime sees only catalog entries that are
reviewed, validated, `active`, compatible with its runtime, and named in its
declared publish target.

## Compile, verify, install

1. Rebuild or verify [`registry/capabilities.json`](../registry/capabilities.json).
2. `scripts/bootstrap-stack.py --install` verifies the pinned Compound
   Engineering and GStack checkouts in `$HOME/.stack-packages`, then
   `scripts/compile-runtime.py` validates catalog digest, source paths,
   references, target metadata, dependency closure, and repository-owned bundle
   integrity before staging either target.
3. Each staged `runtime-manifest.json` records target, runtime, source commit,
   registry digest, included/excluded capabilities, package exports, generated
   command adapters, alias resolution, and explicit bundle-shadow decisions.
4. Each stage includes a deterministic `stage-attestation.json` binding the
   catalog digest, runtime-manifest digest, staged payload-tree digest, source
   commit, and source-tree digest. Compilation rejects dirty tracked sources
   and arbitrary commit overrides (non-Git fixtures may use a safe test id).
5. `scripts/install-runtime.py` recomputes that attestation, checks any
   configured catalog binding, then atomically changes each declared relative target
   pointer only after all relevant stages validate. Its receipt records prior
   target pointers, source commits, registry digest, target names, and status.
6. Each target independently verifies all 12 primary command adapters and every
   declared package/direct alias from its installed destination pointer before
   publication is considered complete. `stack-review` and `stack-ship` are
   explicit same-name collision resolutions: their generated canonical registry
   adapters shadow the corresponding Stack-Codex bundle exports.

An active canonical capability may declare bounded `compatibility_aliases`.
Reviewed deprecated compatibility adapters compile from their own warning
wrappers; other inactive/deprecated entries remain excluded. Registry command
aliases resolve to an existing local/package export when one exists, otherwise
the compiler writes a small canonical-warning adapter. Undeclared collisions
with local, external-package, or Stack-Codex skills fail before staging.

The live target contract is strict Claude/Codex parity:

- Claude: `$HOME/.claude/skills/stack`
- Codex: `$HOME/.codex/skills/stack`

From a clean checkout, the durable fresh-machine path is:

```sh
python3 scripts/bootstrap-stack.py --install \
  --expected-source-commit "$(git rev-parse --verify 'origin/main^{commit}')" \
  --deployment-root "$HOME" \
  --staging-root "$HOME/.local/share/stack/stages" \
  --receipts-dir "$HOME/.local/state/stack/runtime-receipts"
python3 scripts/stack-doctor.py --deployment-root "$HOME"
```

The checkout and deployment root remain separate. Compilation and installation
refresh the canonical Stack GitHub origin before compilation and again before
pointer movement, and require clean source `HEAD` to equal that supplied `origin/main` commit and
refuse dirty source/package checkouts, symlinked source roots, bad pins/origins,
payload leaks, unresolved runtime links, and partial target verification.
The compiler reads an installer-owned detached snapshot and writes a unique
0700 staging transaction. Each configured verifier runs only against a disposable
copy in a dedicated process group, which is terminated on success or timeout.
The installer then makes a fresh sealed publication copy and revalidates it
before and after linking. Failures persist receipts and restore switched pointers.

## Receipt and rollback

Publication is complete only when the source change, runtime compilation,
target installation/discovery, and receipt are verified. Catalog activation by
itself is not publication.

Receipts belong in an owner-only `0700` directory outside the public repository.
The publication receipt is redacted and contains no absolute paths; owner-only
rollback state keeps the prior pointer paths separately.

Each install writes an immutable owner-only pair at
`transactions/<transaction-id>/install.json` and `rollback.json`. The files
share the transaction ID and exact prior-target state. Root-level `latest.json`
and `rollback-state.json` remain mutable operational pointers and are not
automatic-promotion proof.

Automatic promotion accepts that pair only beneath the configured
`~/.local/state/stack/runtime-receipts` root. A byte-identical owner-only pair
in any other directory is rejected.

Hermes accepts a `published` intake disposition only after resolving the named
installation receipt beneath the configured trusted root above, matching its
source commit, catalog digest, verification
timestamp, passed target verifiers, and rollback coverage. Well-shaped evidence
without that owner-only receipt is not publication proof.

If a switch or target verification fails, restore each already-switched target
to the prior pointer recorded in the failed receipt. The installer performs
this restoration automatically for a switch failure; recovery for later target
verification uses the same recorded prior pointers. Re-run target discovery and
write a recovery result to the receipt trail. Do not rewrite source history,
hand-edit generated runtime manifests, or publish a partial target set.

## Scheduling boundary

The scheduler lanes remain distinct. Upstream maintenance has its own writer,
lease, and receipts. Hermes owns a Monday intake-only collection/curation lane.
The Stack weekly intelligence lane coordinates Saturday evidence and links the
latest maintenance receipt but never invokes maintenance. Under
`weekly-design-auto-promotion-approved-v1`, its separate automatic tail may
publish one evaluated Stack-owned skill/reference candidate after verified
merge. Collection, curation, evaluation, maintenance, and publication failures
remain distinct.

Stack provides a reviewed wrapper and reports the Stack commit and policy
digest. The approved Saturday 09:00 `America/Los_Angeles` contract becomes live
only when the existing Codex automation exactly matches the checked-in ID,
project, cadence, runtime, and prompt digest. After enablement, health requires
a terminal non-duplicate campaign receipt inside every eight-day window; a
scheduler entry alone is not proof.
