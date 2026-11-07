# Setup recipes

`mb.py init` needs three answers: how a take builds (`--build`), where the static
output lands (`--out`), and what each new worktree needs before it can build
(`--setup`). Read `package.json` scripts, the lockfile and the framework config
before choosing.

Frames are served from a subfolder on the board and as standalone folders in
Twombly, so **asset paths should be relative**. A blank frame or 404s for
`/assets/...` on the board means the build wrote root paths. If the build can't
change, `init --root-paths` makes the board serve each frame at the root of its own
address (`r1-t2.localhost`), which Chrome, Edge and Firefox resolve locally.

| Stack | `--build` | `--out` | Notes |
|---|---|---|---|
| Plain HTML, CSS, JS | `""` (none) | `.` or the folder holding `index.html` | The whole folder is copied, minus `.git` and `node_modules` |
| Vite (React, Vue, Svelte, vanilla) | `npm run build -- --base=./` | `dist` | `--base=./` makes asset paths relative |
| Next.js | `npx next build` with `output: 'export'` in `next.config` | `out` | Needs static export; set `images.unoptimized: true`. If `/_next/` assets 404 on the board, use Twombly or ask before changing `assetPrefix` |
| Astro | `npm run build` | `dist` | If assets 404 on the board, set `base` in `astro.config` |
| SvelteKit | `npm run build` with `adapter-static` | `build` | `paths.relative` must stay `true` |
| Create React App | `PUBLIC_URL=. npm run build` | `build` | |
| Storybook | `npx storybook build -o storybook-static` | `storybook-static` | Each frame shows the whole Storybook |
| Monorepo package | `cd apps/web && npm run build -- --base=./` | `apps/web/dist` | Paths are relative to the take's root |
| Design Studio | `init --preset design-studio` | `dist` | Fills in build, setup and root paths. See `design-studio.md` |

Swap `npm run` for `pnpm`, `yarn` or `bun` to match the lockfile.

## Dependencies in each take

Every take is a separate worktree, so it starts without `node_modules`.

| Situation | `--setup` |
|---|---|
| Takes never change dependencies (most design work) | `ln -s "$MB_MAIN/node_modules" node_modules` (fast; `$MB_MAIN` is the main checkout) |
| pnpm | `pnpm install --frozen-lockfile` (fast, shared store) |
| npm | `npm ci` |
| yarn | `yarn install --frozen-lockfile` |
| No dependencies | leave `--setup` unset |

Install dependencies in the main checkout first when using the symlink. If a take
adds a package, replace its symlink with a real install inside that worktree.

A `.gitignore` line like `node_modules/` matches folders, not links, so a linked
`node_modules` would land in the take's commits. After setup, the script adds every
link setup made to the repo's local `.git/info/exclude` (never committed) and lists
them under `setup.ignored_links`.

## Environment

`--setup` and `--build` run through the shell inside the take's worktree with
`MB_ROUND`, `MB_TAKE`, `MB_WORKTREE` and `MB_MAIN` set.

## No static build

Apps that only run on a server (SSR without export, apps that need a backend) can't
become frames directly. In order of preference:

1. Add a static export for the screens under exploration, if the framework supports it.
2. Build a small static harness page in the take that renders the component with
   mock data, and point `--out` at it.
3. Skip the canvas: cut takes as usual, run the dev server in each take's worktree
   on its own port, and share the URLs with the person.

## Frame size

`--frame-size WIDTHxHEIGHT` sets how frames are laid out. Use `390x844` for phone
screens, `1280x800` (default) for desktop, `768x1024` for tablet.
