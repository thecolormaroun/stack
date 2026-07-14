# Stack

Skills, workflows, and a design knowledge graph for Claude Code. One command takes an idea from brain dump to shipped PR.

## Quick Start

```bash
# Clone into your Claude Code config
git clone https://github.com/thecolormaroun/claude-code-stack.git ~/.claude/stack

# Link skills to your global config
echo 'skills.load.extraDirs: ["~/.claude/stack/skills"]' >> ~/.claude/settings.json

# Install compound-engineering (powers /lfg)
claude plugins install compound-engineering@every-marketplace

# Install illo (editorial illustration skill/plugin)
claude plugin marketplace add tmchow/illo-skill
claude plugin install illo@illo-skill
```

Or copy individual skills into any project's `skills/` directory.

---

## Commands

### `/mega` — The Full Pipeline

One command runs everything. Drop a brain dump and `/mega` handles product, design, build, review, security, QA, and shipping.

```
/mega [your idea here]
```

```
Brain Dump → CPO (Product) → CDO (Design) → /lfg (Build) → /review → /cso → /qa → /ship
```

| Phase | What happens | Output |
|-------|-------------|--------|
| **CPO** | Extracts requirements, RICE scores, sizes the work | Plan file in `docs/plans/` |
| **CDO** | Adds visual direction, component specs, interaction patterns | Design spec appended to plan |
| **/lfg** | Builds it (compound-engineering) | Working code |
| **/review** | Staff engineer code review + auto-fixes | Clean code |
| **/cso** | OWASP + STRIDE security audit | Security fixes |
| **/qa** | Real browser testing, finds and fixes bugs | Verified features |
| **/ship** | Sync, test, push, PR | Shipped PR |

### Pipeline Variants

| Command | What it runs |
|---------|-------------|
| `/mega [idea]` | Full pipeline: product → design → build → verify → ship |
| `/mega:spec [idea]` | CPO + CDO only — just the plan and design spec |
| `/mega:build [plan]` | CDO → /lfg → verify — design through build |
| `/mega:verify [branch]` | /review → /cso → /qa → /ship — verification suite only |
| `/mega:qa [url]` | Just the gstack verification suite |

### `/ideate` — Idea Validation

Flesh out an idea before committing to build it.

```
/ideate [your idea]
```

Runs:
- `/office-hours` — YC-style forcing questions, pushback on weak ideas
- `/plan-ceo-review` — Scope expansion, strategic fit, risk assessment
- `/plan-design-review` — Visual feasibility, component audit (0–10 per dimension)
- `/plan-eng-review` — Architecture diagrams, test strategy, complexity estimate

### Other Entry Points

| Command | What it does |
|---------|-------------|
| `/ship [idea]` | Same as `/mega` (alias) |
| `"run it through the departments"` | Same as `/mega` |
| `"departments: plan only"` | CPO only — just the plan file |
| `"departments: design [plan]"` | CDO only — add design spec to existing plan |
| `"departments: ship [plan]"` | Skip to /lfg — build from existing plan |

---

## Skills Reference

### Pipeline Skills

| Skill | Emoji | What it does |
|-------|-------|-------------|
| `mega-workflow/` | 🚀 | Full pipeline orchestrator — product → design → build → verify → ship |
| `ideate/` | 💡 | Idea validation suite — YC pushback, scope review, design + eng feasibility |
| `departments/` | 🏢 | Simpler pipeline — CPO → CDO → /lfg |
| `cpo/` | 🎯 | Chief Product Officer — brain dumps → structured plan files with RICE scoring |
| `cdo/` | 🎨 | Chief Design Officer — enriches plans with design specs |

### CDO Sub-Skills

The CDO skill includes specialized modules that activate automatically during the design phase:

| Sub-skill | What it does |
|-----------|-------------|
| `cdo/visual-direction/` | Color palettes, mood, aesthetic foundation, brand expression |
| `cdo/ui-ux-pro-max/` | 67 styles, 96 palettes, 57 font pairings, 25 chart types, 13 tech stacks |
| `cdo/taste-skill/` | Anti-LLM-bias rules — overrides default AI aesthetics with metric-based design |
| `cdo/favicon/` | Generate full favicon sets from a source image |
| `cdo/deslop/` | Design-aware slop removal |
| `cdo/simplify/` | Design-aware code simplification |
| `cdo/rams/` | Design-aware accessibility review |
| `cdo/react-doctor/` | Design-aware React audit |

### Design Quality Skills

Community skills for UI craft. Claude consults these automatically during UI work.

| Skill | What it does | Source |
|-------|-------------|--------|
| `emil-design-eng/` | Animation craft — easing curves, spring physics, polish | [emilkowalski/skill](https://github.com/emilkowalski/skill) |
| `review-animations/` | Hard-nosed motion review — flags easing, duration, origin, interruptibility, performance, and a11y | [emilkowalski/skill](https://github.com/emilkowalski/skill) |
| `make-interfaces-feel-better/` | 16 UI detail principles (optical alignment, shadows, stagger, hit areas) | [jakubkrehel](https://github.com/jakubkrehel/make-interfaces-feel-better) |
| `taste-skill-suite/` | Anti-LLM-bias, typography calibration, color correction, layout diversification | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) |
| `impeccable/` | 17 design commands — dark mode mastery, polish, audit | [impeccable.style](https://impeccable.style) |
| `ui-skills/` | Baseline UI accessibility, motion performance, 12 principles of animation | [ui-skills.com](https://www.ui-skills.com) |
| `ui-design-brain/` | 60+ component patterns across 5 design styles | [carmahhawwari/ui-design-brain](https://github.com/carmahhawwari/ui-design-brain) |
| `userinterface-wiki/` | 152 rules across 12 categories — animations, CSS, typography, UX patterns | [raphael-salaja](https://github.com/raphael-salaja) |
| `better-icons/` | 200k+ icons via MCP | [better-auth/better-icons](https://github.com/better-auth/better-icons) |
| `illo/` | Editorial illustrations with a recurring mascot, print-style looks, and Codex/OpenRouter backends | [tmchow/illo-skill](https://github.com/tmchow/illo-skill) |

### Code Quality Skills

Run these after writing code to clean up before shipping.

| Skill | What it does |
|-------|-------------|
| `deslop/` | Remove AI slop — unnecessary comments, defensive checks, inconsistent style |
| `simplify/` | Refine code for clarity without changing behavior |
| `rams/` | Accessibility (WCAG 2.1 AA) + visual design review (Dieter Rams principles) |
| `react-doctor/` | React health audit — security, performance, architecture (0–100 score) |
| `knip/` | Find and remove dead code, unused files, unused exports |
| `tdd/` | Test-driven development — red/green/refactor loop |
| `fix-sentry-issues/` | Discover, triage, and fix production errors from Sentry |
| `reclaude/` | Refactor bloated CLAUDE.md files using progressive disclosure |
| `gemini-review/` | Read-only Google AI / Antigravity second-model review over a git diff |

---

## Studio Skill Graph

A structured knowledge graph (90+ files) that Claude navigates during product, design, and build work. You don't invoke it directly — it's reference material that other skills pull from.

| Domain | What's in it |
|--------|-------------|
| **Design System** | Tokens, color system, motion tokens, buttons, cards, inputs, spacing, typography |
| **Design Patterns** | Premium interaction patterns, motion design, "design with taste" guardrails |
| **Design Heuristics** | Error prevention, irreversible actions, trust signals |
| **Design Checklists** | Visual QA checklist, UI critique framework |
| **Layout** | Grid system, responsive rules, spacing scale, touch targets, visual hierarchy |
| **Research** | Competitive teardowns, gap analysis, landscape discovery, taste mining |
| **Product** | PRD generation, product specs, feature prioritization |
| **Ship** | Build handoff, QA, release workflow |

Entry point: `skills/studio/_graph/studio.moc.md`

---

## Directory Structure

```
├── config/
│   └── CLAUDE.md              # Global config (Studio graph refs, plan settings)
├── plugins/
│   └── compound-engineering/  # Plugin config
├── skills/
│   ├── mega-workflow/         # 🚀 Full pipeline orchestrator
│   ├── ideate/                # 💡 Idea validation suite
│   ├── departments/           # 🏢 Simpler pipeline
│   ├── cpo/                   # 🎯 Product — brain dump → plan file
│   ├── cdo/                   # 🎨 Design — plan file → design spec
│   │   ├── visual-direction/
│   │   ├── ui-ux-pro-max/
│   │   ├── taste-skill/
│   │   ├── favicon/
│   │   ├── deslop/
│   │   ├── simplify/
│   │   ├── rams/
│   │   └── react-doctor/
│   ├── studio/                # Studio Skill Graph (90+ files)
│   │   └── _graph/
│   ├── emil-design-eng/
│   ├── review-animations/
│   ├── make-interfaces-feel-better/
│   ├── taste-skill-suite/
│   ├── impeccable/
│   ├── ui-skills/
│   ├── ui-design-brain/
│   ├── userinterface-wiki/
│   ├── better-icons/
│   ├── illo/
│   ├── deslop/
│   ├── simplify/
│   ├── rams/
│   ├── react-doctor/
│   ├── knip/
│   ├── tdd/
│   ├── fix-sentry-issues/
│   ├── reclaude/
│   └── gemini-review/
└── docs/
    └── setup-guide.md
```

---

## Requirements

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)
- [compound-engineering plugin](https://github.com/EveryInc/compound-engineering-plugin) — powers `/lfg`
- [illo plugin](https://github.com/tmchow/illo-skill) — powers editorial illustration generation

```bash
claude plugins install compound-engineering@every-marketplace
claude plugin marketplace add tmchow/illo-skill
claude plugin install illo@illo-skill
```

## Security Guardrails

Pull requests run a `Security scan` workflow before merge. The workflow combines
Gitleaks with a stack-specific sensitive content scanner for local paths, private
agent artifacts, credential-looking config values, and household or finance-lane
references. See `docs/security/leak-prevention.md` for local hook setup and leak
remediation guidance.

---

## Philosophy

**Boil the Lake** — When AI makes the marginal cost of review near-zero, do complete reviews instead of sampling. Run the full pipeline. Check everything. Ship with confidence.

---

## License

Skills are provided as-is. External skills (linked above) maintain their original licenses.
