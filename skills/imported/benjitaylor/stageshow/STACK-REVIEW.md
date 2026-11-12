# Stageshow source intake

Source: https://github.com/benjitaylor/skills/tree/802057409787133703c56001080169e347305572/stageshow
Author: Benji Taylor. Upstream version: 0.1.0. Revision: `802057409787133703c56001080169e347305572`.

## Decision and scope

The user explicitly requested this skill for Stack and work use. Retain its
authored product-illustration guidance, React kit and permitted examples as one
design workflow under `stack.design`. It complements CDO/Emil motion guidance;
it does not become a general product-design authority or real-app automation.
The initial import remained `candidate` until isolated validation. The November 9
acceptance below supersedes that hold and authorizes local Claude/Codex exports.
Repository activation and actual runtime installation remain separate evidence.

## Provenance and adaptations

Every retrieved file was verified against GitHub's immutable Git blob identity.
`source.json` records upstream and imported SHA-256 hashes, omissions and changes.
LICENSE and upstream NOTICE.md are preserved unchanged. The retained brand
artwork retains its per-file sources and MIT, Apache 2.0 or CC0 license texts;
these do not grant trademark rights. Retained photographs keep PHOTOS.md.

- Add the Stack integration contract to SKILL.md; make setup and editing-copy
  instructions conditional on authorization and the runtime hold.
- Omit app-bundle icon artwork, its three dependent examples, hero-demo's
  unlicensed copied toolbar artwork, and kit-extras' omitted dependencies.
- Omit official-only Linear, American Express and Circle artwork whose usage
  terms are not bundled, and remove their three brand-registry entries.
- Replace only Phone's three private status glyph functions with newly authored
  generic geometry. Keep the component API and CSS classes. Native glyph
  fidelity is deliberately not claimed.
- Filter the playground catalog by available example modules so omitted
  resources are not offered as runnable examples. Upstream example tables and
  notices describe the original collection; the Stack contract and source
  manifest control this imported subset.
- Normalize one retained SVG line ending and one Markdown EOF blank line for
  repository formatting checks; the SVG records its modification and its artwork
  geometry is unchanged.
- Apply two local safety/reliability patches in scripts/film.mjs: fold a
  failed gate into the report's final exit status, and HTML-escape labels before
  contact-sheet interpolation. Do not print a passed gate for a nonzero report.
  At initial intake, all other helper source, package metadata and the lockfile
  were preserved, and no upstream setup, dependency lifecycle, build, browser,
  preview or filming code was run. See the follow-up below for the later launcher
  patch and validation attempts.

## Runtime hold and evidence limits

At the pinned upstream revision, scripts/film.mjs overwrites a failed gate exit
status and interpolates page-controlled labels into contact-sheet HTML. The two
local patches address those source paths: a gate failure raises result.exitCode
before report serialization and final assignment; all five HTML delimiter
characters in labels are escaped before interpolation. Static/stdlib regression
checks cover the source policy, failure-status combinations and markup-bearing
labels without importing or executing the tool. These are not reproduced browser
outcomes. State capture still observes only the first selected stage; that behavior
is unchanged. Do not use the helpers as acceptance evidence until independent
representative runtime validation passes.

The preview uses Portless/Vite, which starts a local listener; its Vite config
allows the parent directory. Filming launches installed Chrome through
playwright-core (or CHROME_PATH), accepts arbitrary URLs and writes captures and
reports. Setup may download dependencies and run transitive lifecycle scripts.
No browser downloader is configured in scripts/browser.mjs. None of these
effects is authorized merely by importing or invoking the skill.

## Promotion evidence still needed

In a separately authorized isolated project: review the exact setup actions,
serving directory/origin and permitted synthetic content; validate the local
filming patches; typecheck/build the retained subset; verify a representative still,
loop, compact layout, reduced-motion state, output containment, truthful gate
failure, and clean browser/server shutdown. Record independent visual review.
Then review activation and managed Claude/Codex publication separately.

## Validation follow-up: 2026-11-01

The user authorized continuing isolated validation with synthetic content, a
matching official browser, its sandbox enabled and no test network access.
They reported that dependency installation, typecheck and build passed in a
prior attempt, but the disposable VM's browser-image download failed because
guest DNS did not work. That VM was removed. The newer setup receipts were not
located in this checkout or the available saved-file search, so those results
remain user-reported rather than independently verified here. The denied
`/mnt/lima-cidata/network-config` read was not repeated. No privilege elevation
or attempt to bypass that denial was made.

Source review found that `scripts/browser.mjs` omitted `chromiumSandbox`, which
Playwright defaults to false. A third local patch explicitly sets it to true
for both the Chrome channel and `CHROME_PATH`. No retry with weaker options is
provided. `tests/test_stageshow_browser_launcher.py` executes that wrapper with
a fake Playwright module: default selection, explicit path, launch failure and
missing dependency. The three sandbox assertions failed before the patch; all
four tests pass afterward. These tests never launch a browser and do not prove
that a platform can run its sandbox.

A new Lima VM definition used plain mode, no host mounts, no SSH agent/public
key forwarding, no proxy environment propagation and no container runtime.
Creation stopped before boot because the current execution permissions denied
Lima's image-cache write. Separate HTTPS probes could not resolve the official
Debian image and Microsoft browser-image hosts from this shell. The unbooted VM
definition was deleted. No browser, listener or test network was started.

The proposed next route is to fetch verified VM/browser assets during setup in
an environment that permits those downloads, copy only the pinned package and
synthetic fixture into a fresh VM, and run validation with enforced network
denial. That route has not been executed or validated here. Keep the browser
sandbox enabled and stop on any isolation failure; do not change host security
settings, reuse a signed-in browser, or retry the denied diagnostic read.

`film.mjs` exports PNG stills/contact sheets, not an encoded video. Acceptance
also requires recording an actual synthetic UI clip with the matching browser
and verifying the resulting video: successful decode, duration, dimensions,
changing frames, expected final state and visual review. No video artifact or
browser acceptance receipt exists from this follow-up. The candidate and empty
publication-target list remain unchanged. After validation, use the documented
catalog/compiler procedure; do not bypass its clean-source requirements or
publish runtimes under this task's prohibition on publication.

The bounded follow-up receipt is
`artifacts/validation/stageshow/2026-11-01.json`.

## Accepted isolated validation: 2026-11-09

Maroun authorized official pinned setup downloads, isolated synthetic tests and
normal local installation into both Stack runtimes in Codex chat
`01a1c1bb-c674-7013-a1ee-dcaf8ede8354`. That run prohibited external publication.

The accepted receipt is `artifacts/validation/stageshow/2026-11-09-accepted.json`.
A disposable Lima 2.2.0 Debian 12 arm64 VM used a digest-pinned official image,
no host shares, no SSH agent/private-key forwarding, an allowlisted environment
and no signed-in state. Node 22.22.3 matched the official SHA-256 list. Exact
lockfile dependencies used `npm ci --ignore-scripts`; matching Playwright-core
1.48.2 installed official Chromium 130.0.6723.31 (revision 1140). Signed Debian
packages were version-pinned and extracted into the non-root user's directory;
no sudo or privilege elevation was used.

An inherited seccomp rule with no-new-privileges denied IP sockets and io_uring
setup before all acceptance commands. IPv4/IPv6 socket attempts returned EPERM
and an external browser navigation failed. Synthetic pages were fully inlined
local files, so no HTTP server or external resource was needed. Renderer status
proved a PID namespace and additional Chromium seccomp filtering; actual launch
arguments omitted sandbox-disabling switches. The source launcher was unchanged.

Acceptance includes a decoded 12-second 640×480 H.264 UI clip (300 frames at
25 fps), showing typing, error, correction, submission and “Account created”;
an 8-second 640×360 loop (200 frames) traversing saved/reset twice; wide and
390px compact reduced-motion posters stable across captures; representative
stills; and a complete, no-findings loop rehearsal under unchanged thresholds.
Native Playwright recordings include encoder tail time; delivered clips trim
only that tail to the declared duration. Decoded frames were visually inspected.

A deliberately clipped target returned exit 1 in both the process and report,
printed rehearsal failure and never printed success. A markup-bearing state
label round-tripped as literal caption text, with zero injected elements or
executed handlers. Outputs stayed under the designated validation output root;
source helper/lockfile hashes matched afterward. Browsers closed and the VM
stopped. No prohibited diagnostic was retried or host security setting changed.

Limits: this validates representative routes, not the whole example catalog.
Exploratory retained form/loading examples produced compact framing findings
and/or motion-sampling gaps on the VM. Those reports are preserved; they were
not reclassified or used as passed gates. Project copies still need rehearsal
and visual review. The filming helper remains a PNG exporter; actual encoded
video requires the separate recording/decoding step. Runtime installation is
verified by the owner-only normal installer receipt, not by this source note.

## Canonical publication authorization: 2026-11-12

After the source-only acceptance, the owner authorized publishing and merging
this reviewed integration, then installing both local Stack runtimes through
the normal procedure. The canonical-main provenance gate remains unchanged.
The original local-only commit and raw evidence remain preserved locally;
published VM diagnostics redact host home paths. Runtime availability still
requires successful canonical installation and both discovery checks.
