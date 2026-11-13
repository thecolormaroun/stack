# Upstream admission policy

Stack takes skills from other people's repositories in one of two modes. Each
provider in `registry/upstreams.json` records its mode in `"tracking"`.

- **`weekly`** (tracked provider). The weekly maintenance lane observes the
  provider's `HEAD`, re-materializes its mapped skills at the new commit, and
  proposes the update as a pull request.
- **`pick-only`**. Stack imports one reviewed skill at a time. The copy becomes
  Stack-owned the moment it lands: it lives in its family root (not under
  `skills/imported/`), keeps its origin and license notice in
  `references/source.md`, and never follows upstream again.

## Admission rule

A repository can be `weekly` only if all four hold. Anything else is
`pick-only`.

1. **OSI license file.** The repository contains a license file (`LICENSE`,
   `LICENSE.md`, `LICENSE.txt` or `COPYING`) with an OSI-approved license. A
   license reported by GitHub without a file does not count.
2. **Published for other people.** A README written for users, skill paths that
   stay put, and real commits. A mirror that pushes snapshot dumps from a
   private repository fails, however good its content is.
3. **No silent deletions.** The maintainer has a record of announcing removals
   and moves (changelog, release notes, deprecation), or the repository ships
   versioned releases.
4. **General-purpose skills.** Nothing tied to the author's machine, accounts,
   agents, private repositories or home-directory layout.

## What code enforces

- `scripts/stack-maintenance.py` rejects a provider whose `tracking` is not
  `weekly` or `pick-only`, and never observes a pick-only provider. Its
  observation row is `pick_only`, so it can never be proposed.
- `scripts/materialize-maintenance-proposal.py` and
  `scripts/discover-upstream-updates.py` refuse any provider that is not
  `weekly`.
- `scripts/import-pinned-skills.py` refuses a pick-only provider before any
  network access. For a weekly provider it checks the machine-checkable part of
  criterion 1 and 2 on the exact upstream checkout: an OSI license id, a license
  file and a README.
- `tests/test_upstream_admission.py` pins these checks and requires every
  provider to appear in the audit table below.

Stable paths, the deletion record and general-purpose content (criteria 2 to 4)
need a person. Record that review in the audit table.

## Changing a provider's mode

Open a pull request that changes the provider's `tracking` value and its row in
the audit table, with the evidence. Moving a provider to `pick-only` also
converts each of its tracked skills to Stack-owned, removes its rule from
`registry/maintenance-imports.json` and its root from the
`config/stack-maintenance.json` diff allowlist, and adds the converted paths to
the `stack-owned-imports` row in `registry/maintenance-sources.json`.

## Picking a skill from a pick-only provider

1. Read the upstream skill at an exact commit and decide it is useful outside
   its author's setup.
2. Copy it to `skills/<family>/<name>/` with a `capability.json` whose
   provenance is `repository-local`, `stack:skills/<name>` and the upstream
   license.
3. Write `references/source.md` with the origin repository, path, inspected
   commit and the full license notice.
4. Add the path to the `stack-owned-imports` row, then rebuild the generated
   artifacts and run the full suite (see `docs/stack-maintenance.md`).

## Provider audit, 2026-11-13

Audited at each repository's default-branch `HEAD`, looking back three months.
Only `david` changed mode. The others keep their current mode; a "pick-only"
verdict on a provider still marked `weekly` is an open decision for the owner.

| Provider | Repository at audit | 1 License | 2 Published | 3 Deletions / releases | 4 General | Verdict | Mode now |
| --- | --- | --- | --- | --- | --- | --- | --- |
| matt | mattpocock/skills `5863806` | MIT file | Pass. Skills move between bucket folders when promoted, always announced | Pass. 10 releases; the merge-conflicts removal is in CHANGELOG 1.3.0 | Pass | Pass | weekly |
| emil | emilkowalski/skills `f8ff3b0` | MIT file | Pass | Pass. No releases, but no skill has ever been removed | Pass | Pass | weekly |
| stewdio | StewdioAI/blank-page `5ac1be1` | MIT file | Pass, provisional | Fail. Ten days old, no releases or tags | Pass | Pick-only (3) | weekly |
| gstack | garrytan/gstack `43c815b` | MIT file | Pass | Pass. 9 releases; removals in CHANGELOG | Fail. 63 of 71 SKILL.md files call `~/.claude/skills/gstack/bin` | Pick-only (4) | weekly |
| compound-engineering | EveryInc/compound-engineering-plugin `ee46dde` | MIT file | Pass | Pass. 242 releases; removals listed in PR 967 | Pass | Pass | weekly |
| stack-codex | thecolormaroun/stack (this repository) | Stack-owned | n/a | n/a | n/a | Stack-owned bundle | weekly |
| david | davidondrej/skills `482d888` | MIT file | Fail. Every commit is "Publish sanitized skills snapshot" from a private repo; paths flattened on 2026-11-09 | Fail. No releases; 18 skill names gone without notice; history rewritten | Fail. cmux, Pi agent, `~/.agents` hooks | Pick-only (2, 3, 4) | pick-only |
| impeccable | pbakaus/impeccable `c4cd192` | Apache-2.0 file | Pass | Pass. 107 releases; consolidation announced | Pass | Pass | Stack-owned copy, not a provider |
| taste-skill | Leonxlnx/taste-skill `f6b7657` | MIT file | Fail. Layout restructured four times in eight months | Pass. 9 releases | Pass | Pick-only (2) | Stack-owned copy, not a provider |
| ui | ibelick/ui-skills `ba966a3` | MIT file | Pass | Pass. 8 releases, no deletions since January | Pass | Pass | not yet a provider |

Notes for the open decisions:

- **gstack** fails only because each skill needs gstack's own public runtime
  installed. If Stack accepts a provider-runtime dependency, it passes all four.
- **stewdio** should be re-audited after its first tagged release or in about
  90 days.
- **impeccable** upstream merged the 21 skills Stack carries into one
  `impeccable` skill on 2026-04-10. Tracking it would mean tracking that single
  skill, not the current copies.
- **taste-skill** upstream now ships one skill (`design-taste-frontend`). The
  soft-skill copy moved to Leonxlnx/taste-skill-classics.
