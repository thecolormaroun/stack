---
name: live-site-health-check
description: "Audit Maroun's live website surfaces and classify code, GitHub, Vercel, browser, and account/deployment blockers. Use when asked for weekly live-site health checks, dependency PR follow-through, production smoke tests, stuck Vercel deployments, security headers, or whether a safe repo-side patch already exists."
---

# Live Site Health Check

Use this skill for Maroun's recurring website maintenance loop. The goal is not just to open PRs; it is to report the current production truth, safe repo-side fixes, and the exact remaining gate.

## Evidence Order

1. Read the automation memory when present:
   - `~/.codex/automations/weekly-live-site-health-check/memory.md`
   - `~/.codex/automations/weekly-website-dependency-maintenance/memory.md`
2. Inspect the relevant local repo state before editing: branch, dirty files, remotes, open PRs, and package manager.
3. Check GitHub PRs, review comments, and checks for the current head commit.
4. Check Vercel deployment/project/domain state when available.
5. Run HTTP and browser smoke checks against the public production or preview URLs.

Treat old deployment records as historical unless they match the active PR, commit, or production alias.

Use `agent-browser` by default for browser smoke, screenshots, authenticated visual checks, and frontend/dev-server verification when browser work is needed. If `agent-browser` is unavailable, record the setup blocker before falling back to simpler HTTP checks.
Re-check live state before carrying a blocker forward. A prior Vercel/team/deploy blocker can be historical after access changes, merges, or production redeploys.

## Standard Checks

Use repo-specific commands, but prefer this ladder when it applies:

```bash
npm outdated || true
npm ci
npm run lint
npm test
npm run build
npm audit --audit-level=moderate
```

When the request is validation-only or explicitly read-only, do not run mutation-capable package commands, dependency installs, local servers, browser-profile automation, or write-producing checks. Use memory, repo status, GitHub/Vercel inspection, and public HTTP checks instead, and say which deeper checks were skipped because of the read-only boundary.

Validation-only runs may also skip `agent-browser` and package-registry checks when the delegation forbids browser-profile, cache, dependency, or network-side effects and HTTP/Vercel/GitHub checks are sufficient.

For production/deployment state, record:
- public URL, key routes, redirects, and status codes;
- security headers worth acting on;
- `/api/health` or equivalent health endpoint behavior;
- TLS/certificate validity windows when the run is checking public production health;
- `gh pr checks` and current PR head SHA;
- Codex review request/status on the current PR head, including whether the review is clean, pending, or only acknowledged;
- Vercel inspect/log findings tied to the current deployment;
- browser smoke result, using `agent-browser` by default.

## Boundaries

- Do not route deployment access through a work email path.
- Do not mutate production configuration, external accounts, credentials, browser profiles, or DNS.
- Do not reopen duplicate patches when an existing PR already fixes the code path.
- Do not clean or reset dirty local checkouts unless Maroun explicitly asks.
- Use a clean worktree for verification if the primary checkout is dirty.

## Blocker Classification

Separate these in the closeout:
- healthy production surface;
- repo-side bug with safe local fix;
- existing PR waiting on review, checks, or deploy;
- existing PR waiting specifically on Codex review after checks are green;
- account/team/domain/deployment configuration blocker;
- local-only blocker, such as missing development env vars;
- historical blocker that no longer matches the active head/deployment.
- deployment-only project without a matching local/GitHub repo.

## Closeout

Start with what Maroun should do next. Then list sites checked, safe fixes or PRs, verification commands, browser smoke result, blockers, and the exact waiting state. If a PR was opened or updated, say that review/deploy is still the gate unless those checks actually passed.
