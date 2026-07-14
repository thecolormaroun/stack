---
name: gemini-review
description: "Run a read-only Google AI / Antigravity second-model review over a git diff. Use when Maroun asks for Gemini review, Antigravity review, Google AI review, second-model review, or model-diverse review of a repo/PR/diff."
metadata:
  local_wrapper: ~/bin/mookie-gemini-review
  report_dir: ~/hermes/reports/google-ai-pro
  working_surface: antigravity-cli
---

# Gemini Review

Use this skill to run Google AI as an advisory second reviewer without replacing Codex as the executor.

Despite the historical name, the current working model-call surface is **Antigravity CLI** through `~/bin/mookie-gemini-review`. Legacy `gemini-cli` is installed but is not supported for individual Code Assist model calls.

## Boundary

This is read-only and advisory.

Do not:

- edit files;
- push, commit, merge, or open PRs;
- run the review from inside `~/Vault`, private source corpora, browser profiles, Gmail/Calendar exports, finance, health, or credential directories;
- send `.env`, credentials, auth JSON, secret-looking files, raw finance/health/email bodies, or full repos;
- use `GEMINI_API_KEY` or `GOOGLE_API_KEY`;
- treat Gemini/Antigravity findings as authoritative without Codex/user review.

The wrapper unsets Gemini API key environment variables before invoking Antigravity. It also refuses sensitive-looking changed paths and sends only a redacted git diff/stat from a scratch directory.

## Source Of Truth

- Wrapper: `~/bin/mookie-gemini-review`
- Reports: `~/hermes/reports/google-ai-pro/`
- Scratch cwd for Antigravity calls: `~/hermes/tmp/google-ai-pro/login-smoke`

## Required Preflight

From any directory, confirm the wrapper and quota surface:

```bash
~/bin/mookie-google-ai-usage
~/bin/mookie-gemini-smoke --no-model-call
```

Both commands should return JSON with `ok: true` or a report path whose JSON says `ok: true`.

If either fails because Antigravity is not logged in, stop and report the login/auth blocker.

## Review Command

Run this against the target git repo:

```bash
~/bin/mookie-gemini-review --repo /absolute/path/to/repo --base HEAD
```

Optional knobs:

```bash
~/bin/mookie-gemini-review --repo /absolute/path/to/repo --base main --max-chars 80000
~/bin/mookie-gemini-review --repo /absolute/path/to/repo --out ~/hermes/reports/google-ai-pro/review-custom.md
```

## Output Contract

The wrapper prints the markdown report path. Read the report and summarize:

- blocker / should-fix findings;
- open questions;
- test gaps;
- whether the report is useful enough to act on;
- any false positives or stale-context issues.

Do not paste raw long output unless Maroun asks for it.

## Verification

A successful run has:

- exit code `0`;
- a report under `~/hermes/reports/google-ai-pro/`;
- no secret-looking strings in the report;
- no file changes in the reviewed repo caused by this skill.

Recommended secret scan for the new report:

```bash
rg -n 'AIza[0-9A-Za-z_-]{20,}|GEMINI_API_KEY=[0-9A-Za-z_./:+-]{8,}|GOOGLE_API_KEY=[0-9A-Za-z_./:+-]{8,}|x-goog-api-key: [0-9A-Za-z_./:+-]{8,}' ~/hermes/reports/google-ai-pro/review-*.md
```

An exit code of `1` from `rg` means no matches, which is good.

## Closeout

Close with:

- report path;
- verification commands run;
- top findings;
- whether Codex agrees, disagrees, or needs more context;
- next action, if any.
