---
name: agent-verification-ladder
description: "Choose and run the right proof level before an agent claims work is complete. Use when Maroun asks whether an agent workflow, automation, Mookie/Hermes change, repo fix, browser task, generated artifact, or background thread is actually working and needs evidence stronger than a narrative summary."
---

# Agent Verification Ladder

## Overview

Use this skill to turn "looks done" into a concrete proof plan. Match verification cost to blast radius, run the cheapest meaningful checks first, and stop with a named blocker instead of claiming completion from weak evidence.

## Ladder

Pick the lowest level that can genuinely prove the current claim:

1. Artifact proof: inspect the exact file, report, diff, log, or saved output.
2. Command proof: run the relevant local command, test, lint, parser, or status check.
3. State proof: verify the live service, database, queue, lock, branch, deployment, or thread status that the claim depends on.
4. Browser/UI proof: use `agent-browser` for pages, screenshots, authenticated UI state, visual checks, and frontend smoke tests when a browser is the user-facing surface.
5. Cross-run proof: compare current output against prior automation memory, session logs, PR checks, or deployment history when the workflow is recurring.
6. Independent proof: use a focused validation thread or isolated worktree when the workflow is broad, risky, or needs a fresh agent to exercise it.

## Workflow

1. State the claim in one sentence.
2. Identify the source of truth for that claim: file, command, UI, service state, PR/check, deployment, automation memory, or user-visible artifact.
3. Choose the proof level from the ladder and name why lower levels are insufficient.
4. Run the check or record the exact blocker that prevents it.
5. For automation or service claims, require a bounded claim check: artifact timestamp, paired machine-readable report path when available, current state check, weak evidence explicitly rejected, and held/watch/out-of-scope items named.
6. Report the result as `passed`, `failed`, `blocked`, or `partial`; include the command/artifact/thread id without dumping sensitive content.
7. If the same blocker repeats, stop retries and recommend the smallest next fix or owner action.

## Choosing Evidence

- Repo work: prefer tests, build/lint/typecheck, git status, and focused diffs.
- Web work: prefer HTTP checks plus `agent-browser` smoke or screenshot when rendering matters.
- Automation work: read the automation memory first, then verify current files, command exit status, and remaining warnings.
- Hermes/Mookie/Zouzou work: separate runtime health from auth, locks, queues, LaunchAgents, browser state, and external accounts.
- Sensitive work: paraphrase private evidence; do not print credentials, personal finance details, private health details, browser profile contents, or raw scraped personal content.
- Background threads: inspect the thread output and artifact; do not treat thread creation as validation.

## Hard Stops

- Do not mutate production, credentials, source corpora, Vault, browser profiles, financial data, email/calendar, or LaunchAgents just to get stronger proof.
- Do not invent a passing gate when the real source of truth is unavailable.
- Do not treat "no error shown" as proof unless the task's success criterion is specifically absence of errors.
- Do not run expensive, destructive, or account-changing checks without explicit approval.

## Closeout

Close with the claim, proof used, verdict, residual risk, and next gate. If validation was partial, name exactly what remains unproven.
