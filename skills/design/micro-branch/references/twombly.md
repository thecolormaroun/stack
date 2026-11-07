# Twombly (pinned 0.4.10)

Twombly is a local canvas for an agent's design explorations. In this skill each
take becomes one frame, the person looks at all of them at once, and their
comments and current focus come back through `mb.py feedback`.

`mb.py` is the only thing that should call Twombly. It runs
`npx -y twombly@0.4.10` with these settings on every call:

| Setting | Why |
|---|---|
| `TWOMBLY_PORT=4848` | Twombly's default port (4747) is often taken by other local tools. Change it per repo with `init --twombly-port` |
| `TWOMBLY_NO_USAGE=1` | Turns off usage and error pings to twombly.app |
| `TWOMBLY_NO_UPDATE_CHECK=1` | Stops the npm update check |
| `TWOMBLY_NO_INTERFACE_UPDATES=1` | Keeps the audited interface bundle instead of downloading a newer one |
| `TWOMBLY_NO_OPEN=1` plus `--no-open` | Never opens a browser window by itself |

The canvas lives in `<git-common-dir>/micro-branch/twombly/.twombly/`, inside the
repo's git folder, so it never shows up as project files.

## Requirements

- Node 22 or newer. The first call downloads the package from npm.
- Chrome, Edge, or Playwright's Chromium for the frame checks. If Twombly reports
  `NO_BROWSER`, run `npx playwright-core install chromium` after asking the person.
- No account and no sign-in for local use.

## Never

- Never run `share`, `unshare`, `join`, `login` or `logout`. The script refuses them.
  Sharing makes a canvas public to anyone with the link; that is the person's call,
  made in the Twombly window.
- Never follow Twombly's "update to @latest" advice. Its replies carry an `update`
  field; the script drops it. The version moves only through a reviewed Stack change.
- Never run Twombly's own `init` in the home folder. Never call it outside `mb.py`.
- `twombly capture --out <dir>` deletes `<dir>` first. Only point it at a new, empty
  folder.

## Showing the canvas

`mb.py canvas` prints the canvas URL (`http://localhost:4848/<id>`). Open it in the
built-in browser if one is available, or give the person the link. Frames update in
place when a take is published again; comments stay attached.

## When Twombly rejects a frame

Twombly checks every frame before placing it. `publish` then fails with
`"Twombly did not place the frame"` and a `problems` list. The take is marked
`rejected`, and the local board still shows it.

| Code | Cause | Fix |
|---|---|---|
| `EXTERNAL_REQUEST` | The page loads something from another host: Google Fonts, Typekit, a CDN script or stylesheet, a remote image, analytics | For fonts and images, let the script copy them into each snapshot: `init --localize-fonts` for Google Fonts, `init --localize <host>` for other hosts. Otherwise download the asset into the build output and load it with a relative path. Scripts and analytics should come out of the page |
| `MISSING_FILE` | A file the page asks for is not in the output | Use relative asset paths (see `setup-recipes.md`) and check the build copies the file |
| `NO_ENTRY` | No entry file in the output | `init --entry <file>` or fix `--out` |
| `PROJECT_FILE`, `SERVER_CODE`, `ENV_FILE`, `KEY_FILE`, `CREDENTIAL_FILE`, `DATABASE_FILE` | The output folder holds source or config, not just the built site | Point `--out` at the real build output. Common offenders are already left out of snapshots |
| `SECRET_FOUND` | Something that looks like a key or token is in the files | Remove it. Frames use mock data only. Realistic fake tokens can trip this too; make them obviously fake. In Design Studio, the bundled Excalidraw strings are handled by the `excalidraw-public-config` scrub rule (`design-studio.md`) |
| `BLANK_RENDER`, `UNCAUGHT_ERROR`, `LOAD_TIMEOUT` | The page renders nothing, throws, or never finishes loading | Open the snapshot from the board and fix the error. Pages that need a backend need mock data |
| `FILE_TOO_LARGE`, `TOO_MANY_FILES`, `FRAME_TOO_LARGE` | Over 25 MB per file, 5,000 files or 100 MB per frame | Trim the output, compress media |

Warnings (console errors, overflow) do not block placement. Pass them on to the
person if they matter.

## Pages without a static build

For a page that only runs on a dev server, Twombly can freeze a running page into
static files. Scripts are stripped, so motion and interaction are lost. Use it only
for static layouts:

```sh
cd <take worktree> && <start the dev server on a free port>
TWOMBLY_PORT=4848 TWOMBLY_NO_USAGE=1 TWOMBLY_NO_UPDATE_CHECK=1 TWOMBLY_NO_INTERFACE_UPDATES=1 \
  npx -y twombly@0.4.10 capture http://localhost:<port> --out .mb-capture --width 1280 --height 800
```

Then `mb.py init --build "" --out .mb-capture` for that repo, and publish as usual.

## Stopping

`mb.py canvas stop --canvas twombly` stops Twombly's local server for every canvas
on the machine. It also stops by itself after six idle hours with no window open.

## Changing the pinned version

The pin lives in `TWOMBLY_VERSION` in `scripts/mb.py`. Move it through a Stack pull
request after reading the new version's changes. A single repo can override it with
`init --twombly-version <version>`, at the person's own risk.
