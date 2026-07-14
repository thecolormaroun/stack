# Agent Operating Stack Source Map

## Source Intake

- Meng To X post: https://x.com/MengTo/status/2075221793925955897
  - Published: 2026-07-09.
  - Interpretation: pair Emil Kowalski's design-engineering skill set with Matt Pocock's engineering skills and David Ondrej's agent-orchestration skills.
- Matt Pocock skills: https://github.com/mattpocock/skills
  - Inspected commit: `391a2701dd948f94f56a39f7533f8eea9a859c87`.
  - License: MIT.
- David Ondrej skills: https://github.com/davidondrej/skills
  - Inspected commit: `5c99080334072075eb9e0a17837f7d24e4f3e6ae`.
  - License: MIT.
- Emil Kowalski skill already present in Stack:
  - Local path: `skills/emil-design-eng`.
  - Current local source pin: `f76beceb7d3fc8c43309cefad5a095a206103a4e`.
  - License posture: upstream repo has no explicit GitHub license in the existing Stack metadata, so keep it as attributed reference material.

## Local Adoption Decision

Import the upstream skills concretely, but keep them namespaced:

- Matt Pocock skills live under `skills/matt-*`.
- David Ondrej skills live under `skills/david-*`.
- The import manifest is [imported-skills.md](imported-skills.md).

This avoids overwriting Stack-native skills such as `tdd`, `teach`, `handoff`, `research`, or Hermes-specific workflows, while still making the upstream skills directly invokable. `agent-operating-stack` remains the router that composes those imports with Emil design craft, Stack-native product/design skills, and Maroun's Hermes boundaries.

## Concept Mapping

| Upstream concept | Stack adaptation |
| --- | --- |
| Matt's ask/router skill | `$matt-ask-matt` for the upstream router; `agent-operating-stack` for Maroun/Hermes routing. |
| Matt's grill/spec/tickets/implement loop | `$matt-grill-with-docs`, `$matt-to-spec`, `$matt-to-tickets`, `$matt-implement`, `$matt-tdd`, and `$matt-code-review`. |
| Matt's bug diagnosis loop | `$matt-diagnosing-bugs`; require a red-capable feedback command before theory-heavy debugging. |
| Matt's domain modeling and codebase design | `$matt-domain-modeling` and `$matt-codebase-design`; use `CONTEXT.md` and ADRs only where durable vocabulary/decisions justify them. |
| David's `/goal` contract | `$david-goal-loop`; encode long-running work as objective, constraints, validation, documentation, checkpoints, and stop condition. |
| David's subagent rules | `$david-codex-subagent`; delegate only self-contained tasks with full prompt context, isolated file ownership, and post-run review. |
| David's handoff/scheduling skills | `$david-handoff` and `$david-agent-self-scheduling`; prefer durable handoff artifacts and Hermes-native scheduling for Hermes work. |
| David's skill-authoring guidance | `$david-effective-agent-skills`, `$david-folder-specific-claude-and-agents-md`, and related imports; keep Stack skills lean, source-pinned, validated, and discoverable with `agents/openai.yaml`. |
| Emil's design engineering | Keep UI work routed through `emil-design-eng`, `review-animations`, and Studio/CDO design gates. |

## Hermes Leverage

Hermes should leverage this through:

- `agents/openai.yaml` discovery for OpenAI/Codex-style skill surfaces;
- direct `$matt-*` and `$david-*` imported skill invocation for focused upstream workflows;
- prompts that name `$agent-operating-stack` when broad Hermes/Mookie work needs a safe loop;
- composition with `hermes-native-patch-migration` for update-safe local extension work;
- composition with `agent-verification-ladder` before claiming runtime success;
- `/goal` contracts only when the validation command and stop condition are explicit.

Hermes should not use this as permission to mutate credentials, external accounts, production services, Vault, browser profiles, source corpora, or LaunchAgents without an explicit approval gate.
