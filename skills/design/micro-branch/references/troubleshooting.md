# Troubleshooting

Every failure prints `"ok": false` with `error` and `hint`. Match the error here.

| Error | Fix |
|---|---|
| `not inside a git work tree` | `cd` into the project. If it has no repo, ask the person before `git init` and a first commit |
| `trunk '<name>' has no commits yet` | Commit the current files, then `init` again |
| `micro-branch is not set up in this repo` | Run `init` (see `setup-recipes.md`) |
| `already has N takes (limit N)` | Ask the person to pick, or start the next round from the strongest take. Raise the limit with `init --max-takes` only if they ask |
| `round ... is picked` / `closed` | Start a new round, or `round next <take>` to build on one of its takes |
| `build failed ... nothing was published` | Read the log path in `hint`. Run the build by hand in the take's worktree, fix, publish again |
| `build output '<dir>' does not exist` | The build wrote somewhere else. `init --out <dir>` |
| `'index.html' is missing from the build output` | `init --entry <file>`, or per round with `round new --entry` |
| `--view needs the design-studio preset` | Use `--entry` outside Design Studio. In a Design Studio folder, `init --preset design-studio` |
| `no view matches ...` / `matches N views` | `views` lists every view as `<prototype>/<path>`; use that form. At publish, archived prototypes are missing from the build |
| `this repo has no studio.config.json` | The preset only fits a Design Studio checkout. Run init there, or drop `--preset` |
| `Design Studio's dependencies are not installed` | Run `pnpm install` in the main checkout once |
| `not a host name` | `--localize` takes bare hosts, comma-separated: `images.example.com,cdn.example.com` |
| `setup failed in <worktree>` | Run the setup command by hand there. The worktree stays, so publish after fixing |
| `trunk checkout ... has uncommitted changes` | Ask the person whether to commit or stash their trunk changes. Never discard them |
| `does not merge cleanly into <trunk>` | Trunk moved since the round started. In the take's worktree: `git merge <trunk>`, resolve, `publish`, then `pick` again. Trunk was left unchanged |
| `has no changes against <trunk>` | The take is identical to trunk; nothing to pick |
| `unrecognized arguments: --canvas ...` | The board is the only canvas now; drop the flag |
| `no single take matches` | Use the full id from `status`, e.g. `r2-type/t3-serif` |
| Board frame is blank or assets 404 | The build uses root paths. Make them relative (`setup-recipes.md`) or `init --root-paths` |
| `prepared.localized.skipped` is not empty | Those assets failed to download and the frame still points at the network. Check the host and that the person is online; the cache keeps what did download |
| A take's commit contains a `node_modules` link | Made before the exclude fix. Remove it in the take with `git rm --cached node_modules`, then publish |
| A take's folder was deleted by hand | `open <take>` recreates it from the branch or the archive tag |
| The board shows an old version of a take | `publish` the take again; the snapshot is replaced |

## Inspecting state

- `status` shows every round, take, branch, worktree and frame.
- State file: `<git-common-dir>/micro-branch/state.json`. Build logs:
  `<git-common-dir>/micro-branch/logs/`. Snapshots: `.../frames/`. Board:
  `.../board/index.html`.
- Archived takes: `git tag --list 'mb-archive/*'`.
