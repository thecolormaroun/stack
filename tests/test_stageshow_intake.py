"""Static source-integrity and publication-boundary checks; no upstream execution."""
from __future__ import annotations

import hashlib
import html.parser
import importlib.util
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/imported/benjitaylor/stageshow"
PIN = "802057409787133703c56001080169e347305572"


def load_tool(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StageshowIntakeTests(unittest.TestCase):
    def test_validated_integration_is_eligible_for_both_managed_runtimes(self) -> None:
        manifest_path = SKILL / "capability.json"
        manifest = json.loads(manifest_path.read_text())
        load_tool("build-capability-registry").validate_manifest(manifest, manifest_path, ROOT)
        self.assertEqual(manifest["lifecycle"], "active")
        self.assertEqual(manifest["validation"]["status"], "validated")
        self.assertEqual(manifest["runtimes"]["publish_targets"], ["claude", "codex"])
        self.assertIn(PIN, manifest["provenance"]["source_identity"])
        compiler = load_tool("compile-runtime")
        for runtime in ("claude", "codex"):
            self.assertIsNone(compiler.exclusion(manifest, runtime))

    def test_acceptance_binds_actual_video_and_current_safety_helpers(self) -> None:
        receipt = json.loads((ROOT / "artifacts/validation/stageshow/2026-11-09-accepted.json").read_text())
        self.assertEqual(receipt["status"], "passed")
        for name, digest in receipt["source"]["helper_sha256"].items():
            self.assertEqual(hashlib.sha256((SKILL / name).read_bytes()).hexdigest(), digest)
        for name, digest in receipt["artifacts_sha256"].items():
            self.assertEqual(hashlib.sha256((ROOT / receipt["artifact_root"] / name).read_bytes()).hexdigest(), digest)
        for name in ("representative-still", "representative-compact", "representative-loop-final"):
            with self.subTest(accepted_route=name):
                report = json.loads((ROOT / receipt["artifact_root"] / "outputs" / (name + ".json")).read_text())
                self.assertEqual(report["exitCode"], 0)
                self.assertEqual(report["status"], "no-issues-detected")
                self.assertEqual(report["errors"], [])
                self.assertTrue(report["stages"])
                for stage in report["stages"]:
                    self.assertEqual(stage["coverage"]["status"], "complete")
                    self.assertEqual(stage["findings"], [])
        video = receipt["checks"]["video"]["sample"]
        self.assertEqual((video["duration_seconds"], video["dimensions"], video["decoded_frames"]), (12, [640, 480], 300))

    def test_imported_bytes_match_the_recorded_immutable_subset(self) -> None:
        source = json.loads((SKILL / "source.json").read_text())
        self.assertEqual(source["revision"], PIN)
        self.assertEqual(source["subdirectory"], "stageshow")
        self.assertEqual(len(source["files"]) + len(source["excluded"]), 358)
        self.assertEqual(set(source["stack_authored"]), {"source.json", "capability.json", "STACK-REVIEW.md"})
        expected = set(source["files"]) | set(source["stack_authored"])
        actual = {p.relative_to(SKILL).as_posix() for p in SKILL.rglob("*") if p.is_file()}
        self.assertEqual(actual, expected)
        for name, metadata in source["files"].items():
            with self.subTest(path=name):
                path = SKILL / name
                self.assertFalse(path.is_symlink())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), metadata["sha256"])
                if "adaptation" not in metadata:
                    self.assertEqual(metadata["sha256"], metadata["upstream_sha256"])
        for name in source["excluded"]:
            self.assertFalse((SKILL / name).exists(), name)

    def test_required_notices_are_preserved_and_excluded_art_is_unreferenced(self) -> None:
        source = json.loads((SKILL / "source.json").read_text())
        notices = ["LICENSE", "NOTICE.md", "kit/brands/SOURCES.md", "kit/brands/LICENSE-SVGL.txt", "kit/brands/LICENSE-PAYMENT-ICONS.txt", "kit/brands/LICENSE-CRYPTO-FLAT.txt", "kit/brands/LICENSE-SIMPLE-ICONS.txt", "examples/wikipedia/PHOTOS.md"]
        for name in notices:
            with self.subTest(path=name):
                self.assertEqual(source["files"][name]["sha256"], source["files"][name]["upstream_sha256"])
        registry = (SKILL / "kit/brands/index.ts").read_text()
        for name in ("linear.svg", "linear-dark.svg", "amex.svg", "amex-tile.svg", "usdc.svg"):
            self.assertNotIn("./" + name, registry)
        for path in SKILL.rglob("*.tsx"):
            self.assertNotRegex(path.read_text(), r"(?:from|import)\s*['\"][^'\"]*app-icons")

    def test_retained_relative_module_and_asset_references_resolve(self) -> None:
        patterns = [r"(?:from\s+|import\s*\(\s*|import\s+)['\"](\.[^'\"]+)['\"]", r"new URL\(['\"](\.[^'\"]+)['\"]"]
        for path in SKILL.rglob("*"):
            if not path.is_file() or path.suffix not in {".ts", ".tsx", ".mjs", ".css"}:
                continue
            for pattern in patterns:
                for relative in re.findall(pattern, path.read_text()):
                    if "*" in relative:
                        continue
                    target = (path.parent / relative).resolve()
                    self.assertTrue(target.is_relative_to(SKILL.resolve()))
                    candidates = [target, *[Path(str(target) + suffix) for suffix in (".ts", ".tsx", ".mjs", ".js", ".css", ".svg")], target / "index.ts", target / "index.tsx"]
                    self.assertTrue(any(p.is_file() for p in candidates), f"{path.relative_to(SKILL)}: {relative}")


    def test_static_gate_policy_preserves_nonzero_report_status(self) -> None:
        # Read source policy; never import or execute the third-party tool.
        film = (SKILL / "scripts/film.mjs").read_text()
        block = film.split("const finishReport =", 1)[1].split("const shots =", 1)[0]
        gate = block.split("if (has('gate'))", 1)[1].split("if (reportPath)", 1)[0]
        self.assertNotIn("process.exitCode", gate)
        match = re.search(r"result\.exitCode = Math\.max\(result\.exitCode, (\d+)\)", gate)
        self.assertIsNotNone(match)
        failure_floor = int(match.group(1))
        self.assertEqual(failure_floor, 1)
        self.assertIn("else if (result.exitCode === 0)", gate)
        self.assertIn("process.exitCode = result.exitCode", block)
        self.assertLess(block.index("Math.max"), block.index("writeFileSync"))
        self.assertLess(block.index("writeFileSync"), block.index("process.exitCode = result.exitCode"))
        # Stdlib policy fixtures establish expected failure precedence only.
        for report, failed_gate, expected in ((0, False, 0), (0, True, 1), (1, False, 1), (1, True, 1), (2, False, 2), (2, True, 2)):
            actual = max(report, failure_floor) if failed_gate else report
            self.assertEqual(actual, expected)

    def test_static_caption_escape_policy_keeps_page_markup_as_text(self) -> None:
        film = (SKILL / "scripts/film.mjs").read_text()
        match = re.search(r"const HTML_TEXT_ENTITIES = (\{[^\n]+\})", film)
        self.assertIsNotNone(match)
        entities = json.loads(match.group(1))
        self.assertEqual(entities, {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})
        self.assertIn("String(value).replace(/[&<>\"']/g, (character) => HTML_TEXT_ENTITIES[character])", film)
        self.assertIn("${escapeHtmlText(s.label)}", film)
        self.assertNotIn("${s.label}", film)

        class CaptionParser(html.parser.HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.tags = []
                self.text = []

            def handle_starttag(self, tag, attrs):
                self.tags.append((tag, attrs))

            def handle_data(self, data):
                self.text.append(data)

        # Parse extracted entity data with stdlib; no JavaScript is evaluated.
        payloads = ["plain label", "</figcaption><script>alert(1)</script>", '<img src=x onerror="alert(1)"> & \'single\' "double"', "&lt;script&gt;", "label → 日本語"]
        for payload in payloads:
            with self.subTest(label=payload):
                escaped = "".join(entities.get(character, character) for character in payload)
                parser = CaptionParser()
                parser.feed("<figcaption>" + escaped + "</figcaption>")
                self.assertEqual(parser.tags, [("figcaption", [])])
                self.assertEqual("".join(parser.text), payload)

if __name__ == "__main__":
    unittest.main()
