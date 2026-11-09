# Stack critique and review, 2026-11-06

Reviewer: Claude (Fable 5.1), at Maroun's request. Scope: the whole repo at commit `245e598` (main), the installed Claude runtime at `~/.claude/skills/stack`, the workspace copies under `~/Claude/skills`, and the upstream pins. Lenses applied: the compound-engineering doc-review personas (coherence, feasibility, product lens), the gstack DX-review rubric (time to hello world, findability, upgrade path), and the repo's own inclusion test from `docs/architecture.md`.

Everything below was measured on this machine today. Where a number matters it is in a table, not prose.

---

## 1. Verdict

Stack is a well-built control plane for a factory that has no production line and, until yesterday, no customers.

- The governance machinery is real and correct. Pinned upstreams, atomic install with rollback receipts, 505 passing tests, secret scanning, deterministic registry. None of that is the problem.
- The machinery is sized for a multi-runtime, multi-model, scheduler-driven system (Codex Sol/Terra/Luna, Hermes, GBrain, Field Theory, a Codex automation). None of those exist on this machine. Codex is not installed. Hermes is not installed. GBrain is not installed. The weekly-intelligence checkout does not exist. The Codex target at `~/.codex/skills/stack` is published to a host with no CLI.
- The one runtime that is used, Claude Code, loaded nothing from Stack until PR #46 (yesterday). Installs reported success for months while zero skills were visible. The tests verified the machine, never the outcome.
- The skills themselves are mostly good, but there are too many of them, they collide with three other copies of the same skills on this machine, and the catalog's own visibility tiers have no effect on what gets loaded.

Recommendation, in one line: keep the catalog, compiler and installer; delete the intelligence and maintenance lanes and the Codex target; cut the published skill count by roughly two thirds; then build a thin factory line on Claude Code's native primitives, fed by retros of real builds rather than X bookmarks. Details in sections 6 through 8.

---

## 2. What it is, by the numbers

| Measure | Value |
| --- | --- |
| Catalogued capabilities | 158 (150 active, 8 deprecated adapters) |
| Published skill folders in the Claude runtime | 189 |
| Stack-owned capabilities | 46 |
| Imported capabilities | 112 (david 29, matt 22, impeccable 21, emil 16, studio 14, ui 5, taste 4, stewdio 1) |
| Primary-visibility capabilities | 3 |
| Lines of Python in `scripts/` | 25,347 |
| Lines of Python in `tests/` | 13,304 (505 tests, pass in 71s) |
| Lines of SKILL.md across the estate | 19,716 |
| Lines of docs | 1,800 |
| Commits, lifetime | 60 (Mar 2026 to Nov 2026) |
| Disk used by runtime stages plus package cache | 342 MB |
| Context cost of published skill names and descriptions, every session | ~8,200 tokens |

Two ratios tell the story. Infrastructure code is 1.3 times the size of the skill content it ships. And about half of the 60 commits are about the machinery (runtime, maintenance, automation hardening, security), not about skills.

### Where the Python goes

| Lane | Scripts | Lines | Runs on this machine? |
| --- | --- | ---: | --- |
| Bookmark curation, design intelligence, candidate evaluation, weekly campaign | 20 | ~14,100 | No. Needs GBrain, Field Theory, Hermes, a Codex automation. None installed. |
| Stack maintenance (upstream audit and prepare) | 3 | ~5,800 | Partly. Driven by a Claude scheduled task created this week; no run yet. |
| Catalog, compile, install, doctor, layout, imports | 13 | ~4,500 | Yes. This is the part that works. |
| Command resolver and run-state ledger | 2 | ~970 | Runnable, unused. Claude Code routes skills itself. |

Roughly 60 percent of the code serves lanes that cannot execute here, and another 23 percent serves a maintenance lane that a 60-line scheduled-task prompt now drives.

---

## 3. Usability critique

I scored this the way the gstack DX rubric scores a developer product, because Stack is one: its developer is Maroun, and its hello world is "a skill I wrote shows up in Claude."

| Dimension | Score | Evidence |
| --- | :---: | --- |
| Getting started | 3/10 | Install is a five-flag command that refuses to run unless clean `HEAD` equals `origin/main` on the canonical remote. The runbook for it lives in an auto-memory file because the README version is buried under governance prose. Zero skills loaded for months after a "successful" install. |
| Adding a skill | 2/10 | Classifier rule, layout migration entry, registry regen, catalog digest bump, counts in two docs, test constant, then PR, then reinstall. Eight touchpoints to add one markdown folder. PR #47 (micro-branch) shows the full cost. |
| Invocation surface | 4/10 | 189 flat names. 12 logical commands (`stack.plan`, `stack.design`...) that no one can type in Claude Code. A 601-line resolver that re-implements the host's skill routing. |
| Findability | 3/10 | Nine motion skills, four code-review skills, four teach skills, four handoff skills, three grill skills. Nothing tells the model or the human which one is canonical. |
| Documentation | 4/10 | 1,800 lines, led by receipts, attestation, lineage, sealed copies. No example of invoking a skill. Setup guide still describes dropping skill folders into a repo, which the compiler forbids. |
| Error and failure reporting | 6/10 | Fail-closed with named blocker codes is good. But the central failure mode (runtime installed, host sees nothing) had no check until yesterday. |
| Upgrade path | 3/10 | See the pin table below. Four months behind on the two providers the factory depends on. |
| Dev environment | 6/10 | Tests green, doctor works, pre-commit scans secrets. CI runs only the security scan; the 505 tests never run in CI. |
| Overall | 4/10 | Works, with friction. The operator tolerates it because he built it. |

### 3.1 Time to hello world

For "I wrote a skill, I want Claude to use it" the honest path today is: edit `scripts/classify-capabilities.py`, add a layout entry, run the registry build, bump the digest in `config/runtime-targets.json`, update counts in `docs/skill-architecture.md` and `README.md`, add the name to a test constant, run 505 tests, open a PR, merge, run the five-flag installer from a clean main checkout, then restart Claude Code. The target should be: drop a folder, run one command.

### 3.2 Routing layers that fight the host

Claude Code already routes from skill descriptions and already enforces permissions. Stack adds on top:

- `registry/commands.json` with 12 logical routes and `registry/routing-rules.json`, read by `skills/core/stack/SKILL.md`, which asks the model to parse JSON to decide which skill to call.
- Trust classes (`read-only`, `local-mutation`, `external-mutation`) that duplicate Claude Code permission modes and are never enforced by anything.
- `scripts/stack-run-state.py`, a SQLite run ledger with leases and fan-out caps, for a shop with one operator, when Claude Code has sessions, worktrees, subagents and scheduled tasks.
- A quota preflight table keyed to Codex rolling quota, in a Claude runtime.

Each layer is coherent on its own. Together they are a second operating system running inside the first one, and the second one is the one that goes stale.

### 3.3 The install that passed while nothing loaded

Memory records that until PR #46 the runtime had no plugin manifest, so Claude Code loaded none of it. Meanwhile 505 tests passed, receipts were written, verifiers ran in disposable copies, attestations matched. This is the single most important usability finding, because it shows what the tests test. There is still no smoke test that asks the host "do you see `stack:micro-branch`?" The post-switch verifier checks that files exist and that `plugin.json` has the right version string. That is necessary, not sufficient.

---

## 4. Content critique: the skills themselves

### 4.1 Collisions and duplicates

The same skill is reachable several ways in one Claude session, with different content behind each name.

| Name | Reachable as | Content diverges? |
| --- | --- | --- |
| deslop | `deslop` (workspace), `stack:deslop`, `stack:cdo-deslop` (deprecated adapter) | Yes |
| simplify | `simplify` (workspace), `stack:simplify`, `stack:cdo-simplify`, `compound-engineering:ce-simplify-code`, Claude built-in `/simplify` | Yes |
| rams, react-doctor | workspace, `stack:`, `stack:cdo-*` | Yes |
| cdo, cpo, departments | workspace, `stack:` | Yes (cdo: 25 differing files) |
| ce-plan, ce-work, ce-brainstorm... | `compound-engineering:*` (desktop plugin), `stack:ce-*` (pinned July copy) | Yes, 595 upstream commits apart |
| qa, retro, canary, land-and-deploy, office-hours | bare gstack (April install), `stack:*` (July pin) | Yes |
| frontend-design | `frontend-design` plugin, `stack:frontend-design` (impeccable) | Different skills, same name |
| tdd | `tdd` (workspace), `stack:tdd`, `stack:matt-tdd` | Yes |

Twenty skills exist as diverged copies in both `~/Claude/skills` and this repo. The workspace's `docs/skill-reference.md` declares the workspace folder "the canonical source of truth" and says the upstream was retired on 2026-06-03. This repo's README says the same of itself. Two sources of truth, both in writing. The workspace `CLAUDE.md` routes "run it through the departments" to the workspace `departments` skill; this repo's `departments` is a deprecated adapter that redirects to `stack.run plan`. Which one fires depends on which description the model reads first.

### 4.2 Overlap clusters the catalog does not declare

The registry declares overlaps on 8 of 158 capabilities. Reading the descriptions, the real clusters are:

| Cluster | Members | Suggested canonical |
| --- | --- | --- |
| Motion | emil-animate, emil-improve-animations, emil-choreograph, emil-animation-vocabulary, emil-animation-performance, emil-find-animation-opportunities, emil-remove-animations, animate (impeccable), review-animations, transitions-dev-motion, fixing-motion-performance | Emil's set, with transitions-dev as a reference pack |
| Code review | matt-code-review, ce-code-review, stack-review, gemini-review, stack-gemini-review, plus Claude's built-in review | ce-code-review |
| Research | matt-research, david-deep-research, david-research-prompt, competitive (studio) | one, probably matt-research |
| Handoff | matt-handoff, david-handoff, orchestration-handoff, ce-handoff (plugin) | ce-handoff |
| Teach | matt-teach, david-teach, teach-impeccable, teach-me (workspace) | one |
| Grill | matt-grill-me, matt-grill-with-docs, matt-grilling, change-engineering:grill-me | matt-grilling |
| Prototype | matt-prototype, emil-prototype, change-design:prototype | depends on target |
| Design system generation | designsystem (studio), ui-ux-pro-max, design-consultation (gstack), change-design-system | ui-ux-pro-max for personal work |
| TDD | tdd, matt-tdd | matt-tdd |
| Simplify / deslop | simplify, cdo-simplify, deslop, cdo-deslop, taste-skill, ce-simplify-code | deslop plus ce-simplify-code |

### 4.3 Imports that fail the repo's own inclusion test

`docs/architecture.md` says a capability belongs only if it "materially improves the design or construction of software." The David collection was imported wholesale, and roughly 20 of its 29 skills are David's personal tooling: `david-cmux`, `david-anti-sleep`, `david-pi-custom-model`, `david-pi-web-search`, `david-setup-help`, `david-youtube-transcript`, `david-google-safe-browsing`, `david-create-readonly-db-role`, `david-push-skill-to-github`, `david-distribute-skill-to-all-agents`, `david-codex-subagent`, `david-level-up`, `david-short`, `david-fable-safe-prompt`, `david-cyber-audit`, `david-agent-self-scheduling`, `david-read-all-adrs`. Keep the eight that are about building software (`deep-research`, `effective-agent-skills`, `research-prompt`, `prompt-me`, `goal-loop`, `folder-specific-claude-and-agents-md`, `brain-to-docs`, `browser-harness`) and drop the rest.

### 4.4 Stale references inside skills

- `skills/design/cdo/SKILL.md` and `instructions/skill-routing.md` route to `layout-strategy/`, `design-system/`, `ux-patterns/` and `typography/` as sub-folders of cdo. They are not there; they live under `skills/imported/studio/design/`. The CDO routing table has been wrong since the July layout migration.
- `skills/design/cdo/SKILL.md.bak` is committed.
- cdo and cpo tell the model to run `/ce:work` and `/lfg`. Compound Engineering's current invocation in this host is `compound-engineering:ce-work`; check whether `lfg` still exists upstream before any skill relies on it.
- 12 Stack-owned skills plus the whole `packages/stack-codex` bundle hardcode `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, Hermes, OpenClaw or Codex automations. `skills/core/stack/SKILL.md`, `skills/orchestration/*`, `skills/review/agent-verification-ladder`, `skills/qa/live-site-health-check` all assume a runtime that is not here.
- `skills/design/design-intelligence/SKILL.md` instructs a weekly scan of Arc bookmarks, Field Theory, GBrain, and an "OpenClaw outage recovery" backfill from April 2026. None of those sources exist on this machine.
- 4 broken relative links (`reclaude`, impeccable `arrange` and `typeset`, `matt-wayfinder`).
- 20 published skills are under 25 lines. Eight are warning adapters; the rest (`orchestration-goal`, `orchestration-handoff`, `orchestration-parallel-goals`, `matt-grill-me`, `david-short`...) are pointers to docs, not skills. A pointer costs the same context as a skill.
- 24 of 166 descriptions are under 60 characters. Claude Code routes on descriptions. Short descriptions mean the skill never fires on its own.

### 4.5 Catalog fields that say nothing

- `validation.status` is `validated` on all 158. The evidence kinds are `reviewed-estate-refactor`, `structural-classification`, `primary-runtime-parity`. Every one is structural. No skill has ever been evaluated on an output.
- `provenance.license` is `unknown` on 142 of 158, while `THIRD_PARTY_NOTICES.md` records MIT for every provider. The manifests were never updated after the notices were written.
- `visibility` is `extended` on 147, `primary` on 3. The compiler publishes all 158 regardless. The tier exists in the data and does nothing.

### 4.6 What is good

- `micro-branch` is the model Stack-owned skill. A real script (`mb.py`), tests, a Change.org-agnostic rule enforced by a test, a security audit of its one dependency (Twombly 0.4.10 with telemetry and self-update disabled), and a quickstart written in plain words. Every Stack-owned skill should look like this.
- The Emil, Impeccable and Matt collections are high quality and worth keeping, pinned and attributed.
- The family taxonomy, roles and the inclusion test are the right bones for a curated library.
- Pinning, provenance and third-party notices are the right instinct and most personal skill repos skip them.
- Atomic install with rollback receipts is overbuilt for one user but it is correct, and it will matter if Stack is ever shared.
- `stack-doctor` as a read-only check, pre-commit secret scanning, and a green suite are good hygiene.
- The weekly `stack-upstream-sync` scheduled task is the right shape for maintenance: a 60-line prompt plus two scripts, draft PRs only.

---

## 5. Upstream drift

| Provider | Pinned | Pin date | Latest upstream | Commits behind |
| --- | --- | --- | --- | ---: |
| compound-engineering | `1a7a4c1e` | 2026-07-14 | `72ef35e5` (2026-11-07) | 595 |
| gstack | `7c9df1c5` | 2026-07-10 | `dd97420b` (2026-11-07) | 733 |
| matt | `391a2701` | 2026-07-10 | `4ae2317d` (2026-10-31) | 263 |
| david | `5c990803` | 2026-07-10 | `c23d9026` (2026-11-06) | not comparable |
| emil | `c8a79627` | 2026-11-04 | same | 0 |
| stewdio | `cd42b37f` | 2026-11-04 | same | 0 |

The two providers that `stack.plan`, `stack.build`, `stack.review`, `stack.qa` and `stack.ship` delegate to are four months and 1,300 commits stale. Meanwhile the live Compound Engineering plugin in the desktop app is current and exposes 16 skills, including `ce-doc-review`, `ce-pov`, `ce-compound` and `ce-handoff`; Stack exports seven, none of those four. There are three gstack copies on this machine: the bare April install in `~/.claude/skills` (0.15.16), the July pin in `~/.stack-packages/gstack` (1.60.1), and upstream. The oldest is the one Claude Code loads bare.

Syncing more often will not fix this. Pinning a fast-moving plugin behind a control plane means the control plane is always the stale thing. Let the host's plugin manager own CE and gstack. Stack should reference them by name, not vendor them.

---

## 6. Prune

Ordered by payoff over effort. Each row is reversible through git.

### 6.1 Delete the intelligence lane

Remove: `scripts/{backfill-bookmark-history,bookmark_private_corpus,build-design-intelligence-packet,collect-bookmark-candidates,evaluate-design-intelligence-candidate,field_theory_freshness,import-bookmark-deltas,materialize-bookmark-candidates,materialize-capability-change,query-design-intelligence,reconcile-bookmark-sources,record-weekly-design-promotion,list-pending-weekly-design-promotions,run-stack-weekly-intelligence,run-stack-weekly-live,triage-bookmark-candidates,weekly_local_adapters,x_bookmark_infrastructure_status}.py`, `scripts/run-stack-bookmark-curation.sh`, `scripts/install-hermes-stack-curation-job.sh`, `scripts/gbrain-pinned-*`, their roughly 15 test files and fixtures, `docs/{bookmark-curation,design-intelligence-loop,weekly-intelligence-operations,weekly-intelligence-readiness,private-overlay}.md`, about ten schemas under `registry/`, `config/{bookmark-*,weekly-*,candidate-evaluation-profiles,private-data-handling}.json`, `references/{bookmark-source-adapters,hermes-curation-deployment}.md`, and the skills `design-intelligence`, `field-theory-bookmark-synthesis`, `fieldbook-source-split`, `hermes-native-patch-migration`.

Why: roughly 14,000 lines serving sources and schedulers that are not installed, documented in a readiness record from August that still lists "branch delivery and the Codex automation update" as the remaining gate. The idea behind it (compound taste into skills) is right; the input (X bookmarks) and the executor (Codex automation) were wrong. Section 8 proposes the replacement.

Saves: about 55 percent of `scripts/`, 30 percent of `tests/`, 55 percent of `docs/`.

### 6.2 Drop the Codex target and the stack-codex package

Remove the `codex` entry from `config/runtime-targets.json`, `packages/stack-codex/` (8 skills, 7 commands, 3 agent TOMLs, all Sol/Terra/Luna), the parity tests, the bundle digest, `.codex-plugin`. Archive on a tag so it can come back the day Codex is actually in use.

Why: no Codex CLI on the machine; the published target is dead weight; parity doubles the compile and verify surface for zero consumers.

### 6.3 Replace the maintenance runner

`scripts/stack-maintenance.py` is 3,998 lines. The scheduled task that drives it is 60 lines and already says what to do. Keep `discover-upstream-updates.py` and `import-pinned-skills.py`, collapse the audit/prepare state machine to a script that: reads pins, compares to upstream heads, opens or refreshes one draft PR with the diff. Target under 400 lines.

### 6.4 Remove the second operating system

Delete `registry/commands.json`, `registry/routing-rules.json`, `scripts/resolve-command.py`, `scripts/stack-run-state.py`, `docs/orchestration-contract.md`, `docs/command-tree.md`, the 12 command adapters, the trust-class fields, and the skills `core/stack`, `core/run`, `orchestration/*` (goal, handoff, parallel-goals, goal-validation-threads), `review/agent-verification-ladder`, `review/scratch-eval-promotion-gate`, and all 8 compatibility adapters (`agent-operating-stack`, `departments`, `ideate`, `mega-workflow`, `cdo-deslop`, `cdo-rams`, `cdo-react-doctor`, `taste-skill-suite-taste-skill`). One operator does not need warning wrappers for his own old command names.

Replace with one `stack:factory` skill (section 8) whose description does the routing, which is how Claude Code routes anyway.

### 6.5 Cut the estate to what gets used

| Action | Count | Names |
| --- | ---: | --- |
| Drop David personal tooling | 21 | listed in 4.3 |
| Collapse motion cluster | 5 | review-animations, animate (impeccable, keep as alt only if used), fixing-motion-performance, emil-remove-animations, emil-find-animation-opportunities |
| Drop duplicate review/teach/grill/handoff | 7 | matt-code-review, gemini-review, david-teach, teach-impeccable, matt-grill-me, matt-grill-with-docs, david-handoff |
| Demote reference packs to references loaded by cdo, not skills | 4 | userinterface-wiki (154 rule files), muller-brockmann-grid-systems, ui-design-brain, high-end-visual-design |
| Drop the studio product set already covered by cpo and CE | 6 | braindump, prd, rice, roadmap, commercialization, menu |
| Drop platform and delivery oddities | 3 | local-tracker-dashboard, reclaude (broken link, workspace has its own), stack-refresh-pr-mode (fold into README) |

Published count goes from 189 to roughly 65. Session context cost drops from about 8,200 tokens to about 2,800. Findability goes up because each cluster has one name.

### 6.6 One source of truth with the workspace

Delete the 20 diverged copies from `~/Claude/skills` (cdo, cpo, departments, deslop, rams, react-doctor, simplify, tdd, knip, better-icons, emil-design-eng, fix-sentry-issues, impeccable, make-interfaces-feel-better, reclaude, studio, taste-skill-suite, ui-design-brain, ui-skills, userinterface-wiki) and point the workspace `CLAUDE.md` and `docs/skill-reference.md` at `stack:` names. The workspace keeps the personal-ops skills that fail Stack's inclusion test (daily-review, career-log, triage, pre-leave-sweep and so on), which is exactly the split the architecture doc already describes.

### 6.7 Small fixes, do them now

- Fix the cdo routing table paths; delete `SKILL.md.bak`.
- Replace `/ce:work` and `/lfg` with `compound-engineering:ce-work` in cpo, cdo and departments.
- Set `provenance.license` from `THIRD_PARTY_NOTICES.md`.
- Add a GitHub Actions job that runs `python3 -m unittest discover -s tests`. Today only the secret scan runs in CI.
- Add a real post-install smoke test: launch `claude plugin list` (or `claude --print` with a skill invocation) and assert the plugin and one skill are visible. The absence of this check is why nothing loaded for months.
- Rewrite the 24 short descriptions with trigger phrases, the way `micro-branch` does it.
- Make `visibility` drive publication: `primary` and `extended` publish, `reference-only` does not.

---

## 7. Uplevel

These are worth doing regardless of the factory question.

1. **One-command add.** `python3 scripts/stack.py add skills/design/foo` should classify from frontmatter, write the layout entry, regenerate the registry, bump the digest, and update the counts. The eight touchpoints in 3.1 are all derivable from the folder.
2. **One-command install from the checkout.** `python3 scripts/stack.py install` that fetches, verifies clean main, compiles, switches, and runs the host smoke test. Keep the current flags as the explicit long form.
3. **Behavioral evals per skill.** `skills/<name>/eval/` with one to three fixtures and a judge prompt; cpo and cdo already have `eval/checklist.md` and `advisory-board.md`. Run them with a Claude scheduled task and record pass/fail into the manifest's `validation.evidence`. That turns `validated` from a label into a fact. The spotter skill in the Change.org design plugin is a working example of the shape.
4. **Usage signal.** The reassessment template asks for a low-usage signal and nothing produces one. A Claude Code hook on the Skill tool appending `{skill, ts, cwd}` to `~/.local/state/stack/usage.jsonl` gives it a source. Monthly, the sync task reports the zero-use list.
5. **Descriptions as the routing layer.** Invest the effort that went into `routing-rules.json` into descriptions with trigger phrases and anti-triggers ("not for X, use Y"). Claude Code reads those on every turn; it never reads the JSON.
6. **Let the host own CE and gstack.** Remove them from `packages/`. Keep a `references/upstreams.md` that names the plugin and the skills Stack calls, and a test that asserts the plugin is installed. Four months of drift disappears.
7. **README rewrite.** Lead with: what Stack is in two sentences, the five skills you will use most and how to say them, how to add a skill, how to install. Move receipts, attestation and lineage to `docs/runtime-publication.md` where they belong.

---

## 8. Should Stack power a software factory?

Yes, and it already wants to. `stack.run full` describes plan → build → verify → ship with gates. cpo → cdo → build is a real production spine. The orchestration contract has stages, children, gates, approvals and receipts. The vocabulary is right. What is missing is the line itself and a feedback loop from real output.

### 8.1 What a factory needs that Stack does not have

| Factory part | Today | Gap |
| --- | --- | --- |
| Intake | cpo turns a brain dump into a plan file | Works. Plan format is CE's; good. |
| Design stage | cdo appends a design spec to the plan | Routing table broken; references sub-skills that moved. |
| Build stage | delegates to pinned ce-work | Pin is 595 commits stale; live plugin is newer. |
| Review and QA gates | delegates to ce-code-review and gstack qa | Same staleness. No per-project definition of done beyond prose. |
| Ship | gstack ship or land-and-deploy | Fine. |
| Project ledger | SQLite in `~/.local/state` | Wrong place. Artifacts already live in `docs/plans` and `docs/solutions` in the project; the ledger should be git. |
| Scaffold | none in Stack | `change-utilities:begin` does this for the workspace. Factory needs a project template with `CLAUDE.md`, `docs/plans`, `docs/solutions`, eval hooks. |
| Metrics | none | Cycle time per stage, review findings per build, rework count. Without these the "factory" cannot say whether it is getting better. |
| Learning loop | design-intelligence from X bookmarks | Wrong input. The loop that compounds is retro of the build → `ce-compound` writes the learning → proposed skill patch → eval → merge. gstack `retro` and CE `ce-compound` already exist. |
| Parallelism | run-state fan-out, Codex roles | Claude Code sessions, worktrees and subagents are the native primitives now; `micro-branch` already uses worktrees correctly. |

### 8.2 Three options

**A. Curated library.** Do sections 6 and 7, stop there. Stack becomes what it is in practice: a pinned, attributed, tested skill library for design and build work, published into Claude Code. Low risk, high relief, cuts the repo by more than half.

**B. Library plus a thin factory line.** A, then add one skill, `stack:factory`, that defines the pipeline as data (stages, the skill each stage calls by its host name, the artifact each stage writes into the project, the gate checklist each stage must pass) and runs it with Claude Code sessions and worktrees. Project ledger is the git history of `docs/plans` and `docs/solutions`. Every run ends with retro → `ce-compound` → a proposed diff to a Stack skill, evaluated by the skill's eval fixtures before merge. This is the honest version of design intelligence: learn from your own builds. Medium effort. This is the recommendation.

**C. Revive the control plane.** Install Codex and Hermes, update pins, reactivate the weekly campaign, keep parity. Not recommended. It optimizes for a runtime that is not in use, and every quarter of drift makes it heavier.

### 8.3 Suggested order for B

1. Week 1: section 6.7 fixes, delete the intelligence lane and Codex target (6.1, 6.2), add the CI test job and the host smoke test. Reinstall. Verify `stack:` skills fire.
2. Week 2: estate cut (6.5), workspace dedupe (6.6), description rewrites. Reinstall.
3. Week 3: `stack.py add` and `stack.py install` (7.1, 7.2). Move CE and gstack to host-owned (7.6). Delete the resolver, run-state and compatibility adapters (6.4).
4. Week 4: `stack:factory` v1 on one personal project, end to end, with the retro → compound step writing one real learning. Measure cycle time by stage.
5. Then: evals per skill (7.3), usage hook (7.4), README rewrite (7.7).

Dogfood rule: use the factory to build each of its own later steps.

---

## 9. Risks of pruning, and why they are acceptable

- **Losing the intelligence work.** It is in git history and can be tagged. The concept returns in 8.2 B with a better input.
- **Losing Codex parity.** Nothing consumes it today. Re-adding a target later is a config entry plus compile; the compiler already supports multiple targets.
- **Breaking the departments trigger in the workspace.** The workspace `CLAUDE.md` must be updated in the same change as 6.6. One PR in each repo, same day.
- **Test count drops.** From 505 to roughly 300. The remaining tests cover the parts that run.

---

## 10. Checks run for this review

- Full suite: `python3 -m unittest discover -s tests` → 505 tests, OK, 71 seconds.
- `python3 scripts/stack-doctor.py` → status ok, 150 active, 13 commands, 11 families, 7 providers, clean source at `245e598`.
- Installed runtime manifest at `~/.claude/skills/stack/runtime-manifest.json`: 158 included, 0 excluded, 12 command adapters, 20 aliases, validation passed.
- Upstream drift via the GitHub API, 2026-11-06.
- Workspace diff: 20 skills present in both `~/Claude/skills` and this repo, all diverged.
- Host check: `codex`, `hermes`, `gbrain`, `field-theory` not on PATH; no weekly-intelligence checkout; `bun` present.
- `claude plugin list` shows the change-ai-skills, figma and frontend-design plugins; Stack loads as `stack@skills-dir`.
