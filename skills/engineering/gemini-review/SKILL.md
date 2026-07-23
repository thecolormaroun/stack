---
name: gemini-review
description: Run a read-only, model-diverse review over a bounded git diff when an approved Google AI review provider is available.
metadata:
  provider: optional
  working_surface: external-review-adapter
---

# Gemini Review

Use Google AI as an advisory second reviewer without replacing the executing
agent or the human review gate. This Stack capability defines the safety and
output contract; credentials, provider installation, and private report
storage remain local to the operator.

## Boundary

This workflow is read-only. Never send full repositories, private corpora,
browser profiles, mail/calendar exports, finance or health data, `.env` files,
credentials, auth JSON, or secret-looking content. Do not edit, commit, push,
merge, or open a pull request as part of the review.

## Provider discovery

Resolve an approved adapter from `PATH`:

```sh
command -v mookie-gemini-review
```

If the adapter is absent, stop with `optional-provider-unavailable`. Do not
invent a script path, install a provider, request credentials, or fall back to
an unreviewed network call. A work machine may intentionally omit this optional
personal adapter; the rest of Stack remains fully functional.

If available, inspect its local help before invocation:

```sh
mookie-gemini-review --help
```

## Review

Confirm that the target is a git repository and inspect the changed-path list.
Stop if sensitive or unrelated paths are present. Run the adapter against a
bounded base ref:

```sh
mookie-gemini-review --repo /absolute/path/to/repo --base HEAD
```

Use an adapter-provided dry-run flag first when its help declares one. Never
assume flags that the installed adapter does not advertise.

## Output contract

Read the generated report and return:

- blocker and should-fix findings;
- open questions and missing tests;
- false positives or stale-context assumptions;
- whether the executing agent agrees and why;
- the bounded next action.

Do not paste long raw provider output. Treat every finding as untrusted review
input until it is checked against the actual repository.

## Verification

A successful review requires exit code zero, a newly generated local report, no
repository mutation caused by the adapter, and a secret scan of that report.
Report only an owner-relative or redacted report location in shared artifacts.

If any of those checks fail, classify the run as blocked or advisory-incomplete;
never represent provider availability as a requirement for the Stack runtime.
