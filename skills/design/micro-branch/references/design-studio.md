# Design Studio

Design Studio is an open-source prototype sandbox: React views, Markdown documents,
diagrams and canvases in one folder, with a browser preview. The `design-studio`
preset makes each take's frame open on one view, on its own, without the studio
around it.

## Set up

Run init from the Design Studio checkout, after its dependencies are installed
(`pnpm install`, once):

```sh
$MB init --preset design-studio [--localize-fonts] [--localize <host>,<host>]
```

| Setting | Preset value | Why |
|---|---|---|
| `--build` | `node src/platform/node/build/build-manifest.js --deploy && ./node_modules/.bin/vite build` | The manifest and Vite only, about 10 seconds. `pnpm build` adds release checks and typechecking, which reject work in progress |
| `--out` | `dist` | |
| `--setup` | Links `node_modules` and each `src/systems/*/node_modules` from the main checkout | Instant. A fresh `pnpm install` in each take takes about a minute |
| `--root-paths` | on | The build loads `/assets/...`, so the board serves each frame at the root of its own address, `r<N>-t<M>.localhost` |

Trunk is the branch checked out when init runs. In a Design Studio folder that is
often a feature branch, not `main`. Pass `--trunk` to choose.

## Pick the view

Each round opens its frames on one view, a `.tsx` file in a prototype folder:

```sh
$MB views                    # every view on trunk, as <prototype>/<path>
$MB round new card --question "How should the card read?" --view "<prototype>/<path>.tsx"
```

`--view` takes the full `<prototype>/<path>`, the path alone, or the end of the
path, as long as only one view matches. A take can use a different view:
`take new r1 <slug> --view ...`. A view that a take creates is not on trunk yet, so
`take new` warns instead of failing, and `views --take r1/t2` lists the take's files.

At publish, the script reads the take's build manifest and points the frame at
Design Studio's preview address (`index.html?studio-preview=1&...`). The studio
uses that address to embed views itself. It renders one view with no navigation
or chrome.

## Remote assets

A frame on the board loads fonts and images from the network like any page. To keep
frames working offline, and the same every time they are opened, name the hosts at
init: `--localize-fonts` for Google Fonts, `--localize <host>` for the rest. Each
asset is downloaded once over https and cached in
`<git-common-dir>/micro-branch/cache/remote/`. The script copies it into the
frame's `mb-assets/` folder and rewrites the snapshot's references. Snapshots are
copies, so the take's own files never change. `prepared.localized.skipped` lists
anything that failed to download.

## Limits

- A view is live in its frame, so motion and interaction work. Anything that calls
  a server needs mock data, like any frame.
- Archived prototypes are left out of the build by `--deploy`. Unarchive one to
  explore it.
- Takes share the main checkout's dependencies. A take that adds or upgrades a
  package needs its own install: delete the take's linked `node_modules` and run
  `pnpm install` inside the take.
- The preview address is part of Design Studio's internals. If an upgrade changes
  it, frames show "Invalid preview address". Fix `design_studio_entry()` in
  `scripts/mb.py` through a Stack change.
- The Design Studio folder's own `AGENTS.md` still applies inside each take. Build
  prototypes the way it says.
