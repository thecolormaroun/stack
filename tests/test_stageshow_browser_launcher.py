"""Exercise the imported launcher with a fake Playwright module; no browser runs."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BROWSER = ROOT / "skills/imported/benjitaylor/stageshow/scripts/browser.mjs"
NODE = shutil.which("node")
HARNESS = r"""
import vm from 'node:vm';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const { source, mode, chromePath } = JSON.parse(input);
const calls = [], errors = [];
let exitCode = null;
const context = vm.createContext({
  process: {
    env: chromePath ? { CHROME_PATH: chromePath } : {},
    exit(code) { exitCode = code; throw new Error('EXIT'); },
  },
  console: { error(message) { errors.push(message); } },
}, { codeGeneration: { strings: false, wasm: false } });
const dependency = new vm.SyntheticModule(['chromium'], function () {
  this.setExport('chromium', {
    async launch(options) {
      calls.push(options);
      if (mode === 'launch-error') throw new Error('sandbox unavailable');
      return 'fake-browser';
    },
  });
}, { context });
const launcher = new vm.SourceTextModule(source, {
  context,
  async importModuleDynamically(specifier) {
    if (specifier !== 'playwright-core') throw new Error('unexpected import');
    if (mode === 'missing-dependency') throw new Error('not installed');
    await dependency.link(() => { throw new Error('unexpected nested import'); });
    await dependency.evaluate({ timeout: 1000 });
    return dependency;
  },
});
await launcher.link(() => { throw new Error('unexpected static import'); });
await launcher.evaluate({ timeout: 1000 });
let result = null;
try { result = await launcher.namespace.launch(); }
catch (error) { if (exitCode === null) throw error; }
process.stdout.write(JSON.stringify({ calls, errors, exitCode, result }));
"""


@unittest.skipUnless(NODE, "Node.js is required for the launcher contract test")
class StageshowBrowserLauncherTests(unittest.TestCase):
    def run_launcher(self, mode="success", chrome_path=None):
        completed = subprocess.run(
            [NODE, "--experimental-vm-modules", "--input-type=module", "-e", HARNESS],
            input=json.dumps({"source": BROWSER.read_text(), "mode": mode, "chromePath": chrome_path}),
            text=True,
            capture_output=True,
            timeout=10,
            env={},
            check=True,
        )
        return json.loads(completed.stdout)

    def test_default_channel_explicitly_enables_chromium_sandbox(self):
        result = self.run_launcher()
        self.assertEqual(result["calls"], [{"channel": "chrome", "chromiumSandbox": True}])
        self.assertEqual(result["result"], "fake-browser")
        self.assertIsNone(result["exitCode"])

    def test_explicit_official_browser_path_preserves_sandbox(self):
        result = self.run_launcher(chrome_path="/synthetic/browser/chrome")
        self.assertEqual(result["calls"], [{"executablePath": "/synthetic/browser/chrome", "chromiumSandbox": True}])
        self.assertEqual(result["result"], "fake-browser")

    def test_failed_launch_does_not_retry_with_weaker_options(self):
        result = self.run_launcher(mode="launch-error")
        self.assertEqual(result["exitCode"], 2)
        self.assertEqual(result["calls"], [{"channel": "chrome", "chromiumSandbox": True}])
        self.assertIsNone(result["result"])
        self.assertEqual(len(result["errors"]), 1)

    def test_missing_dependency_fails_before_launch(self):
        result = self.run_launcher(mode="missing-dependency")
        self.assertEqual(result["exitCode"], 2)
        self.assertEqual(result["calls"], [])
        self.assertIsNone(result["result"])


if __name__ == "__main__":
    unittest.main()
