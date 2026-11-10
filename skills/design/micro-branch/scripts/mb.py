#!/usr/bin/env python3
"""micro-branch: keep every design take on its own git branch.

A round is one design question. A take is one answer to it, on its own branch
and worktree, so takes never overwrite each other. Publishing a take builds it,
snapshots the output and lays it out on a local board, next to the round's other
takes. Picking a take squash-merges it into trunk and archives the round's takes
as tags.

Every command prints JSON. State, snapshots and the board live in
<git-common-dir>/micro-branch/, so they are shared by every worktree and never
leave the machine. The board listens on 127.0.0.1 only. Nothing here pushes
anything or deletes a take without tagging it first.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import functools
import hashlib
import html
import http.server
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator

STATE_VERSION = 1
DEFAULT_MAX_TAKES = 4
MAX_TAKES_CEILING = 8
BOARD_PORT = 4780
# Never copied into a frame: repo internals, dependencies, secrets and project config.
FRAME_IGNORE = (
    ".git", "node_modules", ".micro-branch", ".DS_Store", ".env*", "*.map",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb", "tsconfig*.json",
)
# The board serves a frame on its own origin (r1-t2.localhost) when its build uses root paths like /assets/.
FRAME_HOST = re.compile(r"^r(\d+)-t(\d+)\.localhost$")
EXCLUDE_HEADER = "# micro-branch: links that take setup made (safe to delete)"
GOOGLE_FONT_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")
LOCALIZE_SUFFIXES = {".css", ".js", ".mjs", ".html", ".htm", ".json", ".svg"}
MARKUP_SUFFIXES = (".html", ".htm", ".svg")
LOCALIZE_MAX_BYTES = 15 * 1024 * 1024
# Google serves woff2 only to browser user agents.
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
ASSET_TYPES = {
    "text/css": ".css", "font/woff2": ".woff2", "font/woff": ".woff", "font/ttf": ".ttf", "font/otf": ".otf",
    "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp", "image/avif": ".avif",
    "image/svg+xml": ".svg", "video/mp4": ".mp4", "video/webm": ".webm",
}
KNOWN_SUFFIXES = set(ASSET_TYPES.values()) | {".jpeg", ".ico", ".json"}
PRESETS = ("design-studio",)
FRAME_KEYS = ("path", "published_at", "commit", "entry", "view")

DEFAULT_CONFIG: dict[str, Any] = {
    "trunk": None,
    "name": None,
    "build": None,
    "out": ".",
    "entry": "index.html",
    "setup": None,
    "max_takes": DEFAULT_MAX_TAKES,
    "frame_width": 1280,
    "frame_height": 800,
    "takes_dir": None,
    "preset": None,
    "root_paths": False,
    "localize": [],
}


class MBError(Exception):
    def __init__(self, message: str, hint: str | None = None, **extra: Any) -> None:
        super().__init__(message)
        self.hint = hint
        self.extra = extra


# ---------------------------------------------------------------- helpers


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def slugify(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not slug:
        raise MBError(f"'{text}' has no letters or digits to name a branch with")
    return slug[:limit].rstrip("-")


def run(cmd: list[str], cwd: Path | str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise MBError(
            f"`{' '.join(shlex.quote(c) for c in cmd)}` failed",
            stderr=proc.stderr.strip()[-2000:],
            stdout=proc.stdout.strip()[-2000:],
        )
    return proc


def git(*args: str, cwd: Path | str | None = None, check: bool = True) -> str:
    return run(["git", *args], cwd=cwd, check=check).stdout.strip()


def if_set(key: str, value: Any) -> dict[str, Any]:
    """`{key: value}` when value is set, else `{}`: for optional fields in replies."""
    return {key: value} if value else {}


def emit(payload: dict[str, Any], code: int = 0) -> int:
    print(json.dumps(payload, indent=2, sort_keys=False))
    return code


# ---------------------------------------------------------------- repo + state


class Repo:
    def __init__(self, cwd: Path) -> None:
        inside = run(["git", "rev-parse", "--is-inside-work-tree"], cwd=cwd, check=False)
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            raise MBError("not inside a git work tree", hint="cd into the project, or run `git init` first")
        self.cwd = cwd
        common = Path(git("rev-parse", "--git-common-dir", cwd=cwd))
        self.common_dir = (cwd / common).resolve() if not common.is_absolute() else common
        self.state_dir = self.common_dir / "micro-branch"
        self.state_file = self.state_dir / "state.json"
        self.lock_file = self.state_dir / "state.lock"
        self.main_worktree = self.worktrees()[0]["path"]

    def worktrees(self) -> list[dict[str, Any]]:
        out = git("worktree", "list", "--porcelain", cwd=self.cwd)
        items: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
        for line in out.splitlines() + [""]:
            if not line:
                if current:
                    items.append(current)
                current = {}
                continue
            key, _, value = line.partition(" ")
            if key == "worktree":
                current["path"] = Path(value)
            elif key == "branch":
                current["branch"] = value.removeprefix("refs/heads/")
            elif key == "HEAD":
                current["head"] = value
            else:
                current[key] = value or True
        return items

    def worktree_for(self, branch: str) -> Path | None:
        for item in self.worktrees():
            if item.get("branch") == branch:
                return item["path"]
        return None

    def ref_exists(self, ref: str) -> bool:
        return run(["git", "rev-parse", "--verify", "--quiet", ref + "^{commit}"], cwd=self.cwd, check=False).returncode == 0

    def takes_root(self, config: dict[str, Any]) -> Path:
        if config.get("takes_dir"):
            return Path(config["takes_dir"]).expanduser().resolve()
        main = Path(self.main_worktree)
        return main.parent / f"{main.name}.takes"


@contextlib.contextmanager
def locked_state(repo: Repo, create: bool = False) -> Iterator[dict[str, Any]]:
    """Load, yield and save state under an exclusive lock."""
    if not repo.state_file.exists() and not create:
        raise MBError("micro-branch is not set up in this repo", hint="run `mb.py init` first")
    repo.state_dir.mkdir(parents=True, exist_ok=True)
    with open(repo.lock_file, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_state(repo) if repo.state_file.exists() else new_state()
        yield state
        tmp = repo.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2) + "\n")
        os.replace(tmp, repo.state_file)


def new_state() -> dict[str, Any]:
    return {"version": STATE_VERSION, "config": dict(DEFAULT_CONFIG), "rounds": {}, "canvas": {}}


def read_state(repo: Repo) -> dict[str, Any]:
    if not repo.state_file.exists():
        raise MBError("micro-branch is not set up in this repo", hint="run `mb.py init` first")
    state = json.loads(repo.state_file.read_text())
    if state.get("version") != STATE_VERSION:
        raise MBError(f"state version {state.get('version')} is not supported by this script")
    migrate(state)
    return state


def migrate(state: dict[str, Any]) -> None:
    """Bring state written by an older version in line with this one; the board is the only canvas.

    Settings, canvas records and frame fields this version doesn't know are dropped,
    and takes another canvas refused become published, since the board shows them.
    Any command that saves state (plain `init` will do) writes the result to disk.
    """
    stored = state.get("config", {})
    state["config"] = {key: stored.get(key, default) for key, default in DEFAULT_CONFIG.items()}
    board = (state.get("canvas") or {}).get("board")
    state["canvas"] = {"board": board} if board else {}
    for rnd in state.get("rounds", {}).values():
        for take in rnd.get("takes", {}).values():
            if take.get("frame"):
                take["frame"] = {key: take["frame"][key] for key in FRAME_KEYS if key in take["frame"]}
            if take.get("status") == "rejected":
                take["status"] = "published"


def resolve(state: dict[str, Any], ref: str, round_hint: str | None = None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Resolve 'r1', 'r1/t2', 'r1-slug/t2-slug', 'mb/r1-slug/t2-slug' or 't2' + round_hint."""
    ref = ref.strip().removeprefix("mb-archive/").removeprefix("mb/")
    round_part, _, take_part = ref.partition("/")
    if not take_part and round_hint and re.match(r"^t\d+", round_part):
        round_part, take_part = round_hint, round_part
    rnd = match_id(state["rounds"], round_part, "round")
    if not take_part:
        return rnd, None
    return rnd, match_id(rnd["takes"], take_part, "take", scope=rnd["id"])


def resolve_take(state: dict[str, Any], ref: str, round_hint: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Like resolve(), but the reference must name a take."""
    rnd, take = resolve(state, ref, round_hint)
    if take is None:
        raise MBError(f"'{ref}' names a round, not a take", hint=f"add the take, for example {rnd['id']}/t1")
    return rnd, take


def match_id(items: dict[str, Any], key: str, kind: str, scope: str | None = None) -> dict[str, Any]:
    if key in items:
        return items[key]
    hits = [v for k, v in items.items() if k.split("-", 1)[0] == key or k.startswith(key + "-")]
    if len(hits) == 1:
        return hits[0]
    where = f" in {scope}" if scope else ""
    known = ", ".join(items) or "none yet"
    raise MBError(f"no single {kind} matches '{key}'{where}", hint=f"known: {known}")


def label(rnd: dict[str, Any], take: dict[str, Any]) -> str:
    words = take["slug"].replace("-", " ")
    return f"R{rnd['n']} · T{take['n']} {words}"


# ---------------------------------------------------------------- board


class Board:
    """A zero-dependency local page that shows every take's frame side by side."""

    def __init__(self, repo: Repo, state: dict[str, Any]) -> None:
        self.repo, self.state = repo, state
        self.root = repo.state_dir

    def frame_link(self, rnd: dict[str, Any], take: dict[str, Any], attr: str) -> str:
        """`src`/`href` for a frame: a path on the board, or its own origin when the build uses root paths."""
        frame = take.get("frame") or {}
        entry = html.escape(frame.get("entry") or self.state["config"]["entry"])
        if self.state["config"].get("root_paths"):
            return f'data-frame-host="r{rnd["n"]}-t{take["n"]}" data-entry="{entry}" data-attr="{attr}"'
        return f'{attr}="../{html.escape(frame["path"])}/{entry}"'

    def render(self) -> Path:
        board = self.root / "board"
        board.mkdir(parents=True, exist_ok=True)
        cfg = self.state["config"]
        width, height = int(cfg["frame_width"]), int(cfg["frame_height"])
        card = 420
        scale = card / width
        parts = []
        for rnd in reversed(list(self.state["rounds"].values())):
            cards = []
            for take in rnd["takes"].values():
                frame = take.get("frame") or {}
                src = frame.get("path")
                status = take["status"]
                body = (
                    f'<div class="viewport" style="height:{round(height * scale)}px">'
                    f'<iframe loading="lazy" {self.frame_link(rnd, take, "src")} '
                    f'style="width:{width}px;height:{height}px;transform:scale({scale:.4f})" '
                    f'title="{html.escape(label(rnd, take))}"></iframe></div>'
                    if src
                    else '<div class="viewport empty">not published yet</div>'
                )
                link = f'<a {self.frame_link(rnd, take, "href")} target="_blank">open</a>' if src else ""
                note = f'<p class="note">{html.escape(take["note"])}</p>' if take.get("note") else ""
                cards.append(
                    f'<article class="card {html.escape(status)}"><header><strong>{html.escape(label(rnd, take))}</strong>'
                    f'<span class="badge">{html.escape(status)}</span></header>{body}{note}'
                    f'<footer><code>{html.escape(take["branch"])}</code>{link}</footer></article>'
                )
            built_on = f' · built on {html.escape(rnd["built_on"])}' if rnd.get("built_on") else ""
            parts.append(
                f'<section><h2>R{rnd["n"]} · {html.escape(rnd["question"])}</h2>'
                f'<p class="meta">{html.escape(rnd["id"])} · {html.escape(rnd["status"])}{built_on}</p>'
                f'<div class="grid">{"".join(cards) or "<p>No takes yet.</p>"}</div></section>'
            )
        title = html.escape(cfg.get("name") or Path(self.repo.main_worktree).name)
        page = BOARD_TEMPLATE.format(title=title, card=card, body="".join(parts) or "<p>No rounds yet.</p>", updated=now())
        (board / "index.html").write_text(page)
        return board / "index.html"

    def ensure(self) -> dict[str, Any]:
        self.render()
        info = self.state["canvas"].get("board") or {}
        pid, port = info.get("pid"), info.get("port")
        if pid and port and pid_alive(pid) and port_open(port):
            return {"url": f"http://127.0.0.1:{port}/board/", "pid": pid, "started": False}
        port = free_port(BOARD_PORT)
        log = open(self.root / "board.log", "a")
        proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "_board-serve", str(self.root), str(port)],
            stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True,
        )
        for _ in range(50):
            if port_open(port):
                break
            time.sleep(0.1)
        self.state["canvas"]["board"] = {"pid": proc.pid, "port": port}
        return {"url": f"http://127.0.0.1:{port}/board/", "pid": proc.pid, "started": True}

    def stop(self) -> dict[str, Any]:
        info = self.state["canvas"].pop("board", None) or {}
        if info.get("pid") and pid_alive(info["pid"]):
            os.kill(info["pid"], signal.SIGTERM)
            return {"stopped": True}
        return {"stopped": False}


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def free_port(start: int) -> int:
    for port in range(start, start + 50):
        if not port_open(port):
            return port
    raise MBError("no free port for the board between 4780 and 4829")


# ---------------------------------------------------------------- Design Studio


# A fast build for frames: the manifest plus Vite, without the release checks of `pnpm build`.
DESIGN_STUDIO_BUILD = "node src/platform/node/build/build-manifest.js --deploy && ./node_modules/.bin/vite build"
# Takes link to the main checkout's dependencies: the root node_modules and each design system's own.
DESIGN_STUDIO_SETUP = (
    'ln -s "$MB_MAIN/node_modules" node_modules && '
    '{ for d in "$MB_MAIN"/src/systems/*/node_modules; do s="${d#"$MB_MAIN"/}"; '
    '[ -d "$d" ] && [ -d "$(dirname "$s")" ] && [ ! -e "$s" ] && ln -s "$d" "$s"; done; :; }'
)


def design_studio_preset(main: Path) -> dict[str, Any]:
    if not (main / "studio.config.json").is_file():
        raise MBError("this repo has no studio.config.json, so it is not a Design Studio folder",
                      hint="run init from the Design Studio checkout, or drop --preset")
    if not (main / "node_modules").is_dir():
        raise MBError("Design Studio's dependencies are not installed in the main checkout",
                      hint="run `pnpm install` there once; every take links to them")
    return {"build": DESIGN_STUDIO_BUILD, "out": "dist", "entry": "index.html", "setup": DESIGN_STUDIO_SETUP,
            "root_paths": True}


def design_studio_views(paths: list[str]) -> list[dict[str, str]]:
    """Views are .tsx files in a prototype folder (one with meta.json), outside folders starting with _ or ."""
    protos = {Path(p).parent for p in paths if re.fullmatch(r"src/prototypes/[^/]+/[^/]+/meta\.json", p)}
    views = []
    for p in sorted(paths):
        path = Path(p)
        root = next((r for r in protos if r in path.parents), None)
        if root is None or path.suffix != ".tsx":
            continue
        rel = path.relative_to(root)
        if any(part.startswith(("_", ".")) for part in rel.parts):
            continue
        views.append({"view": f"{root.name}/{rel.as_posix()}", "prototype": root.name, "contributor": root.parent.name})
    return views


def prototype_files(repo: Repo, ref: str | None = None, worktree: Path | None = None) -> list[str]:
    if worktree is not None:
        out = git("ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "src/prototypes", cwd=worktree)
    else:
        out = git("ls-tree", "-r", "-z", "--name-only", ref or "HEAD", "--", "src/prototypes", cwd=repo.cwd)
    return [p for p in out.split("\0") if p]


def match_view(view: str, refs: list[str]) -> str:
    """Find one view by '<prototype>/<path>', by its path alone, or by the end of its path."""
    key = view.strip().strip("/")
    bare = key.removesuffix(".tsx").lower()
    tests = (
        lambda r: r == key,
        lambda r: r.removesuffix(".tsx").lower() == bare,
        lambda r: r.split("/", 1)[1].removesuffix(".tsx").lower() == bare,
        lambda r: r.removesuffix(".tsx").lower().endswith(bare),
    )
    for test in tests:
        hits = [r for r in refs if test(r)]
        if len(hits) == 1:
            return hits[0]
        if hits:
            raise MBError(f"'{view}' matches {len(hits)} views", hint="name it as <prototype>/<path>: " + "; ".join(hits[:12]))
    raise MBError(f"no view matches '{view}'", hint="known views: " + ("; ".join(refs[:15]) or "none"))


def check_view(repo: Repo, cfg: dict[str, Any], view: str | None, ref: str | None = None,
               worktree: Path | None = None) -> str | None:
    """Reject --view outside Design Studio; return a warning when the view isn't in the files yet."""
    if not view:
        return None
    if cfg.get("preset") != "design-studio":
        raise MBError("--view needs the design-studio preset", hint="use --entry for other projects")
    refs = [v["view"] for v in design_studio_views(prototype_files(repo, ref, worktree))]
    try:
        match_view(view, refs)
    except MBError as err:
        return f"{err}; publish looks again in the take's build"
    return None


def design_studio_entry(out_dir: Path, view: str) -> tuple[str, str]:
    """Entry that opens one view on its own, through Design Studio's preview address."""
    folder = out_dir / "prototypes"
    try:
        manifest = json.loads((folder / "manifest.json").read_text())
    except (OSError, ValueError):
        raise MBError("the build has no prototypes/manifest.json", hint="check the build command; Design Studio writes it while building")
    found: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for proto in manifest.get("prototypes", []):
        with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
            items = json.loads((folder / "artifacts" / proto["contributorKey"] / f"{proto['id']}.json").read_text())
            for item in items:
                if item.get("fileType") == "view":
                    found[f"{proto['id']}/{item['path']}"] = (proto, item)
    try:
        ref = match_view(view, sorted(found))
    except MBError as err:
        raise MBError(f"{err} in the take's build", hint=f"{err.hint}. Archived prototypes are left out of the build")
    proto, item = found[ref]
    if not proto.get("studioId") or not item.get("studioId"):
        raise MBError(f"{ref} has no studio id in the build", hint="run `pnpm studio sync` in the take, then publish again")
    config = {
        "target": {"contributor": proto["contributorKey"], "prototype": proto["id"], "prototypeId": proto["studioId"],
                   "artifact": item["path"], "artifactId": item["studioId"]},
        "href": f"/prototypes/{proto['studioId']}/artifacts/{item['studioId']}", "dark": False, "surface": "page",
    }
    query = urllib.parse.urlencode({"studio-preview": "1", "session": "micro-branch",
                                    "config": json.dumps(config, separators=(",", ":"))})
    return f"index.html?{query}", ref


# ---------------------------------------------------------------- snapshot


def frame_entry(cfg: dict[str, Any], rnd: dict[str, Any], take: dict[str, Any], out_dir: Path) -> tuple[str, str | None]:
    """The take's own view or entry wins, then the round's, then the repo's entry."""
    for scope in (take, rnd):
        if scope.get("view"):
            return design_studio_entry(out_dir, scope["view"])
        if scope.get("entry"):
            return scope["entry"], None
    return cfg["entry"], None


def entry_file(entry: str) -> str:
    return re.split(r"[?#]", entry, maxsplit=1)[0]


def fetch_remote(repo: Repo, url: str) -> tuple[bytes, str]:
    """Download one asset, cached in the state folder so republishing works offline."""
    cache = repo.state_dir / "cache" / "remote"
    key = hashlib.sha256(url.encode()).hexdigest()
    body, meta = cache / f"{key}.bin", cache / f"{key}.json"
    if body.is_file() and meta.is_file():
        return body.read_bytes(), json.loads(meta.read_text()).get("type", "")
    if urllib.parse.urlsplit(url).scheme != "https":
        raise MBError("only https assets are copied")
    request = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=20) as resp:
            data, kind = resp.read(LOCALIZE_MAX_BYTES + 1), resp.headers.get_content_type()
    except (OSError, ValueError) as err:
        raise MBError(f"download failed: {err}")
    if len(data) > LOCALIZE_MAX_BYTES:
        raise MBError("larger than 15 MB")
    cache.mkdir(parents=True, exist_ok=True)
    body.write_bytes(data)
    meta.write_text(json.dumps({"url": url, "type": kind, "fetched_at": now()}) + "\n")
    return data, kind


def asset_suffix(url: str, kind: str) -> str:
    suffix = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    if suffix in KNOWN_SUFFIXES:
        return suffix
    return ASSET_TYPES.get(kind, ".bin")


def localize_snapshot(repo: Repo, cfg: dict[str, Any], snapshot: Path) -> dict[str, Any]:
    """Copy assets from the listed hosts into mb-assets/ and point the snapshot's files at the copies."""
    hosts = list(cfg.get("localize") or [])
    pattern = re.compile(r"https://(?:%s)/[^\s\"'`()<>\\{}$]+(?=[\s\"'`()<>\\]|$)" % "|".join(map(re.escape, hosts)))
    assets = snapshot / "mb-assets"
    copies: dict[str, str | None] = {}
    skipped: list[dict[str, str]] = []

    def reference(target: str, source: Path) -> str:
        """How `source` should point at the copy at `target` (a path inside the snapshot)."""
        if source.suffix == ".css":  # url() resolves against the stylesheet itself
            return os.path.relpath(snapshot / target, source.parent).replace(os.sep, "/")
        if cfg.get("root_paths"):
            return "/" + target
        if source.suffix in MARKUP_SUFFIXES:
            return os.path.relpath(snapshot / target, source.parent).replace(os.sep, "/")
        return target  # scripts resolve against the page, which sits at the snapshot root

    def copy(url: str) -> str | None:
        if url in copies:
            return copies[url]
        copies[url] = None  # also stops a stylesheet that imports itself
        try:
            data, kind = fetch_remote(repo, url)
        except MBError as err:
            skipped.append({"url": url, "reason": str(err)})
            return None
        suffix = asset_suffix(url, kind)
        dest = assets / (hashlib.sha256(url.encode()).hexdigest()[:16] + suffix)
        assets.mkdir(parents=True, exist_ok=True)
        if suffix == ".css":  # a hosted stylesheet, such as Google Fonts CSS, points at more files
            dest.write_text(rewrite(data.decode("utf-8", "replace"), dest))
        else:
            dest.write_bytes(data)
        copies[url] = dest.relative_to(snapshot).as_posix()
        return copies[url]

    def rewrite(text: str, source: Path) -> str:
        def swap(match: re.Match) -> str:
            url = match.group(0)
            target = copy(html.unescape(url) if source.suffix in MARKUP_SUFFIXES else url)
            return reference(target, source) if target else url
        return pattern.sub(swap, text)

    files = []
    for path in sorted(snapshot.rglob("*")):
        if path.suffix.lower() not in LOCALIZE_SUFFIXES or not path.is_file() or assets in path.parents:
            continue
        text = path.read_text("utf-8", errors="surrogateescape")
        if not any(host in text for host in hosts):
            continue
        new = rewrite(text, path)
        if new != text:
            path.write_text(new, "utf-8", errors="surrogateescape")
            files.append(path.relative_to(snapshot).as_posix())
    return {"hosts": hosts, "assets": sum(1 for v in copies.values() if v), "files": files, "skipped": skipped[:20]}


def prepare_snapshot(repo: Repo, cfg: dict[str, Any], snapshot: Path) -> dict[str, Any]:
    report: dict[str, Any] = {}
    if cfg.get("localize"):
        report["localized"] = localize_snapshot(repo, cfg, snapshot)
    return report


def serve_board(root: str, port: int) -> None:
    """The board's server: the state folder on 127.0.0.1, and each frame at the root of r<N>-t<M>.localhost."""

    class Handler(http.server.SimpleHTTPRequestHandler):
        def translate_path(self, path: str) -> str:
            match = FRAME_HOST.match((self.headers.get("Host") or "").rsplit(":", 1)[0].lower())
            if match:
                hits = sorted((Path(root) / "frames").glob(f"r{match[1]}-*/t{match[2]}-*"))
                self.directory = str(hits[0]) if len(hits) == 1 else str(Path(root) / "frames" / ".none")
            return super().translate_path(path)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Handler, directory=root))
    server.serve_forever()


# ---------------------------------------------------------------- commands


def cmd_init(repo: Repo, args: argparse.Namespace) -> dict[str, Any]:
    with locked_state(repo, create=True) as state:
        cfg = state["config"]
        if args.trunk or not cfg.get("trunk"):
            trunk = args.trunk or git("branch", "--show-current", cwd=repo.main_worktree)
            if not trunk:
                raise MBError("the main checkout is on a detached HEAD", hint="pass --trunk <branch>")
            cfg["trunk"] = trunk
        if args.preset:
            cfg.update(design_studio_preset(Path(repo.main_worktree)), preset=args.preset)
        for key in ("name", "build", "out", "entry", "setup", "takes_dir"):
            value = getattr(args, key, None)
            if value is not None:
                cfg[key] = None if value == "" else value
        if args.root_paths is not None:
            cfg["root_paths"] = args.root_paths
        if args.localize is not None:
            cfg["localize"] = [h.strip().lower() for h in args.localize.split(",") if h.strip()]
        if args.localize_fonts:
            cfg["localize"] = list(dict.fromkeys([*cfg["localize"], *GOOGLE_FONT_HOSTS]))
        bad = [h for h in cfg["localize"] if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", h)]
        if bad:
            raise MBError(f"not a host name: {', '.join(bad)}", hint="pass bare hosts, e.g. --localize images.example.com")
        if args.max_takes is not None:
            if not 1 <= args.max_takes <= MAX_TAKES_CEILING:
                raise MBError(f"--max-takes must be between 1 and {MAX_TAKES_CEILING}")
            cfg["max_takes"] = args.max_takes
        if args.frame_size:
            w, _, h = args.frame_size.partition("x")
            cfg["frame_width"], cfg["frame_height"] = int(w), int(h)
        if not repo.ref_exists(cfg["trunk"]):
            raise MBError(f"trunk '{cfg['trunk']}' has no commits yet", hint="commit something first")
        return {"ok": True, "config": cfg, "state_dir": str(repo.state_dir), "takes_dir": str(repo.takes_root(cfg))}


def cmd_status(repo: Repo, args: argparse.Namespace) -> dict[str, Any]:
    state = read_state(repo)
    rounds = list(state["rounds"].values())
    if args.round:
        rounds = [resolve(state, args.round)[0]]
    for rnd in rounds:
        for take in rnd["takes"].values():
            take["worktree_exists"] = bool(take.get("worktree")) and Path(take["worktree"]).exists()
            take["label"] = label(rnd, take)
    return {"ok": True, "config": state["config"], "rounds": rounds, "canvas": state["canvas"]}


def cmd_round_new(repo: Repo, args: argparse.Namespace) -> dict[str, Any]:
    with locked_state(repo) as state:
        base_ref = args.from_ref or state["config"]["trunk"]
        if not repo.ref_exists(base_ref):
            raise MBError(f"'{base_ref}' is not a commit")
        warning = check_view(repo, state["config"], args.view, ref=base_ref)
        rnd = add_round(state, args, git("rev-parse", base_ref, cwd=repo.cwd), base_ref, None)
        return {"ok": True, "round": rnd, **if_set("warning", warning)}


def add_round(state: dict[str, Any], args: argparse.Namespace, base: str, base_ref: str, built_on: str | None,
              inherit: dict[str, Any] | None = None) -> dict[str, Any]:
    n = len(state["rounds"]) + 1
    slug = slugify(args.slug)
    rid = f"r{n}-{slug}"
    inherit = inherit or {}
    rnd = {
        "id": rid, "n": n, "slug": slug, "question": args.question, "base": base, "base_ref": base_ref,
        "built_on": built_on, "status": "open", "picked": None, "created_at": now(), "takes": {},
        "entry": args.entry or inherit.get("entry"), "view": args.view or inherit.get("view"),
    }
    state["rounds"][rid] = rnd
    return rnd


def cmd_round_next(repo: Repo, args: argparse.Namespace) -> dict[str, Any]:
    with locked_state(repo) as state:
        src_round, take = resolve_take(state, args.take)
        ref = take_ref(repo, take)
        warning = check_view(repo, state["config"], args.view, ref=ref)
        inherit = {"entry": take.get("entry") or src_round.get("entry"), "view": take.get("view") or src_round.get("view")}
        rnd = add_round(state, args, git("rev-parse", ref, cwd=repo.cwd), ref, f"{src_round['id']}/{take['id']}", inherit)
        return {"ok": True, "round": rnd, **if_set("warning", warning)}


def take_ref(repo: Repo, take: dict[str, Any]) -> str:
    if repo.ref_exists(take["branch"]):
        return take["branch"]
    if take.get("archive_tag") and repo.ref_exists(take["archive_tag"]):
        return take["archive_tag"]
    raise MBError(f"take {take['id']} has neither its branch nor its archive tag")


def cmd_take_new(repo: Repo, args: argparse.Namespace) -> dict[str, Any]:
    with locked_state(repo) as state:
        cfg = state["config"]
        rnd, _ = resolve(state, args.round)
        if rnd["status"] != "open":
            raise MBError(f"round {rnd['id']} is {rnd['status']}", hint="start a new round, or use `round next` to build on a take")
        if len(rnd["takes"]) >= int(cfg["max_takes"]):
            raise MBError(
                f"round {rnd['id']} already has {len(rnd['takes'])} takes (limit {cfg['max_takes']})",
                hint="pick one, or start the next round from the strongest take",
            )
        base, from_take = rnd["base"], None
        if args.from_take:
            _, src = resolve_take(state, args.from_take, round_hint=rnd["id"])
            base, from_take = git("rev-parse", take_ref(repo, src), cwd=repo.cwd), src["id"]
        warning = check_view(repo, cfg, args.view, ref=base)  # before any branch exists
        n, slug = len(rnd["takes"]) + 1, slugify(args.slug)
        tid = f"t{n}-{slug}"
        branch = f"mb/{rnd['id']}/{tid}"
        path = repo.takes_root(cfg) / rnd["id"] / tid
        if repo.ref_exists(branch):
            raise MBError(f"branch {branch} already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        git("worktree", "add", "-b", branch, str(path), base, cwd=repo.cwd)
        take = {
            "id": tid, "n": n, "slug": slug, "branch": branch, "worktree": str(path), "base": base,
            "from_take": from_take, "note": args.note or "", "status": "open", "commit": None, "frame": None,
            "archive_tag": None, "created_at": now(), "entry": args.entry, "view": args.view,
        }
        rnd["takes"][tid] = take
    setup = run_setup(repo, cfg.get("setup"), take, take_env(repo, rnd, take))
    return {"ok": True, "round": rnd["id"], "take": take, "label": label(rnd, take), "setup": setup,
            **if_set("warning", warning)}


def take_env(repo: Repo, rnd: dict[str, Any], take: dict[str, Any]) -> dict[str, str]:
    """Environment for setup and build commands, as documented in setup-recipes.md."""
    return dict(os.environ, MB_ROUND=rnd["id"], MB_TAKE=take["id"], MB_WORKTREE=take["worktree"],
                MB_MAIN=str(repo.main_worktree))


def run_setup(repo: Repo, cmd: str | None, take: dict[str, Any], env: dict[str, str]) -> dict[str, Any] | None:
    if not cmd:
        return None
    proc = subprocess.run(cmd, shell=True, cwd=take["worktree"], text=True, capture_output=True, env=env)
    if proc.returncode != 0:
        raise MBError(f"setup failed in {take['worktree']}", hint="fix the setup command with `mb.py init --setup`",
                      stderr=proc.stderr.strip()[-2000:])
    return {"command": cmd, "ok": True, "ignored_links": ignore_setup_links(repo, Path(take["worktree"]))}


def ignore_setup_links(repo: Repo, worktree: Path) -> list[str]:
    """Keep symlinks that setup made out of take commits.

    `.gitignore` entries like `node_modules/` match folders only, so a linked
    node_modules would otherwise be committed. The links go into the repo's
    local `info/exclude`, which is never committed or pushed.
    """
    out = git("ls-files", "-z", "--others", "--exclude-standard", cwd=worktree)
    links = [p for p in out.split("\0") if p and (worktree / p).is_symlink()]
    exclude = repo.common_dir / "info" / "exclude"
    text = exclude.read_text() if exclude.exists() else ""
    lines = text.splitlines()
    patterns = ["/" + re.sub(r"([\\*?\[!#])", r"\\\1", p) for p in links]  # match each link literally
    new = [line for line in dict.fromkeys(patterns) if line not in lines]
    if not new:
        return links
    block = []
    if text and not text.endswith("\n"):
        block.append("")
    if EXCLUDE_HEADER not in lines:
        if lines:
            block.append("")
        block.append(EXCLUDE_HEADER)
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with open(exclude, "a") as fh:
        fh.write("\n".join(block + new) + "\n")
    return links


def cmd_open(repo: Repo, args: argparse.Namespace) -> dict[str, Any]:
    with locked_state(repo) as state:
        rnd, take = resolve_take(state, args.take)
        path = Path(take["worktree"])
        restored = False
        if not repo.ref_exists(take["branch"]):
            tag = take.get("archive_tag")
            if not tag or not repo.ref_exists(tag):
                raise MBError(f"take {take['id']} has no branch or archive tag to restore")
            git("branch", take["branch"], tag, cwd=repo.cwd)
            restored = True
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            git("worktree", "prune", cwd=repo.cwd)
            git("worktree", "add", str(path), take["branch"], cwd=repo.cwd)
            restored = True
        if take["status"] == "archived":
            take["status"] = "reopened"
        return {"ok": True, "label": label(rnd, take), "worktree": str(path), "branch": take["branch"], "restored": restored}


def cmd_publish(repo: Repo, args: argparse.Namespace) -> dict[str, Any]:
    state = read_state(repo)
    rnd, take = resolve_take(state, args.take)
    cfg = state["config"]
    worktree = Path(take["worktree"])
    if not worktree.exists():
        raise MBError(f"take {take['id']} has no worktree", hint=f"run `mb.py open {rnd['id']}/{take['id']}` first")
    committed = commit_take(worktree, rnd, take, args.message)
    commit = git("rev-parse", "HEAD", cwd=worktree)
    log_path = repo.state_dir / "logs" / rnd["id"] / f"{take['id']}.build.log"
    build = run_build(cfg.get("build"), worktree, take_env(repo, rnd, take), log_path)
    if not build["ok"]:
        with locked_state(repo) as fresh:
            stored = fresh["rounds"][rnd["id"]]["takes"][take["id"]]
            stored.update(status="broken", commit=commit)
        raise MBError(f"build failed for {label(rnd, take)}; nothing was published", hint=f"read {log_path}",
                      log_tail=build["tail"])
    out_dir = (worktree / cfg["out"]).resolve()
    if not out_dir.is_dir():
        raise MBError(f"build output '{cfg['out']}' does not exist in the take", hint="set the right folder with `mb.py init --out`")
    entry, view = frame_entry(cfg, rnd, take, out_dir)
    if not (out_dir / entry_file(entry)).exists():
        raise MBError(f"'{entry_file(entry)}' is missing from the build output",
                      hint="set the entry with `mb.py init --entry`, or per round with `round new --entry`")
    snapshot = repo.state_dir / "frames" / rnd["id"] / take["id"]
    if snapshot.exists():
        shutil.rmtree(snapshot)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(out_dir, snapshot, ignore=shutil.ignore_patterns(*FRAME_IGNORE))
    prepared = prepare_snapshot(repo, cfg, snapshot)
    with locked_state(repo) as fresh:
        stored = fresh["rounds"][rnd["id"]]["takes"][take["id"]]
        frame = {"path": str(snapshot.relative_to(repo.state_dir)), "published_at": now(), "commit": commit,
                 "entry": entry, "view": view}
        stored.update(status="published", commit=commit, frame=frame)
        board = Board(repo, fresh).ensure()  # renders the board and starts its server if needed
    return {"ok": True, "label": label(rnd, take), "committed": committed, "commit": commit, "frame": frame,
            "board": board["url"], **if_set("prepared", prepared)}


def commit_take(worktree: Path, rnd: dict[str, Any], take: dict[str, Any], message: str | None) -> bool:
    if not git("status", "--porcelain", cwd=worktree):
        return False
    git("add", "-A", cwd=worktree)
    subject = message or f"take({rnd['id']}/{take['id']}): {take['slug'].replace('-', ' ')}"
    body = f"\n\nMicro-Branch-Round: {rnd['id']}\nMicro-Branch-Take: {take['id']}\nMicro-Branch-Question: {rnd['question']}"
    git("commit", "-q", "-m", subject + body, cwd=worktree)
    return True


def run_build(cmd: str | None, worktree: Path, env: dict[str, str], log_path: Path) -> dict[str, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not cmd:
        log_path.write_text("no build command; publishing the output folder as it is\n")
        return {"ok": True, "tail": ""}
    proc = subprocess.run(cmd, shell=True, cwd=worktree, text=True, capture_output=True, env=env)
    log_path.write_text(f"$ {cmd}\n{proc.stdout}\n{proc.stderr}")
    return {"ok": proc.returncode == 0, "tail": (proc.stdout + proc.stderr).strip()[-1500:]}


def cmd_pick(repo: Repo, args: argparse.Namespace) -> dict[str, Any]:
    with locked_state(repo) as state:
        cfg = state["config"]
        rnd, take = resolve_take(state, args.take)
        if rnd["status"] != "open":
            raise MBError(f"round {rnd['id']} is already {rnd['status']}")
        trunk = cfg["trunk"]
        trunk_tree = repo.worktree_for(trunk)
        if trunk_tree is None:
            raise MBError(f"trunk '{trunk}' is not checked out anywhere", hint=f"run `git switch {trunk}` in the main checkout")
        if git("status", "--porcelain", "--untracked-files=no", cwd=trunk_tree):
            raise MBError(f"trunk checkout {trunk_tree} has uncommitted changes", hint="commit or stash them, then pick again")
        if Path(take["worktree"]).exists():
            commit_take(Path(take["worktree"]), rnd, take, None)
        others = [t["id"] for t in rnd["takes"].values() if t["id"] != take["id"]]
        subject = f"pick({rnd['id']}): {take['id']} for \"{rnd['question']}\""
        body = (
            f"\n\nPicked {take['id']}" + (f" over {', '.join(others)}" if others else "") + ".\n\n"
            f"Micro-Branch-Round: {rnd['id']}\nMicro-Branch-Take: {take['id']}\n"
            f"Micro-Branch-Archive: mb-archive/{rnd['id']}/{take['id']}"
        )
        if args.no_squash:
            proc = run(["git", "merge", "--no-ff", "-m", subject + body, take["branch"]], cwd=trunk_tree, check=False)
        else:
            proc = run(["git", "merge", "--squash", take["branch"]], cwd=trunk_tree, check=False)
        if proc.returncode != 0:
            run(["git", "reset", "--merge"], cwd=trunk_tree, check=False)
            raise MBError(
                f"{take['id']} does not merge cleanly into {trunk}; trunk is unchanged",
                hint=f"in {take['worktree']}, run `git merge {trunk}`, resolve, run `mb.py publish`, then pick again",
                stderr=(proc.stdout + proc.stderr).strip()[-1500:],
            )
        if not args.no_squash:
            if run(["git", "diff", "--cached", "--quiet"], cwd=trunk_tree, check=False).returncode == 0:
                raise MBError(f"{take['id']} has no changes against {trunk}", hint="nothing to pick")
            git("commit", "-q", "-m", subject + body, cwd=trunk_tree)
        picked_commit = git("rev-parse", "HEAD", cwd=trunk_tree)
        archived = archive_round(repo, rnd, picked=take["id"])
        rnd.update(status="picked", picked=take["id"], picked_commit=picked_commit, closed_at=now())
        refresh_board(repo, state)
        return {"ok": True, "round": rnd["id"], "picked": take["id"], "trunk": trunk, "commit": picked_commit, "archived": archived}


def cmd_round_close(repo: Repo, args: argparse.Namespace) -> dict[str, Any]:
    with locked_state(repo) as state:
        rnd, _ = resolve(state, args.round)
        if rnd["status"] != "open":
            raise MBError(f"round {rnd['id']} is already {rnd['status']}")
        archived = archive_round(repo, rnd, picked=None)
        rnd.update(status="closed", closed_at=now())
        refresh_board(repo, state)
        return {"ok": True, "round": rnd["id"], "archived": archived}


def archive_round(repo: Repo, rnd: dict[str, Any], picked: str | None) -> list[dict[str, Any]]:
    """Tag every take, verify the tag, then remove its worktree and branch."""
    results = []
    for take in rnd["takes"].values():
        worktree = Path(take["worktree"])
        if worktree.exists():
            commit_take(worktree, rnd, take, f"take({rnd['id']}/{take['id']}): work in progress before archive")
        if not repo.ref_exists(take["branch"]):
            results.append({"take": take["id"], "skipped": "branch already gone"})
            continue
        tag = f"mb-archive/{rnd['id']}/{take['id']}"
        head = git("rev-parse", take["branch"], cwd=repo.cwd)
        if not repo.ref_exists(tag):
            git("tag", "-a", tag, head, "-m", f"{label(rnd, take)}: {rnd['question']}", cwd=repo.cwd)
        if git("rev-parse", tag + "^{commit}", cwd=repo.cwd) != head:
            raise MBError(f"archive tag {tag} does not match {take['branch']}; nothing was removed")
        if worktree.exists():
            git("worktree", "remove", "--force", str(worktree), cwd=repo.cwd)
        git("branch", "-D", take["branch"], cwd=repo.cwd)
        take.update(archive_tag=tag, status="picked" if take["id"] == picked else "archived")
        results.append({"take": take["id"], "tag": tag})
    git("worktree", "prune", cwd=repo.cwd)
    for round_dir in {Path(t["worktree"]).parent for t in rnd["takes"].values()}:
        with contextlib.suppress(OSError):
            round_dir.rmdir()  # only succeeds once every take folder is gone
    return results


def refresh_board(repo: Repo, state: dict[str, Any]) -> None:
    if (repo.state_dir / "board").exists():
        Board(repo, state).render()


def cmd_canvas(repo: Repo, args: argparse.Namespace) -> dict[str, Any]:
    with locked_state(repo) as state:
        board = Board(repo, state)
        if args.action == "stop":
            return {"ok": True, **board.stop()}
        if args.action == "render":
            return {"ok": True, "path": str(board.render())}
        return {"ok": True, **board.ensure()}


def cmd_views(repo: Repo, args: argparse.Namespace) -> dict[str, Any]:
    state = read_state(repo)
    if state["config"].get("preset") != "design-studio":
        raise MBError("views lists Design Studio views", hint="run `mb.py init --preset design-studio` in a Design Studio folder")
    if args.take:
        _, take = resolve_take(state, args.take)
        files, source = prototype_files(repo, worktree=Path(take["worktree"])), take["worktree"]
    else:
        ref = args.from_ref or state["config"]["trunk"]
        files, source = prototype_files(repo, ref=ref), ref
    views = design_studio_views(files)
    return {"ok": True, "source": source, "count": len(views), "views": views}


# ---------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mb.py", description="Keep every design take on its own git branch.")
    sub = p.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="set up or update micro-branch in this repo")
    init.add_argument("--trunk")
    init.add_argument("--name", help="board title (default: repo folder name)")
    init.add_argument("--build", help="build command run in each take ('' for none)")
    init.add_argument("--out", help="folder the build writes, relative to the take (default '.')")
    init.add_argument("--entry", help="entry file inside the output (default index.html)")
    init.add_argument("--setup", help="command run once in each new take, e.g. 'npm ci'")
    init.add_argument("--max-takes", type=int)
    init.add_argument("--frame-size", help="WIDTHxHEIGHT, e.g. 390x844")
    init.add_argument("--takes-dir")
    init.add_argument("--preset", choices=PRESETS, help="fill in build, output and setup for a known kind of project")
    init.add_argument("--root-paths", action=argparse.BooleanOptionalAction, default=None,
                      help="the build uses root paths like /assets/; the board serves each frame on its own origin")
    init.add_argument("--localize", help="comma-separated hosts whose assets are copied into each frame ('' for none)")
    init.add_argument("--localize-fonts", action="store_true", help="add the Google Fonts hosts to --localize")
    init.set_defaults(func=cmd_init)

    st = sub.add_parser("status", help="rounds, takes, branches and frames")
    st.add_argument("--round")
    st.set_defaults(func=cmd_status)

    rnd = sub.add_parser("round", help="start, branch or close rounds")
    rsub = rnd.add_subparsers(dest="round_command", required=True)
    rn = rsub.add_parser("new")
    rn.add_argument("slug")
    rn.add_argument("--question", required=True)
    rn.add_argument("--from", dest="from_ref", help="base commit or branch (default: trunk)")
    rx = rsub.add_parser("next", help="start a round from a take without merging it")
    rx.add_argument("take")
    rx.add_argument("slug")
    rx.add_argument("--question", required=True)
    for parser in (rn, rx):
        parser.add_argument("--entry", help="entry for this round's frames, e.g. 'index.html?variant=b'")
        parser.add_argument("--view", help="Design Studio view the frames open on, e.g. '<prototype>/<path>.tsx'")
    rn.set_defaults(func=cmd_round_new)
    rx.set_defaults(func=cmd_round_next)
    rc = rsub.add_parser("close", help="archive every take without picking one")
    rc.add_argument("round")
    rc.set_defaults(func=cmd_round_close)

    take = sub.add_parser("take", help="cut takes")
    tsub = take.add_subparsers(dest="take_command", required=True)
    tn = tsub.add_parser("new")
    tn.add_argument("round")
    tn.add_argument("slug")
    tn.add_argument("--note")
    tn.add_argument("--from", dest="from_take", help="branch from another take instead of the round base")
    tn.add_argument("--entry", help="entry for this take's frame (default: the round's)")
    tn.add_argument("--view", help="Design Studio view for this take's frame (default: the round's)")
    tn.set_defaults(func=cmd_take_new)

    pub = sub.add_parser("publish", help="commit, build, snapshot and lay a take out on the board")
    pub.add_argument("take")
    pub.add_argument("--message")
    pub.set_defaults(func=cmd_publish)

    op = sub.add_parser("open", help="print or restore a take's worktree")
    op.add_argument("take")
    op.set_defaults(func=cmd_open)

    pk = sub.add_parser("pick", help="merge a take into trunk and archive its round")
    pk.add_argument("take")
    pk.add_argument("--no-squash", action="store_true", help="keep the take's commits with a merge commit")
    pk.set_defaults(func=cmd_pick)

    cv = sub.add_parser("canvas", help="start the local board and print its URL")
    cv.add_argument("action", nargs="?", default="open", choices=["open", "stop", "render"],
                    help="open (default) starts or reuses the server; render only rewrites the page")
    cv.set_defaults(func=cmd_canvas)

    vw = sub.add_parser("views", help="list Design Studio views a round can open on")
    vw.add_argument("--from", dest="from_ref", help="commit or branch to list (default: trunk)")
    vw.add_argument("--take", help="list a take's files instead, including new views")
    vw.set_defaults(func=cmd_views)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["_board-serve"]:  # internal: the board's server process
        serve_board(argv[1], int(argv[2]))
        return 0
    args = build_parser().parse_args(argv)
    try:
        repo = Repo(Path.cwd())
        return emit(args.func(repo, args))
    except MBError as err:
        return emit({"ok": False, "error": str(err), "hint": err.hint, **err.extra}, code=2)


BOARD_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · takes</title><link rel="icon" href="data:,">
<style>
:root{{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6b6b66;--line:#dcdcd6;--card:#fff;--accent:#2f6fde;--bad:#c2410c}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--fg:#ececea;--muted:#9a9a94;--line:#33332f;--card:#1e1e1c;--accent:#7aa7ff;--bad:#fb923c}}}}
*{{box-sizing:border-box}}body{{margin:0;padding:24px 16px 48px;background:var(--bg);color:var(--fg);font:14px/1.45 ui-sans-serif,system-ui,sans-serif}}
h1{{font-size:20px;margin:0 0 4px}}h2{{font-size:16px;margin:32px 0 2px}}.meta,.updated{{color:var(--muted);margin:0 0 12px}}
.grid{{display:flex;flex-wrap:wrap;gap:16px}}.card{{width:{card}px;max-width:100%;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}}
.card header,.card footer{{display:flex;justify-content:space-between;gap:8px;align-items:center;padding:10px 12px}}
.card footer{{color:var(--muted);font-size:12px;border-top:1px solid var(--line)}}.card code{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.badge{{font-size:11px;border:1px solid var(--line);border-radius:99px;padding:1px 8px;color:var(--muted)}}
.picked{{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}}.picked .badge{{color:var(--accent);border-color:var(--accent)}}
.broken .badge{{color:var(--bad);border-color:var(--bad)}}.archived{{opacity:.7}}
.viewport{{position:relative;overflow:hidden;border-top:1px solid var(--line);background:#fff}}.viewport iframe{{border:0;transform-origin:0 0;position:absolute;inset:0 auto auto 0}}
.viewport.empty{{height:120px;display:grid;place-items:center;color:var(--muted);background:transparent}}
.note{{margin:0;padding:8px 12px 0;color:var(--muted)}}a{{color:var(--accent)}}
</style></head><body><h1>{title}</h1><p class="updated">Local board · updated {updated} · reload to refresh</p>{body}<script>for(const el of document.querySelectorAll("[data-frame-host]"))el.setAttribute(el.dataset.attr,location.protocol+"//"+el.dataset.frameHost+".localhost:"+location.port+"/"+el.dataset.entry)</script></body></html>
"""

if __name__ == "__main__":
    sys.exit(main())
