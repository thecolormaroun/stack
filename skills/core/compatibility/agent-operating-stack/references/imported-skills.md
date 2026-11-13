# Imported Upstream Skills

These are the concrete namespaced imports added from the Meng To recommendation. They are prefixed to avoid overwriting Stack-native skills and to keep upstream provenance clear.

## Matt Pocock Engineering And Productivity Skills

| Local skill | Upstream skill | Upstream path |
| --- | --- | --- |
| `$matt-ask-matt` | `ask-matt` | `skills/engineering/ask-matt` |
| `$matt-code-review` | `code-review` | `skills/engineering/code-review` |
| `$matt-codebase-design` | `codebase-design` | `skills/engineering/codebase-design` |
| `$matt-diagnosing-bugs` | `diagnosing-bugs` | `skills/engineering/diagnosing-bugs` |
| `$matt-domain-modeling` | `domain-modeling` | `skills/engineering/domain-modeling` |
| `$matt-grill-with-docs` | `grill-with-docs` | `skills/engineering/grill-with-docs` |
| `$matt-implement` | `implement` | `skills/engineering/implement` |
| `$matt-improve-codebase-architecture` | `improve-codebase-architecture` | `skills/engineering/improve-codebase-architecture` |
| `$matt-prototype` | `prototype` | `skills/engineering/prototype` |
| `$matt-research` | `research` | `skills/engineering/research` |
| `$matt-setup-matt-pocock-skills` | `setup-matt-pocock-skills` | `skills/engineering/setup-matt-pocock-skills` |
| `$matt-tdd` | `tdd` | `skills/engineering/tdd` |
| `$matt-to-spec` | `to-spec` | `skills/engineering/to-spec` |
| `$matt-to-tickets` | `to-tickets` | `skills/engineering/to-tickets` |
| `$matt-triage` | `triage` | `skills/engineering/triage` |
| `$matt-wayfinder` | `wayfinder` | `skills/engineering/wayfinder` |
| `$matt-grill-me` | `grill-me` | `skills/productivity/grill-me` |
| `$matt-grilling` | `grilling` | `skills/productivity/grilling` |
| `$matt-handoff` | `handoff` | `skills/productivity/handoff` |
| `$matt-teach` | `teach` | `skills/productivity/teach` |
| `$matt-writing-great-skills` | `writing-great-skills` | `skills/productivity/writing-great-skills` |

## Stack-owned Former Imports

These started as imports. Stack owns them as of 2026-11-13 and no longer tracks upstream: their upstream copies were removed or moved, or their provider is pick-only (`davidondrej/skills`; see `docs/upstream-policy.md`). Each keeps its origin and MIT notice in `references/source.md`.

| Local skill | Origin skill | Origin path |
| --- | --- | --- |
| `$david-cmux` | `cmux` | `skills/agent-orchestration/cmux` |
| `$david-codex-subagent` | `codex-subagent` | `skills/agent-orchestration/codex-subagent` |
| `$david-fable-safe-prompt` | `fable-safe-prompt` | `skills/agent-orchestration/fable-safe-prompt` |
| `$david-goal-loop` | `goal-loop` | `skills/agent-orchestration/goal-loop` |
| `$david-handoff` | `handoff` | `skills/agent-orchestration/handoff` |
| `$david-anti-sleep` | `anti-sleep` | `skills/ops-and-setup/anti-sleep` |
| `$david-setup-help` | `setup-help` | `skills/ops-and-setup/setup-help` |
| `$david-browser-harness` | `browser-harness` | `skills/research-and-web/browser-harness` |
| `$david-deep-research` | `deep-research` | `skills/research-and-web/deep-research` |
| `$david-deepapi` | `deepapi` | `skills/research-and-web/deepapi` |
| `$david-effective-agent-skills` | `effective-agent-skills` | `skills/skill-authoring/effective-agent-skills` |
| `$david-read-all-adrs` | `read-all-adrs` | `skills/thinking-and-docs/read-all-adrs` |
| `$matt-resolving-merge-conflicts` | `resolving-merge-conflicts` | `skills/engineering/resolving-merge-conflicts` |
| `$david-agent-self-scheduling` | `agent-self-scheduling` | `skills/agent-orchestration/agent-self-scheduling` |
| `$david-create-readonly-db-role` | `create-readonly-db-role` | `skills/ops-and-setup/create-readonly-db-role` |
| `$david-cyber-audit` | `cyber-audit` | `skills/ops-and-setup/cyber-audit` |
| `$david-google-safe-browsing` | `google-safe-browsing` | `skills/ops-and-setup/google-safe-browsing` |
| `$david-research-prompt` | `research-prompt` | `skills/research-and-web/research-prompt` |
| `$david-youtube-transcript` | `youtube-transcript` | `skills/research-and-web/youtube-transcript` |
| `$david-folder-specific-claude-and-agents-md` | `folder-specific-claude-and-agents-md` | `skills/skill-authoring/folder-specific-claude-and-agents-md` |
| `$david-brain-to-docs` | `brain-to-docs` | `skills/thinking-and-docs/brain-to-docs` |
| `$david-prompt-me` | `prompt-me` | `skills/thinking-and-docs/prompt-me` |

Retired on 2026-11-13 (reasons in `docs/stack-maintenance.md`): `david-pi-web-search`, `david-pi-custom-model`, `david-push-skill-to-github`, `david-distribute-skill-to-all-agents`, `david-run-deep-swe`, `david-level-up`, `david-short`, `david-teach`.

## Source Pins

- Matt Pocock skills: `391a2701dd948f94f56a39f7533f8eea9a859c87`
- David Ondrej skills (pick-only; last inspected): `5c99080334072075eb9e0a17837f7d24e4f3e6ae`
