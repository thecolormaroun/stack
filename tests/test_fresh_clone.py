"""Fresh checkout proof: bootstrap dry-runs without touching a user home."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("runtime_parity_fixture", ROOT / "tests" / "test_runtime_parity.py")
assert SPEC and SPEC.loader
FIXTURE_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURE_MODULE)
fixture = FIXTURE_MODULE.fixture


class FreshCloneTests(unittest.TestCase):
    def test_fresh_fixture_checkout_does_not_write_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            source, clone, home = temporary_root / "source", temporary_root / "clone", temporary_root / "home"
            fixture(source)
            (source / "scripts").mkdir()
            for name in ("bootstrap-stack.py", "stack-doctor.py", "compile-runtime.py", "install-runtime.py", "validate-private-overlay.py"):
                shutil.copy2(ROOT / "scripts" / name, source / "scripts" / name)
            shutil.copytree(source, clone)
            home.mkdir()
            result = subprocess.run(
                ["python3", str(clone / "scripts/bootstrap-stack.py"), "--root", str(clone)],
                text=True, capture_output=True, check=False, env={**os.environ, "HOME": str(home)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(home.iterdir()), [])
            self.assertIn('"mode": "dry-run"', result.stdout)


if __name__ == "__main__":
    unittest.main()
