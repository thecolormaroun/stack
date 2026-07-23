---
name: goal-validation-threads
description: "Create and inspect focused Codex validation threads for candidate skills, workflows, automation changes, or multi-agent plans. Use when a draft skill or workflow needs independent forward-testing with /goal prompts, project resolution, isolated worktrees for mutating tests, concrete pass/fail gates, and promotion/revision recommendations."
---

# Goal Validation Threads

Use this skill to validate whether a candidate skill or workflow actually helps in a fresh Codex thread. The validation must exercise the candidate on a realistic target and produce inspectable evidence.

## Candidate Intake

For each candidate, record:
- skill name and draft path;
- motivating evidence from real threads, commands, artifacts, blockers, or automation results;
- target project/repo/path;
- whether validation can be read-only or might modify repo state;
- expected output artifact and pass/fail gate.

Validate at most three candidates in one run unless Maroun explicitly raises the cap.

## Thread Prompt Contract

Each validation thread prompt must include:

```text
/goal
Objective:
Target path/repo:
Skill under test:
Allowed actions:
Hard stops:
Expected output artifact:
Pass/fail gate:
High-quality output means:
Report back with:
```

Use the draft skill as an input, not a hidden answer key. Do not tell the validator the conclusion you want.

## Isolation Rules

- Use project resolution before creating threads when the platform exposes `list_projects`.
- Use a worktree when validation may change repo state.
- Use local/no-worktree only for strictly read-only validation.
- Do not validate against source corpora, Vault, credentials, browser profiles, external accounts, email/calendar, LaunchAgents, production systems, or unrelated repos.
- Do not merge, push to main, install global/runtime changes, or promote a skill automatically.

## Inspect Results

After a validation thread finishes or clearly blocks, inspect:
- thread id or pending worktree id;
- output artifact path;
- commands/checks used;
- whether the candidate skill was actually used;
- pass/fail evidence;
- isolation choice, such as local read-only, local mutating, or worktree;
- quality notes;
- smallest next fix if failed.

Recommend promotion only with concrete pass evidence and a useful output. If the thread is queued, unavailable, or blocked before validation, mark the candidate blocked rather than passed.

## Closeout

For each candidate, report:

```text
Skill:
Evidence:
Draft path:
Validation thread:
Validation gate:
Verdict:
Recommendation:
Isolation:
```

Keep sensitive evidence paraphrased and label private/sensitive lanes when needed.
