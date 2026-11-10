"""End-to-end tests for skills/design/micro-branch/scripts/mb.py on throwaway git repos."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "design" / "micro-branch"
MB = SKILL / "scripts" / "mb.py"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "mb test",
    "GIT_AUTHOR_EMAIL": "mb@example.invalid",
    "GIT_COMMITTER_NAME": "mb test",
    "GIT_COMMITTER_EMAIL": "mb@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}

FAKE_STUDIO_BUILD = textwrap.dedent(
    """
    import hashlib, json, pathlib
    def sid(text):
        return hashlib.sha1(text.encode()).hexdigest()[:16]
    dist = pathlib.Path("dist")
    (dist / "assets").mkdir(parents=True, exist_ok=True)
    protos = []
    for meta in sorted(pathlib.Path("src/prototypes").glob("*/*/meta.json")):
        folder, owner = meta.parent, meta.parent.parent.name
        items = []
        for f in sorted(folder.rglob("*.tsx")):
            rel = f.relative_to(folder)
            if not any(part.startswith("_") for part in rel.parts):
                items.append({"path": rel.as_posix(), "fileType": "view", "studioId": sid(folder.name + rel.as_posix())})
        (dist / "prototypes" / "artifacts" / owner).mkdir(parents=True, exist_ok=True)
        (dist / "prototypes" / "artifacts" / owner / (folder.name + ".json")).write_text(json.dumps(items))
        protos.append({"id": folder.name, "contributorKey": owner, "studioId": sid(folder.name)})
    (dist / "prototypes" / "manifest.json").write_text(json.dumps({"prototypes": protos}))
    (dist / "index.html").write_text(
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Demo&amp;display=swap">'
        '<script type="module" src="/assets/app.js"></script>')
    (dist / "assets" / "app.css").write_text("@font-face{src:url(https://fonts.gstatic.com/s/demo/a.woff2)}")
    (dist / "assets" / "app.js").write_text(
        'const c=`{"apiKey":"AIza' + "B" * 35 + '","authDomain":"x"}`;'
        "const k={OAI_API_KEY:`excalidraw-oai-api-key`};"
        'const f="https://fonts.gstatic.com/s/demo/a.woff2";const t=`https://fonts.gstatic.com/${f}`;')
    """
)


class Sandbox:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.repo = tmp / "proj"
        self.repo.mkdir()
        self.env = {**os.environ, **GIT_ENV}
        self.git("init", "-q", "-b", "main")
        self.write("index.html", "<h1>base</h1>\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")

    def git(self, *args: str, cwd: Path | None = None) -> str:
        return subprocess.run(["git", *args], cwd=cwd or self.repo, env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def write(self, rel: str, text: str, root: Path | None = None) -> None:
        path = (root or self.repo) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def mb(self, *args: str, expect: int = 0, env: dict | None = None) -> dict:
        proc = subprocess.run([sys.executable, str(MB), *args], cwd=self.repo, env={**self.env, **(env or {})},
                              capture_output=True, text=True)
        if proc.returncode != expect:
            raise AssertionError(f"mb {' '.join(args)} exited {proc.returncode}\n{proc.stdout}\n{proc.stderr}")
        return json.loads(proc.stdout)

    def state(self) -> dict:
        return json.loads((self.repo / ".git" / "micro-branch" / "state.json").read_text())


class MicroBranchTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.sb = Sandbox(Path(self._tmp.name).resolve())
        self.sb.mb("init", "--build", "mkdir -p dist && cp index.html dist/", "--out", "dist")

    def tearDown(self) -> None:
        self.sb.mb("canvas", "stop")
        self._tmp.cleanup()

    def cut(self, rnd: str, slug: str, html: str, **kw: str) -> dict:
        args = ["take", "new", rnd, slug] + [x for k, v in kw.items() for x in (f"--{k}", v)]
        take = self.sb.mb(*args)["take"]
        self.sb.write("index.html", html, root=Path(take["worktree"]))
        return take

    def test_round_takes_publish_and_board(self) -> None:
        rnd = self.sb.mb("round", "new", "view all", "--question", "How does view-all open?")["round"]
        self.assertEqual(rnd["id"], "r1-view-all")
        takes = [self.cut("r1", s, f"<h1>{s}</h1>\n") for s in ("modal sheet", "inline", "rail")]
        self.assertEqual([t["branch"] for t in takes], [
            "mb/r1-view-all/t1-modal-sheet", "mb/r1-view-all/t2-inline", "mb/r1-view-all/t3-rail"])
        for t in takes:
            self.assertTrue(Path(t["worktree"]).is_dir())
            out = self.sb.mb("publish", f"r1/{t['id']}")
            self.assertTrue(out["committed"])
        # trunk never changed while takes were cut
        self.assertEqual((self.sb.repo / "index.html").read_text(), "<h1>base</h1>\n")
        frames = self.sb.repo / ".git" / "micro-branch" / "frames" / "r1-view-all"
        self.assertEqual((frames / "t2-inline" / "index.html").read_text(), "<h1>inline</h1>\n")
        board = (self.sb.repo / ".git" / "micro-branch" / "board" / "index.html").read_text()
        for name in ("R1 · T1 modal sheet", "R1 · T2 inline", "R1 · T3 rail", "How does view-all open?"):
            self.assertIn(name, board)
        status = self.sb.mb("status")
        self.assertEqual({t["status"] for t in status["rounds"][0]["takes"].values()}, {"published"})
        self.assertEqual(self.sb.git("status", "--porcelain"), "")

    def test_take_cap(self) -> None:
        self.sb.mb("init", "--max-takes", "2")
        self.sb.mb("round", "new", "cap", "--question", "q")
        self.sb.mb("take", "new", "r1", "a")
        self.sb.mb("take", "new", "r1", "b")
        err = self.sb.mb("take", "new", "r1", "c", expect=2)
        self.assertFalse(err["ok"])
        self.assertIn("limit 2", err["error"])

    def test_failed_build_publishes_nothing(self) -> None:
        self.sb.mb("init", "--build", "exit 3")
        self.sb.mb("round", "new", "broken", "--question", "q")
        take = self.cut("r1", "boom", "<h1>boom</h1>\n")
        err = self.sb.mb("publish", "r1/t1", expect=2)
        self.assertIn("nothing was published", err["error"])
        self.assertEqual(self.sb.state()["rounds"]["r1-broken"]["takes"]["t1-boom"]["status"], "broken")
        self.assertFalse((self.sb.repo / ".git" / "micro-branch" / "frames" / "r1-broken" / take["id"]).exists())

    def test_pick_squashes_archives_and_restores(self) -> None:
        self.sb.mb("round", "new", "hero", "--question", "Which hero?")
        t1 = self.cut("r1", "big", "<h1>big</h1>\n")
        t2 = self.cut("r1", "small", "<h1>small</h1>\n")
        self.sb.mb("publish", "r1/t1")
        self.sb.mb("publish", "r1/t2")
        out = self.sb.mb("pick", "r1/t2")
        self.assertEqual(out["picked"], "t2-small")
        self.assertEqual((self.sb.repo / "index.html").read_text(), "<h1>small</h1>\n")
        log = self.sb.git("log", "-1", "--format=%B")
        self.assertIn("pick(r1-hero): t2-small", log)
        self.assertIn("Picked t2-small over t1-big.", log)
        tags = self.sb.git("tag", "--list", "mb-archive/*").splitlines()
        self.assertEqual(sorted(tags), ["mb-archive/r1-hero/t1-big", "mb-archive/r1-hero/t2-small"])
        self.assertEqual(self.sb.git("branch", "--list", "mb/*"), "")
        self.assertFalse(Path(t1["worktree"]).exists() or Path(t2["worktree"]).exists())
        state = self.sb.state()["rounds"]["r1-hero"]
        self.assertEqual(state["status"], "picked")
        self.assertEqual(state["takes"]["t1-big"]["status"], "archived")
        # an archived take comes back with its work intact
        opened = self.sb.mb("open", "r1/t1")
        self.assertTrue(opened["restored"])
        self.assertEqual((Path(opened["worktree"]) / "index.html").read_text(), "<h1>big</h1>\n")
        # a picked round takes no new takes
        self.assertIn("picked", self.sb.mb("take", "new", "r1", "late", expect=2)["error"])

    def test_pick_refuses_dirty_trunk_and_conflicts(self) -> None:
        self.sb.mb("round", "new", "copy", "--question", "q")
        self.cut("r1", "a", "<h1>a</h1>\n")
        self.sb.mb("publish", "r1/t1")
        self.sb.write("index.html", "<h1>dirty</h1>\n")
        self.assertIn("uncommitted", self.sb.mb("pick", "r1/t1", expect=2)["error"])
        self.sb.git("commit", "-qam", "trunk moved")
        err = self.sb.mb("pick", "r1/t1", expect=2)
        self.assertIn("does not merge cleanly", err["error"])
        self.assertEqual((self.sb.repo / "index.html").read_text(), "<h1>dirty</h1>\n")
        self.assertEqual(self.sb.git("status", "--porcelain"), "")
        self.assertEqual(self.sb.state()["rounds"]["r1-copy"]["status"], "open")

    def test_next_round_and_take_from_take(self) -> None:
        self.sb.mb("round", "new", "layout", "--question", "Layout?")
        self.cut("r1", "grid", "<h1>grid</h1>\n")
        self.sb.mb("publish", "r1/t1")
        t2 = self.sb.mb("take", "new", "r1", "grid tighter", "--from", "t1")["take"]
        self.assertEqual((Path(t2["worktree"]) / "index.html").read_text(), "<h1>grid</h1>\n")
        self.assertEqual(t2["from_take"], "t1-grid")
        self.assertIn("names a round", self.sb.mb("take", "new", "r1", "x", "--from", "r1", expect=2)["error"])
        r2 = self.sb.mb("round", "next", "r1/t1", "type", "--question", "Type scale?")["round"]
        self.assertEqual(r2["built_on"], "r1-layout/t1-grid")
        t = self.sb.mb("take", "new", "r2", "serif")["take"]
        self.assertEqual((Path(t["worktree"]) / "index.html").read_text(), "<h1>grid</h1>\n")
        closed = self.sb.mb("round", "close", "r1")
        self.assertEqual(len(closed["archived"]), 2)
        self.assertEqual((self.sb.repo / "index.html").read_text(), "<h1>base</h1>\n")

    def test_setup_runs_in_each_take_with_main_checkout_in_env(self) -> None:
        self.sb.mb("init", "--setup", 'printf "%s|%s" "$MB_MAIN" "$MB_ROUND" > .mb-main')
        self.sb.mb("round", "new", "deps", "--question", "q")
        take = self.sb.mb("take", "new", "r1", "a")
        self.assertEqual(take["setup"]["ok"], True)
        self.assertEqual((Path(take["take"]["worktree"]) / ".mb-main").read_text(), f"{self.sb.repo}|r1-deps")

    def test_board_server_starts_and_stops(self) -> None:
        out = self.sb.mb("canvas", "open")
        self.assertTrue(out["url"].startswith("http://127.0.0.1:"))
        again = self.sb.mb("canvas", "open")
        self.assertFalse(again["started"])
        self.assertTrue(self.sb.mb("canvas", "stop")["stopped"])

    def test_round_entry_with_query_reaches_frame_and_board(self) -> None:
        self.sb.mb("round", "new", "variant", "--question", "q", "--entry", "index.html?variant=b")
        self.cut("r1", "a", "<h1>a</h1>\n")
        out = self.sb.mb("publish", "r1/t1")
        self.assertEqual(out["frame"]["entry"], "index.html?variant=b")
        board = (self.sb.repo / ".git" / "micro-branch" / "board" / "index.html").read_text()
        self.assertIn('src="../frames/r1-variant/t1-a/index.html?variant=b"', board)

    def test_view_needs_the_design_studio_preset(self) -> None:
        self.assertIn("design-studio preset", self.sb.mb("round", "new", "x", "--question", "q", "--view", "a", expect=2)["error"])
        self.sb.mb("round", "new", "x", "--question", "q")
        self.assertIn("design-studio preset", self.sb.mb("take", "new", "r1", "a", "--view", "a", expect=2)["error"])
        self.assertEqual(self.sb.git("branch", "--list", "mb/*"), "")
        self.assertIn("studio.config.json", self.sb.mb("init", "--preset", "design-studio", expect=2)["error"])

    def test_setup_symlinks_never_land_in_take_commits(self) -> None:
        self.sb.mb("init", "--setup", 'ln -s "$MB_MAIN" linked-deps')
        self.sb.mb("round", "new", "deps", "--question", "q")
        take = self.cut("r1", "a", "<h1>a</h1>\n")
        tree = Path(take["worktree"])
        self.assertTrue((tree / "linked-deps").is_symlink())
        self.sb.mb("publish", "r1/t1")
        self.assertNotIn("linked-deps", self.sb.git("ls-tree", "-r", "--name-only", "HEAD", cwd=tree).splitlines())
        self.assertNotIn("linked-deps", self.sb.git("status", "--porcelain", cwd=tree))
        self.assertIn("/linked-deps", (self.sb.repo / ".git" / "info" / "exclude").read_text())

    def test_publish_starts_the_board_and_returns_its_url(self) -> None:
        self.sb.mb("round", "new", "hero", "--question", "q")
        self.cut("r1", "a", "<h1>a</h1>\n")
        out = self.sb.mb("publish", "r1/t1")
        self.assertTrue(out["board"].startswith("http://127.0.0.1:"))
        with urllib.request.urlopen(out["board"], timeout=5) as resp:
            self.assertIn("R1 · T1 a", resp.read().decode())
        self.assertTrue(self.sb.mb("canvas", "render")["path"].endswith("board/index.html"))
        self.assertIn("unrecognized arguments", subprocess.run(
            [sys.executable, str(MB), "publish", "r1/t1", "--canvas", "board"], cwd=self.sb.repo,
            env=self.sb.env, capture_output=True, text=True).stderr)

    def test_state_from_an_older_version_drops_its_canvas_settings(self) -> None:
        path = self.sb.repo / ".git" / "micro-branch" / "state.json"
        state = json.loads(path.read_text())
        state["config"].update(canvas="twombly", twombly_version="0.4.10", twombly_port=4848, scrub=["x"])
        state["canvas"] = {"twombly": {"initialized": True, "port": 4848}}
        path.write_text(json.dumps(state))
        status = self.sb.mb("status")
        for key in ("canvas", "twombly_version", "twombly_port", "scrub"):
            self.assertNotIn(key, status["config"])
        self.assertEqual(status["canvas"], {})
        self.sb.mb("round", "new", "after upgrade", "--question", "q")
        self.cut("r1", "a", "<h1>a</h1>\n")
        self.assertTrue(self.sb.mb("publish", "r1/t1")["ok"])
        self.assertNotIn("twombly", json.dumps(self.sb.state()["config"]))

    def test_outside_git_repo_fails_cleanly(self) -> None:
        proc = subprocess.run([sys.executable, str(MB), "status"], cwd=self.sb.tmp, capture_output=True, text=True,
                              env={**os.environ, **GIT_ENV})
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not inside a git work tree", json.loads(proc.stdout)["error"])


class DesignStudioPresetTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.sb = sb = Sandbox(Path(self._tmp.name).resolve())
        sb.write(".gitignore", "node_modules/\ndist/\n")
        sb.write("studio.config.json", '{"name": "Studio"}\n')
        sb.write("build.py", FAKE_STUDIO_BUILD)
        sb.write("src/systems/demo/package.json", "{}\n")
        for proto, files in {"me/shop": ["Screens/home.tsx", "Screens/cart.tsx", "_parts/button.tsx"],
                             "you/blog": ["Screens/home.tsx"]}.items():
            sb.write(f"src/prototypes/{proto}/meta.json", "{}\n")
            for rel in files:
                sb.write(f"src/prototypes/{proto}/{rel}", "export default () => null\n")
        (sb.repo / "node_modules").mkdir()
        (sb.repo / "src" / "systems" / "demo" / "node_modules").mkdir()
        sb.git("add", "-A")
        sb.git("commit", "-q", "-m", "studio")
        self.init = sb.mb("init", "--preset", "design-studio", "--build", "python3 build.py",
                          "--localize-fonts")

    def tearDown(self) -> None:
        self.sb.mb("canvas", "stop")
        self._tmp.cleanup()

    def cache(self, url: str, data: bytes, kind: str) -> str:
        folder = self.sb.repo / ".git" / "micro-branch" / "cache" / "remote"
        folder.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(url.encode()).hexdigest()
        (folder / f"{key}.bin").write_bytes(data)
        (folder / f"{key}.json").write_text(json.dumps({"type": kind}))
        return key[:16]

    def test_preset_views_frame_entry_and_snapshot(self) -> None:
        cfg = self.init["config"]
        self.assertEqual((cfg["preset"], cfg["out"], cfg["root_paths"]), ("design-studio", "dist", True))
        self.assertEqual(cfg["localize"], ["fonts.googleapis.com", "fonts.gstatic.com"])
        views = [v["view"] for v in self.sb.mb("views")["views"]]
        self.assertEqual(views, ["shop/Screens/cart.tsx", "shop/Screens/home.tsx", "blog/Screens/home.tsx"])
        vague = self.sb.mb("round", "new", "hero", "--question", "q", "--view", "Screens/home")
        self.assertIn("matches 2 views", vague["warning"])
        self.sb.mb("round", "new", "cart", "--question", "Which cart?", "--view", "shop/Screens/cart")
        take = self.sb.mb("take", "new", "r2", "dense")
        tree = Path(take["take"]["worktree"])
        self.assertEqual(sorted(take["setup"]["ignored_links"]), ["node_modules", "src/systems/demo/node_modules"])
        self.assertEqual(self.sb.git("status", "--porcelain", cwd=tree), "")
        woff_a = self.cache("https://fonts.gstatic.com/s/demo/a.woff2", b"wOF2-a", "font/woff2")
        woff_b = self.cache("https://fonts.gstatic.com/s/demo/b.woff2", b"wOF2-b", "font/woff2")
        sheet = self.cache("https://fonts.googleapis.com/css2?family=Demo&display=swap",
                           b"@font-face{src:url(https://fonts.gstatic.com/s/demo/b.woff2) format('woff2')}", "text/css")
        out = self.sb.mb("publish", "r2/t1")
        entry = out["frame"]["entry"]
        self.assertTrue(entry.startswith("index.html?studio-preview=1&session=micro-branch&config="))
        config = json.loads(urllib.parse.parse_qs(urllib.parse.urlsplit(entry).query)["config"][0])
        self.assertEqual(config["target"]["prototype"], "shop")
        self.assertEqual(config["target"]["artifact"], "Screens/cart.tsx")
        self.assertEqual(config["href"], f"/prototypes/{config['target']['prototypeId']}/artifacts/{config['target']['artifactId']}")
        self.assertEqual((config["surface"], config["dark"]), ("page", False))
        self.assertEqual(out["frame"]["view"], "shop/Screens/cart.tsx")
        snap = self.sb.repo / ".git" / "micro-branch" / "frames" / "r2-cart" / "t1-dense"
        js = (snap / "assets" / "app.js").read_text()
        self.assertIn('"apiKey":"AIza', js)  # bundled strings are left as they are
        self.assertIn(f'"/mb-assets/{woff_a}.woff2"', js)
        self.assertIn("`https://fonts.gstatic.com/${f}`", js)  # template literals stay as they are
        self.assertIn(f"url(../mb-assets/{woff_a}.woff2)", (snap / "assets" / "app.css").read_text())
        self.assertIn(f'href="/mb-assets/{sheet}.css"', (snap / "index.html").read_text())
        self.assertIn(f"url({woff_b}.woff2)", (snap / "mb-assets" / f"{sheet}.css").read_text())
        self.assertEqual((snap / "mb-assets" / f"{woff_b}.woff2").read_bytes(), b"wOF2-b")
        self.assertEqual(out["prepared"]["localized"]["assets"], 3)
        self.assertEqual(set(out["prepared"]), {"localized"})
        self.assertNotIn("node_modules", self.sb.git("ls-tree", "-r", "--name-only", "HEAD", cwd=tree))

    def test_unknown_view_fails_publish_and_board_serves_frames_on_their_own_origin(self) -> None:
        self.sb.mb("round", "new", "cart", "--question", "q", "--view", "shop/Screens/cart.tsx")
        self.sb.mb("take", "new", "r1", "a")
        missing = self.sb.mb("take", "new", "r1", "b", "--view", "shop/Screens/nope.tsx")
        self.assertIn("no view matches", missing["warning"])
        self.cache("https://fonts.gstatic.com/s/demo/a.woff2", b"a", "font/woff2")
        self.cache("https://fonts.gstatic.com/s/demo/b.woff2", b"b", "font/woff2")
        self.cache("https://fonts.googleapis.com/css2?family=Demo&display=swap", b"", "text/css")
        self.assertIn("no view matches", self.sb.mb("publish", "r1/t2", expect=2)["error"])
        self.sb.mb("publish", "r1/t1")
        board = self.sb.mb("canvas", "open")
        port = urllib.parse.urlsplit(board["url"]).port
        page = (self.sb.repo / ".git" / "micro-branch" / "board" / "index.html").read_text()
        self.assertIn('data-frame-host="r1-t1"', page)
        request = urllib.request.Request(f"http://127.0.0.1:{port}/assets/app.css", headers={"Host": f"r1-t1.localhost:{port}"})
        with urllib.request.urlopen(request, timeout=5) as resp:
            self.assertIn("mb-assets", resp.read().decode())
        with urllib.request.urlopen(board["url"], timeout=5) as resp:
            self.assertIn("R1 · T1 a", resp.read().decode())


class MicroBranchPortabilityTest(unittest.TestCase):
    def test_no_skill_mentions_twombly(self) -> None:
        """Twombly is a paid third-party product and was taken out of Stack on 2026-11-10."""
        banned = re.compile(r"twombly", re.IGNORECASE)
        for path in (ROOT / "skills").rglob("*"):
            if path.is_file():
                text = path.read_text(errors="ignore")
                self.assertIsNone(banned.search(text) or banned.search(path.name),
                                  f"{path.relative_to(ROOT)} mentions Twombly")

    def test_skill_names_no_employer_or_private_system(self) -> None:
        banned = re.compile(r"change\.org|sunrise|corgi|@change/|change-prototypes", re.IGNORECASE)
        for path in SKILL.rglob("*"):
            if path.is_file():
                hits = banned.findall(path.read_text(errors="ignore"))
                self.assertEqual(hits, [], f"{path.relative_to(ROOT)} mentions {hits}")


if __name__ == "__main__":
    unittest.main()
