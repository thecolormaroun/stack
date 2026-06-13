# Setup Guide

## Prerequisites
- Claude Code CLI installed
- GitHub CLI (`gh`) for the github plugin

## Install Plugins
```bash
# Third-party
claude plugins install compound-engineering@every-marketplace
claude plugin marketplace add tmchow/illo-skill
claude plugin install illo@illo-skill

# Official plugins — enable in ~/.claude/settings.json
# They auto-install from claude-plugins-official
```

## Apply Config
```bash
cp config/CLAUDE.md ~/.claude/CLAUDE.md
cp config/settings.json ~/.claude/settings.json
cp config/settings.local.json ~/.claude/settings.local.json
```

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
