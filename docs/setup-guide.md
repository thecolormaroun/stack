# Setup Guide

## Prerequisites
- Claude Code CLI installed
- GitHub CLI (`gh`) for the github plugin

## Safe Stack Runtime Readiness

From a fresh Stack checkout, run the read-only readiness gate first:

```bash
python3 scripts/bootstrap-stack.py
python3 scripts/stack-doctor.py
```

Both commands only read the checkout by default. They validate package pins and
integrity, registry/command parity, active capability classification, and
runtime compilation/install readiness. A non-empty runtime target must pin the
current capability catalog digest and retain the compiler's clean-source
publication protection.

Runtime installation is deliberately separate and requires every explicit
argument below. `--deployment-root` is the only location that receives runtime
targets and its `.stack-packages` cache; use `$HOME` for normal tool integration
and keep it separate from the checkout:

```bash
python3 scripts/bootstrap-stack.py --install \
  --deployment-root "$HOME" \
  --staging-root "$HOME/.local/share/stack/stages" \
  --receipts-dir "$HOME/.local/state/stack/runtime-receipts"
python3 scripts/stack-doctor.py --deployment-root "$HOME"
```

The install verifies the immutable Compound Engineering and GStack commits in
that deployment-owned cache, verifies the Stack-Codex bundle digest, then
atomically switches `.claude/skills/stack` and `.codex/skills/stack` beneath
the deployment root. It refuses a dirty source checkout for a real install;
the default readiness command remains read-only and works in a dirty tree.

`stack-doctor.py` prints a sanitised report with the source commit and dirty
state, never local destination or receipt paths. It fails closed on command or
alias collisions, stale aliases, missing Claude/Codex parity, package-pin
drift, or an unclassified active capability.

The staging directory is durable because the installed runtime namespaces are
atomic symlinks into it. Do not use `/tmp` for a real installation.

## Installed package surface

Bootstrap acquires the exact Compound Engineering and GStack commits declared
in `registry/upstreams.json`, then stages only their declared exports. It also
verifies and stages the repository-owned Stack-Codex bundle. No separate
marketplace installation is required for those declared Stack routes.

Repository configuration under `config/` is source material, not a global
settings replacement. Bootstrap does not overwrite existing Claude or Codex
settings.

## Skills
Skills can be included per-project (drop in repo root) or globally.

### Studio Skill Graph
The skill graph is a structured knowledge base. Reference it from your project's CLAUDE.md:
```markdown
## Studio Parity (Skill Graph)
When doing product/design/UI work, consult:
- `skills/studio/_graph/studio.moc.md`
- `skills/studio/_graph/design/design.moc.md`
```

### Individual Skills
Drop any skill folder into your project. Each has a SKILL.md with usage instructions.
