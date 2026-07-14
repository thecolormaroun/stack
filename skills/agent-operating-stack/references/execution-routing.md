# Agent Execution Routing

This is Stack's durable composition policy. It controls how local workflows use
external skills and agents; it does not modify vendored or upstream skill files.

## Model roles

| Role | Model | Reasoning | Use |
| --- | --- | --- | --- |
| Orchestrator | `gpt-5.6-sol` | high | Decomposition, architecture, conflict resolution, final synthesis |
| Worker | `gpt-5.6-terra` | medium | Implementation, tests, general engineering |
| Reviewer | `gpt-5.6-terra` | high | Correctness, security, contracts, regression risk |
| Explorer | `gpt-5.6-luna` | medium | Repository mapping, extraction, summaries, bounded research |

Use Sol explicitly at the root. Executors must be pinned to Terra or Luna and
must not inherit Sol or `xhigh` reasoning from the parent.

For Hermes, the interactive Mookie root may remain on Sol/high when the user
values the quality. That does not make Sol the right default for subagents,
cron, compression, extraction, or catalog work.

## Quota preflight

If `~/Codex/scripts/codex-quota-preflight.sh` exists, run it before
any multi-agent or multi-reviewer wave. Otherwise fail closed to one Terra/Luna
executor until the live quota is known.

| Rolling quota used | Mode | Maximum executors |
| ---: | --- | ---: |
| below 50% | normal | 3 |
| 50-69% | constrained | 2 |
| 70-84% | single | 1 |
| 85% or higher | pause | 0 |
| unknown | single | 1 |

Pause mode permits deterministic local work but no new model executors unless
the user explicitly overrides the quota gate.

## Dispatch limits

- Maximum three open agent threads and nesting depth one.
- Children never spawn children.
- Use no inherited conversation for self-contained packets. If recent context
  is genuinely required, pass at most the latest three turns; never clone the
  entire parent conversation.
- Give every executor a bounded goal, paths, boundaries, deliverable, and
  verification command.
- Allow one follow-up per executor, then close it or start a fresh narrower
  packet.
- Run one review wave. A second wave requires a validated P0/P1 finding or an
  explicit request for deep review.

## External workflow composition

Keep `ce-work`, `ce-simplify-code`, `ce-code-review`, and other external skills
unchanged. Stack owns their composition:

- Run trivial or small implementation inline.
- Use Terra workers only for independent bounded implementation units.
- Run simplification once at a meaningful phase boundary. In constrained or
  single mode, combine reuse, quality, and efficiency into one inline pass.
- Default code review to one targeted Terra/high reviewer selected by actual
  risk. Add a second reviewer only for a distinct high-risk surface.
- Use a full multi-reviewer workflow only in normal mode for explicit deep
  review or high-risk authentication, payments, destructive data changes,
  public contracts, concurrency, or verification machinery.
- Validate strong P0/P1 findings independently; do not launch a validator for
  every weak P2/P3 observation.
- Do not automatically stack implementation fan-out, simplification reviewers,
  a full review roster, and per-finding validators.

## Hermes context hygiene

Sol quality can stay at the user-facing root while token amplification is
controlled separately:

- Start a new session when the subject changes materially instead of growing a
  single Telegram thread indefinitely.
- Inspect `/usage` during long sessions and use `/compress` before repeated
  large-context calls dominate usage.
- Prefer the normal compression threshold over an 85% Codex-family autoraise
  when quota conservation matters.
- Keep compression, extraction, cron, and delegated support work on Luna or
  Terra.

## Closeout gate

Before claiming an orchestrated workflow complete, verify the role/model used
by each child, peak executor count, nesting depth, review-wave count, focused
tests or artifacts, and the post-run quota state.
