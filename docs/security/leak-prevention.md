# Leak Prevention

This repo is designed to be shared, so every pull request should pass two layers
of secret and sensitive-content checks before merge.

## Required PR Gate

The `Security scan` GitHub Actions workflow runs on pull requests and on pushes
to `main`.

- `Gitleaks` catches provider tokens, private keys, connection strings, and other
  standard secret patterns in the current tree.
- `Stack sensitive content` catches repo-specific risks such as local machine
  paths, Codex session artifacts, credential-like agent config fields, and
  household or finance-lane references.

Scanner output intentionally reports only file, line, and rule name. Do not paste
the matched secret value into chat, issues, pull request comments, or commit
messages while fixing a failure.

## Optional Local Hook

Install local hooks when working on this repo:

```bash
cd ~/Projects/stack
pre-commit install
```

Then run the checks manually before opening a PR:

```bash
pre-commit run --all-files
scripts/security/scan-sensitive-content.sh
go run github.com/zricethezav/gitleaks/v8@v8.30.1 dir --redact --config .gitleaks.toml .
```

The local hook is a convenience layer. GitHub Actions remains the enforced gate.

For a one-time audit of older commits, run Gitleaks in git-history mode:

```bash
go run github.com/zricethezav/gitleaks/v8@v8.30.1 git --redact --config .gitleaks.toml .
```

Treat real credentials in history as leaked and rotate them. Historical local
path findings should be cleaned from the current tree, but they do not require
credential rotation.

## If A Leak Is Found

1. Remove the sensitive value from the branch.
2. Rotate or revoke the credential if a real token, password, private key, or
   session artifact was committed or pushed.
3. Keep remediation notes generic: name the provider and file path, not the
   secret value.
4. Re-run the scanners before requesting review.
