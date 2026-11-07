#!/usr/bin/env python3
"""micro-branch: keep every design take on its own git branch.

A round is one design question. A take is one answer to it, on its own branch
and worktree, so takes never overwrite each other. Publishing a take builds it,
snapshots the output and places it on a canvas. Picking a take squash-merges it
into trunk and archives the round's takes as tags.

Every command prints JSON. State lives in <git-common-dir>/micro-branch/, so it
is shared by every worktree and never leaves the machine. Nothing here pushes,
shares a canvas, or deletes a take without tagging it first.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import html
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
import urllib.request
from pathlib import Path
from typing import Any, Iterator

STATE_VERSION = 1
TWOMBLY_VERSION = "0.4.10"
DEFAULT_MAX_TAKES = 4
MAX_TAKES_CEILING = 8
BOARD_PORT = 4780
TWOMBLY_PORT = 4848  # Twombly's own default (4747) is often taken by other local tools
TWOMBLY_ENV = {
    "TWOMBLY_NO_USAGE": "1",
    "TWOMBLY_NO_UPDATE_CHECK": "1",
    "TWOMBLY_NO_INTERFACE_UPDATES": "1",
    "TWOMBLY_NO_OPEN": "1",
}
TWOMBLY_BLOCKED = {"share", "unshare", "join", "login", "logout"}
# Never copied into a frame: repo internals, dependencies, secrets and files Twombly's gates reject.
FRAME_IGNORE = (
    ".git", "node_modules", ".micro-branch", ".twombly", ".DS_Store", ".env*", "*.map",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb", "tsconfig*.json",
)

DEFAULT_CONFIG: dict[str, Any] = {
    "trunk": None,
    "name": None,
    "build": None,
    "out": ".",
    "entry": "index.html",
    "setup": None,
    "canvas": "twombly",
    "max_takes": DEFAULT_MAX_TAKES,
    "frame_width": 1280,
    "frame_height": 800,
    "twombly_version": TWOMBLY_VERSION,
    "twombly_port": TWOMBLY_PORT,
    "takes_dir": None,
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
    merged = dict(DEFAULT_CONFIG)
    merged.update(state.get("config", {}))
    state["config"] = merged
    return state


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


# ---------------------------------------------------------------- canvas adapters


class BoardAdapter:
    """A zero-dependency local page that shows every frame side by side."""

    name = "board"

    def __init__(self, repo: Repo, state: dict[str, Any]) -> None:
        self.repo, self.state = repo, state
        self.root = repo.state_dir

    def publish(self, rnd: dict[str, Any], take: dict[str, Any], snapshot: Path) -> dict[str, Any]:
        return {"adapter": self.name, "path": str(snapshot.relative_to(self.root))}

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
                    f'<iframe loading="lazy" src="../{html.escape(src)}/{html.escape(cfg["entry"])}" '
                    f'style="width:{width}px;height:{height}px;transform:scale({scale:.4f})" '
                    f'title="{html.escape(label(rnd, take))}"></iframe></div>'
                    if src
                    else '<div class="viewport empty">not published yet</div>'
                )
                link = f'<a href="../{html.escape(src)}/{html.escape(cfg["entry"])}" target="_blank">open</a>' if src else ""
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
            return {"adapter": self.name, "url": f"http://127.0.0.1:{port}/board/", "pid": pid, "started": False}
        port = free_port(BOARD_PORT)
        log = open(self.root / "board.log", "a")
        proc = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(self.root)],
            stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True,
        )
        for _ in range(50):
            if port_open(port):
                break
            time.sleep(0.1)
        self.state["canvas"]["board"] = {"pid": proc.pid, "port": port}
        return {"adapter": self.name, "url": f"http://127.0.0.1:{port}/board/", "pid": proc.pid, "started": True}

    def stop(self) -> dict[str, Any]:
        info = self.state["canvas"].pop("board", None) or {}
        if info.get("pid") and pid_alive(info["pid"]):
            os.kill(info["pid"], signal.SIGTERM)
            return {"adapter": self.name, "stopped": True}
        return {"adapter": self.name, "stopped": False}

    def feedback(self) -> dict[str, Any]:
        return {"adapter": self.name, "supported": False, "hint": "the board has no comments; ask the person in chat"}


class TwomblyAdapter:
    """Drives the Twombly CLI at a pinned version, on localhost only.

    Every call sets a fixed port and turns off Twombly's usage pings, update
    checks and remote interface updates. Commands that sign in or share are
    refused. The `update` nudge in Twombly's replies is dropped on purpose: the
    version stays pinned until Stack moves it.
    """

    name = "twombly"

    def __init__(self, repo: Repo, state: dict[str, Any]) -> None:
        self.repo, self.state = repo, state
        self.cwd = repo.state_dir / "twombly"
        self.info = state["canvas"].setdefault("twombly", {})

    def cmd(self) -> list[str]:
        override = os.environ.get("MB_TWOMBLY_CMD")
        if override:
            return shlex.split(override)
        return ["npx", "-y", f"twombly@{self.state['config']['twombly_version']}"]

    def port(self) -> int:
        start = int(self.info.get("port") or self.state["config"].get("twombly_port") or TWOMBLY_PORT)
        for candidate in range(start, start + 20):
            health = twombly_health(candidate)
            if health is not None or not port_open(candidate):
                self.info["port"] = candidate
                if health:
                    self.info["daemon"] = health.get("build")
                return candidate
        raise MBError(f"ports {start} to {start + 19} are all taken by something other than Twombly",
                      hint="pass a free port with `mb.py init --twombly-port <port>`")

    def call(self, *args: str, allow_fail: bool = False) -> Any:
        if args and args[0] in TWOMBLY_BLOCKED:
            raise MBError(f"micro-branch never runs `twombly {args[0]}`",
                          hint="signing in and sharing are the person's call; they use the Twombly window themselves")
        self.cwd.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, **TWOMBLY_ENV, TWOMBLY_PORT=str(self.port()))
        proc = subprocess.run([*self.cmd(), *args], cwd=self.cwd, env=env, text=True, capture_output=True)
        data = parse_json(proc.stdout)
        if isinstance(data, dict):
            data.pop("update", None)
        if proc.returncode != 0 and not (allow_fail and isinstance(data, dict)):
            problems = data.get("problems") if isinstance(data, dict) else None
            raise MBError(
                f"twombly {args[0] if args else ''} failed",
                hint="check `node --version` (Twombly needs Node 22+) and npm access for the first download; "
                     "or switch with `mb.py init --canvas board`",
                problems=problems, stderr=proc.stderr.strip()[-2000:], stdout=proc.stdout.strip()[-2000:],
            )
        return data

    def ensure(self) -> dict[str, Any]:
        """Create the canvas on first use; afterwards just report where it is."""
        if not self.info.get("initialized"):
            name = self.state["config"].get("name") or Path(self.repo.main_worktree).name
            result = self.call("init", "--no-open", "--name", name) or {}
            self.info.update(initialized=True, name=name, id=result.get("id"), url=result.get("local"))
        else:
            result = self.call("list") or {}
            if isinstance(result, dict) and result.get("local"):
                self.info["url"] = result["local"]
        return {"adapter": self.name, "url": self.info.get("url"), "name": self.info.get("name"),
                "port": self.info.get("port"), "daemon": self.info.get("daemon")}

    def publish(self, rnd: dict[str, Any], take: dict[str, Any], snapshot: Path) -> dict[str, Any]:
        if not self.info.get("initialized"):
            self.ensure()
        cfg = self.state["config"]
        flags = ["--title", label(rnd, take), "--width", str(cfg["frame_width"]),
                 "--height", str(cfg["frame_height"]), "--entry", cfg["entry"]]
        frame_id = ((take.get("frame") or {}).get("twombly") or {}).get("id")
        result = self.call("update", frame_id, str(snapshot), *flags, allow_fail=True) if frame_id else None
        if result is None or (not result.get("ok") and not result.get("problems")):
            result = self.call("add", str(snapshot), *flags, allow_fail=True)
        if not result.get("ok") or result.get("placed") is False:
            raise MBError(
                "Twombly did not place the frame",
                hint="fix each problem (see references/twombly.md), then publish again; the local board still shows this take",
                problems=result.get("problems") or result.get("error"), warnings=result.get("warnings"),
            )
        frame = result.get("frame") or {}
        url = (result.get("canvas") or {}).get("local") or self.info.get("url")
        self.info["url"] = url
        return {
            "adapter": self.name, "path": str(snapshot.relative_to(self.repo.state_dir)), "url": url,
            "twombly": {"id": frame.get("id") or frame_id, "title": frame.get("title")},
            "screenshot": result.get("screenshot"), "warnings": result.get("warnings") or [],
        }

    def stop(self) -> dict[str, Any]:
        result = self.call("stop", allow_fail=True)
        return {"adapter": self.name, "stopped": bool(isinstance(result, dict) and result.get("ok")),
                "note": "this stops Twombly's local server for every canvas on the machine"}

    def feedback(self) -> dict[str, Any]:
        if not self.info.get("initialized"):
            self.ensure()
        by_frame = {
            ((t.get("frame") or {}).get("twombly") or {}).get("id"): f"{r['id']}/{t['id']}"
            for r in self.state["rounds"].values() for t in r["takes"].values()
        }
        by_frame.pop(None, None)
        context = self.call("context") or {}
        threads = (self.call("comments") or {}).get("comments", [])
        for thread in threads:
            thread["take"] = by_frame.get((thread.get("frame") or {}).get("id"))
        viewing = [by_frame.get(f.get("id")) for f in (context.get("frames") or []) if isinstance(f, dict)]
        return {"adapter": self.name, "supported": True, "looking": context.get("looking"), "via": context.get("via"),
                "viewing_takes": [v for v in viewing if v], "comments": threads, "takes_by_frame": by_frame}


def twombly_health(port: int) -> dict[str, Any] | None:
    """Return Twombly's /health reply when Twombly owns the port, else None."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as resp:
            data = json.loads(resp.read().decode() or "{}")
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and str(data.get("build", "")).count("+") == 1 and "api" in data else None


ADAPTERS = {"board": BoardAdapter, "twombly": TwomblyAdapter}


def adapter_for(repo: Repo, state: dict[str, Any], name: str | None = None):
    name = name or state["config"]["canvas"]
    if name not in ADAPTERS:
        raise MBError(f"unknown canvas '{name}'", hint=f"choose one of: {', '.join(ADAPTERS)}")
    return ADAPTERS[name](repo, state)


def parse_json(text: str) -> Any:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for line in reversed(text.splitlines()):
            with contextlib.suppress(json.JSONDecodeError):
                return json.loads(line)
        return {"raw": text[-2000:]}


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


# ---------------------------------------------------------------- commands


def cmd_init(repo: Repo, args: argparse.Namespace) -> dict[str, Any]:
    with locked_state(repo, create=True) as state:
        cfg = state["config"]
        if args.trunk or not cfg.get("trunk"):
            trunk = args.trunk or git("branch", "--show-current", cwd=repo.main_worktree)
            if not trunk:
                raise MBError("the main checkout is on a detached HEAD", hint="pass --trunk <branch>")
            cfg["trunk"] = trunk
        for key in ("name", "build", "out", "entry", "setup", "canvas", "twombly_version", "takes_dir", "twombly_port"):
            value = getattr(args, key, None)
            if value is not None:
                cfg[key] = None if value == "" else value
        if args.max_takes is not None:
            if not 1 <= args.max_takes <= MAX_TAKES_CEILING:
                raise MBError(f"--max-takes must be between 1 and {MAX_TAKES_CEILING}")
            cfg["max_takes"] = args.max_takes
        if args.frame_size:
            w, _, h = args.frame_size.partition("x")
            cfg["frame_width"], cfg["frame_height"] = int(w), int(h)
        if cfg["canvas"] not in ADAPTERS:
            raise MBError(f"unknown canvas '{cfg['canvas']}'", hint=f"choose one of: {', '.join(ADAPTERS)}")
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
        rnd = add_round(state, args.slug, args.question, git("rev-parse", base_ref, cwd=repo.cwd), base_ref, None)
        return {"ok": True, "round": rnd}


def add_round(state: dict[str, Any], slug: str, question: str, base: str, base_ref: str, built_on: str | None) -> dict[str, Any]:
    n = len(state["rounds"]) + 1
    rid = f"r{n}-{slugify(slug)}"
    rnd = {
        "id": rid, "n": n, "slug": slugify(slug), "question": question, "base": base, "base_ref": base_ref,
        "built_on": built_on, "status": "open", "picked": None, "created_at": now(), "takes": {},
    }
    state["rounds"][rid] = rnd
    return rnd


def cmd_round_next(repo: Repo, args: argparse.Namespace) -> dict[str, Any]:
    with locked_state(repo) as state:
        src_round, take = resolve_take(state, args.take)
        ref = take_ref(repo, take)
        rnd = add_round(state, args.slug, args.question, git("rev-parse", ref, cwd=repo.cwd), ref, f"{src_round['id']}/{take['id']}")
        return {"ok": True, "round": rnd}


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
            "archive_tag": None, "created_at": now(),
        }
        rnd["takes"][tid] = take
    setup = run_setup(cfg.get("setup"), take, take_env(repo, rnd, take))
    return {"ok": True, "round": rnd["id"], "take": take, "label": label(rnd, take), "setup": setup}


def take_env(repo: Repo, rnd: dict[str, Any], take: dict[str, Any]) -> dict[str, str]:
    """Environment for setup and build commands, as documented in setup-recipes.md."""
    return dict(os.environ, MB_ROUND=rnd["id"], MB_TAKE=take["id"], MB_WORKTREE=take["worktree"],
                MB_MAIN=str(repo.main_worktree))


def run_setup(cmd: str | None, take: dict[str, Any], env: dict[str, str]) -> dict[str, Any] | None:
    if not cmd:
        return None
    proc = subprocess.run(cmd, shell=True, cwd=take["worktree"], text=True, capture_output=True, env=env)
    if proc.returncode != 0:
        raise MBError(f"setup failed in {take['worktree']}", hint="fix the setup command with `mb.py init --setup`",
                      stderr=proc.stderr.strip()[-2000:])
    return {"command": cmd, "ok": True}


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
    if not (out_dir / cfg["entry"]).exists():
        raise MBError(f"'{cfg['entry']}' is missing from the build output", hint="set the entry file with `mb.py init --entry`")
    snapshot = repo.state_dir / "frames" / rnd["id"] / take["id"]
    if snapshot.exists():
        shutil.rmtree(snapshot)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(out_dir, snapshot, ignore=shutil.ignore_patterns(*FRAME_IGNORE))
    failure: MBError | None = None
    with locked_state(repo) as fresh:
        f_rnd = fresh["rounds"][rnd["id"]]
        stored = f_rnd["takes"][take["id"]]
        try:
            frame = adapter_for(repo, fresh, args.canvas).publish(f_rnd, stored, snapshot)
            status = "published"
        except MBError as err:
            failure, status = err, "rejected"
            frame = {**(stored.get("frame") or {}), "adapter": "board", "path": str(snapshot.relative_to(repo.state_dir))}
        frame.update(published_at=now(), commit=commit)
        stored.update(status=status, commit=commit, frame=frame)
        BoardAdapter(repo, fresh).render()  # the local board mirrors every canvas
    if failure:
        raise failure
    return {"ok": True, "label": label(rnd, take), "committed": committed, "commit": commit, "frame": frame}


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
        BoardAdapter(repo, state).render()


def cmd_canvas(repo: Repo, args: argparse.Namespace) -> dict[str, Any]:
    with locked_state(repo) as state:
        adapter = adapter_for(repo, state, args.canvas)
        if args.action == "stop":
            return {"ok": True, **adapter.stop()}
        if args.action == "board":
            return {"ok": True, "path": str(BoardAdapter(repo, state).render())}
        return {"ok": True, **adapter.ensure()}


def cmd_feedback(repo: Repo, args: argparse.Namespace) -> dict[str, Any]:
    with locked_state(repo) as state:
        result = adapter_for(repo, state, args.canvas).feedback()
        labels = {
            label(rnd, take): f"{rnd['id']}/{take['id']}"
            for rnd in state["rounds"].values() for take in rnd["takes"].values()
        }
        return {"ok": True, "takes_by_label": labels, **result}


# ---------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mb.py", description="Keep every design take on its own git branch.")
    sub = p.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="set up or update micro-branch in this repo")
    init.add_argument("--trunk")
    init.add_argument("--name", help="canvas name (default: repo folder name)")
    init.add_argument("--build", help="build command run in each take ('' for none)")
    init.add_argument("--out", help="folder the build writes, relative to the take (default '.')")
    init.add_argument("--entry", help="entry file inside the output (default index.html)")
    init.add_argument("--setup", help="command run once in each new take, e.g. 'npm ci'")
    init.add_argument("--canvas", choices=sorted(ADAPTERS))
    init.add_argument("--max-takes", type=int)
    init.add_argument("--frame-size", help="WIDTHxHEIGHT, e.g. 390x844")
    init.add_argument("--twombly-version")
    init.add_argument("--twombly-port", type=int, help="local port for Twombly (default 4848)")
    init.add_argument("--takes-dir")
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
    rn.set_defaults(func=cmd_round_new)
    rx = rsub.add_parser("next", help="start a round from a take without merging it")
    rx.add_argument("take")
    rx.add_argument("slug")
    rx.add_argument("--question", required=True)
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
    tn.set_defaults(func=cmd_take_new)

    pub = sub.add_parser("publish", help="commit, build, snapshot and place a take on the canvas")
    pub.add_argument("take")
    pub.add_argument("--message")
    pub.add_argument("--canvas", choices=sorted(ADAPTERS))
    pub.set_defaults(func=cmd_publish)

    op = sub.add_parser("open", help="print or restore a take's worktree")
    op.add_argument("take")
    op.set_defaults(func=cmd_open)

    pk = sub.add_parser("pick", help="merge a take into trunk and archive its round")
    pk.add_argument("take")
    pk.add_argument("--no-squash", action="store_true", help="keep the take's commits with a merge commit")
    pk.set_defaults(func=cmd_pick)

    cv = sub.add_parser("canvas", help="start the canvas and print its URL")
    cv.add_argument("action", nargs="?", default="open", choices=["open", "stop", "board"])
    cv.add_argument("--canvas", choices=sorted(ADAPTERS))
    cv.set_defaults(func=cmd_canvas)

    fb = sub.add_parser("feedback", help="what the person is looking at and their comments")
    fb.add_argument("--canvas", choices=sorted(ADAPTERS))
    fb.set_defaults(func=cmd_feedback)
    return p


def main(argv: list[str] | None = None) -> int:
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
</style></head><body><h1>{title}</h1><p class="updated">Local board · updated {updated} · reload to refresh</p>{body}</body></html>
"""

if __name__ == "__main__":
    sys.exit(main())
