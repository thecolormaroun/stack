---
name: micro-branch
description: >-
  Iterate on a UI without losing versions. Each attempt ("take") lives on its own
  git branch and worktree, every take is laid out side by side on a local board,
  and the person can jump back to any take or pick one into trunk. Use when someone says "try a few versions", "give me three takes",
  "micro-branch this", "put the versions on a canvas", "go back to take 2", "build
  on take 3", "pick that one", or wants design iterations that never overwrite
  each other. Works in any git repo with a static build or plain HTML, and has a
  Design Studio preset that opens each frame on one prototype view.
---

# micro-branch

Design is not linear. People try several answers to one question, go back, and
build on an earlier attempt. This skill keeps every attempt as its own branch so
nothing gets replaced, and puts the attempts side by side so the person can
compare them and point at one.

## Words

| Word | Meaning | Label |
|---|---|---|
| Trunk | The picked state on the main branch | `main` |
| Round | One design question, with 2 to 4 takes from the same starting commit | `r1-view-all` |
| Take | One answer to the round's question, on branch `mb/<round>/<take>` with its own worktree | `R1 · T2 inline expand` |
| Pick | The person chooses a take; it is squash-merged into trunk and the round's takes become `mb-archive/...` tags | |

Talk to the person in plain words: "attempt", "version 2", the label `R1 · T2 ...`.
Never ask them to run git.

## The script

Everything deterministic runs through `scripts/mb.py` in this skill's directory.
Resolve the directory once and keep the command handy:

```sh
MB="python3 <this skill's directory>/scripts/mb.py"
```

Run it from anywhere inside the project's main checkout. Every command prints JSON
with `"ok": true`, or `"ok": false` plus `error` and `hint`. Read the hint before
retrying. State, snapshots and the board live in `<git-common-dir>/micro-branch/`
and never leave the machine.

## First use in a repo

1. Check the repo: `git status` is clean and trunk has at least one commit. If the
   folder is not a repo, ask before running `git init`.
2. Work out how a take becomes static files. Read `references/setup-recipes.md`
   for Vite, Next.js, Astro, plain HTML and other stacks. A folder with
   `studio.config.json` is a Design Studio install: use `init --preset design-studio`
   and read `references/design-studio.md`.
3. Initialise. Defaults: frame `1280x800`, at most 4 takes per round.

```sh
$MB init --name "<project name>" --build "<build command>" --out <output dir> \
  --setup "<install command, only if each take needs dependencies>" \
  [--frame-size 390x844]
```

Use `--frame-size 390x844` for mobile screens. The board needs only Python. To keep
frames working offline, `--localize-fonts` and `--localize <host>` copy remote fonts
and images into each frame.

## The loop

1. **Start a round** for one question the person cares about:
   `$MB round new <slug> --question "How should view-all open?"`.
   Add `--entry "index.html?variant=b"` when the round's frames open somewhere other
   than the repo's entry, or `--view <prototype>/<path>` in Design Studio
   (`$MB views` lists them).
2. **Cut takes**, one idea each, usually 3:
   `$MB take new r1 <slug> --note "one line on the idea"`.
   Edit only inside the `worktree` path it returns. Never edit trunk during a round.
   Subagents can work in parallel, one take worktree each.
3. **Publish each take**: `$MB publish r1/t2`. It commits the take, runs the build,
   snapshots the output and lays it out on the local board, starting the board if
   it isn't running. A failed build publishes nothing and marks the take `broken`;
   read the log path in the hint and fix it. `prepared` in the reply lists assets
   the snapshot copied. Mention any under `skipped`.
4. **Show the board**: the reply's `board` is its URL (`$MB canvas` prints it too).
   Open it in the built-in browser if there is one, or give the person the link.
   Tell them which label is which idea, one line each.
5. **Get feedback in chat**: the board has no comments. Ask which takes work and
   what to change, by label (`R1 · T2 ...`); `status` maps labels to takes.
   Summarise per take and propose the next takes. Build only after the person agrees.
6. **Iterate without overwriting**:
   - Refine one take into a new one: `$MB take new r1 <slug> --from t2`.
   - Start the next question from a take without merging it:
     `$MB round next r1/t2 <slug> --question "..."`.
   - Fix a take in place only when the person asks for that take to change
     ("fix the spacing on 2"): edit its worktree, then publish it again.
7. **Jump back**: `$MB open r1/t1` prints the take's worktree, and restores it from
   its archive tag if the round is closed. Run the project's dev server there to try
   it live.
8. **Pick** only when the person chooses: `$MB pick r1/t2`. Trunk must be checked out
   and clean. If the take no longer merges cleanly, merge trunk into the take's
   worktree, resolve, publish, and pick again. To end a round without a winner:
   `$MB round close r1`.
9. **Check state** any time: `$MB status`.

## Rules

- Never push branches or tags, and never open pull requests from this skill.
- The board stays on 127.0.0.1. Never expose it (no tunnels, no other interfaces) and
  never upload frames anywhere.
- Never delete `mb/*` branches, `mb-archive/*` tags or take worktrees by hand. `pick`
  and `round close` tag first, check the tag, then clean up.
- Never `git reset --hard` or force-checkout in trunk or a take.
- Keep to the take limit. More than 4 ideas means the question is too broad: split it
  into two rounds.

## References

- `references/setup-recipes.md`: build, output and setup values per stack, and what
  to do when a project has no static build.
- `references/design-studio.md`: the Design Studio preset, picking a view, and
  copying remote assets into its frames.
- `references/troubleshooting.md`: common errors and their fixes.
