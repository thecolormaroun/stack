from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run-design-intelligence-evaluation.py"
SPEC = importlib.util.spec_from_file_location("design_intelligence_evidence_runner", SCRIPT)
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)


PNG = b"\x89PNG\r\n\x1a\nsynthetic screenshot bytes"


class FakeBrowser:
    def __init__(self, *, interrupt_candidate_once: bool = False, fail_command: tuple[str, ...] | None = None, visible: bool = True, empty_snapshot: bool = False):
        self.calls: list[tuple[str, ...]] = []
        self.environments: list[dict[str, str]] = []
        self.current_url = "about:blank"
        self.interrupt_candidate_once = interrupt_candidate_once
        self.did_interrupt = False
        self.fail_command = fail_command
        self.visible = visible
        self.empty_snapshot = empty_snapshot
        self.blanket_route = False
        self.clicked_continue = False

    def __call__(self, argv, **kwargs):
        self.assert_safe_invocation(argv, kwargs)
        self.environments.append(kwargs["env"])
        command = tuple(argv[argv.index("--session") + 2 :])
        self.calls.append(command)
        stdout = b""
        if self.fail_command == command:
            return subprocess.CompletedProcess(argv, 19, b"private page output", b"token=must-not-escape")
        if command == ("open",):
            self.current_url = "about:blank"
            self.clicked_continue = False
        elif command == ("network", "route", "*", "--abort"):
            self.blanket_route = True
        elif len(command) == 2 and command[0] == "open":
            if self.blanket_route and command[1].startswith("file://"):
                return subprocess.CompletedProcess(argv, 1, b"", b"local fixture aborted")
            if self.interrupt_candidate_once and command[1].startswith("data:") and b"Updated" in base64.b64decode(command[1].split(",", 1)[1]) and not self.did_interrupt:
                self.did_interrupt = True
                raise KeyboardInterrupt
            self.current_url = command[1]
            self.clicked_continue = False
        elif command == ("click", "#continue"):
            self.clicked_continue = True
        elif command == ("get", "url"):
            stdout = self.current_url.encode()
        elif command == ("snapshot",):
            stdout = b"" if self.empty_snapshot else b"document\n  button: Continue"
        elif command and command[0] == "screenshot":
            Path(command[1]).write_bytes(PNG)
        elif command and command[0] == "eval":
            assert command[1].startswith("({"), "Return an object; the CLI already serializes results"
            stdout = json.dumps({
                "viewport_width": 1280,
                "viewport_height": 800,
                "scroll_width": 1296,
                "scroll_height": 950,
            }).encode()
        elif command[:2] == ("is", "visible"):
            stdout = b"true" if self.visible and self.clicked_continue and command[2] == "#result" else b"false"
        elif command[:2] == ("get", "text"):
            stdout = b"Complete"
        elif command[:2] == ("get", "count"):
            stdout = b"1"
        return subprocess.CompletedProcess(argv, 0, stdout, b"private diagnostic data")

    @staticmethod
    def assert_safe_invocation(argv, kwargs):
        assert kwargs["shell"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["check"] is False
        assert set(kwargs["env"]) == {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "AGENT_BROWSER_CONFIG"}
        assert "--args" not in argv
        assert "--proxy" not in argv
        assert "--profile" not in argv


class DesignIntelligenceEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="design-eval-tests-")
        self.root = Path(self.temp.name)
        self.source_dir = self.root / "inputs"
        self.source_dir.mkdir(mode=0o700)
        self.output_dir = self.root / "output"
        self.manifest_path = self.source_dir / "manifest.json"
        self.browser_path = self.source_dir / "fake-agent-browser"
        self.browser_path.write_bytes(b"fixture executable; commands are injected\n")
        self.browser_path.chmod(0o700)
        allowlist = patch.object(RUNNER, "ALLOWED_BROWSER_EXECUTABLES", {str(self.browser_path)})
        allowlist.start()
        self.addCleanup(allowlist.stop)

    def tearDown(self):
        self.temp.cleanup()

    def write_input(self, name: str, content: bytes) -> dict[str, str]:
        path = self.source_dir / name
        path.write_bytes(content)
        return {"path": str(path), "sha256": RUNNER.digest_file(path)}

    def make_manifest(self, *, case_count: int = 1, workflow: bool = True, browser_arguments=None, extras=None) -> tuple[dict, str]:
        cases = []
        for number in range(case_count):
            suffix = f"{number + 1}"
            task = self.write_input(f"task-{suffix}.md", f"Task {suffix}: complete the local workflow.".encode())
            baseline = self.write_input(f"baseline-{suffix}.html", f"<main data-case='{suffix}'><button id='continue' onclick=\"document.querySelector('#result').hidden=false\">Continue</button><p id='result' hidden>Complete</p></main>".encode())
            candidate = self.write_input(f"candidate-{suffix}.html", f"<main data-case='{suffix}'><button id='continue' onclick=\"document.querySelector('#result').hidden=false\">Continue</button><p id='result' hidden>Updated</p></main>".encode())
            case = {
                "case_id": f"fixture-{suffix}",
                "task_asset": task,
                "viewport": {"width": 1280, "height": 800},
                "variants": {
                    "baseline": {"html": baseline, "assets": []},
                    "candidate": {"html": candidate, "assets": []},
                },
            }
            if workflow:
                case["primary_workflow"] = [{
                    "action": "click",
                    "selector": "#continue",
                    "assertions": [{"kind": "visible", "selector": "#result"}],
                }]
            cases.append(case)
        manifest = {
            "schema_version": 1,
            "run_id": "design-eval-test",
            "content_scope": "synthetic_non_private",
            "offline_asset_policy": RUNNER.OFFLINE_POLICY,
            "browser": {"executable": str(self.browser_path), "arguments": browser_arguments or []},
            "cases": cases,
        }
        if extras:
            manifest.update(extras)
        payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        self.manifest_path.write_bytes(payload)
        return manifest, RUNNER.digest_bytes(payload)

    def run_manifest(self, manifest_digest: str, fake: FakeBrowser):
        return RUNNER.run_evaluation(self.manifest_path, manifest_digest, self.output_dir, command_runner=fake)

    def workflow_snapshot(self):
        store = RUNNER._run_state.WorkflowStore(self.output_dir / "workflow.sqlite3")
        try:
            return store.snapshot("design-eval-test")
        finally:
            store.close()

    def test_real_call_plan_captures_local_artifacts_and_only_observations(self):
        _, manifest_digest = self.make_manifest()
        fake = FakeBrowser()

        receipt = self.run_manifest(manifest_digest, fake)

        self.assertEqual(receipt["status"], "evidence_collected")
        self.assertEqual(receipt["evaluation_status"], "not_evaluated")
        self.assertEqual(receipt["human_task_usefulness"], "pending")
        self.assertNotIn("score", receipt)
        self.assertNotIn("awaiting_approval", json.dumps(receipt))
        self.assertEqual(len(receipt["observations"]), 2)
        first = receipt["observations"][0]
        self.assertEqual(first["browser_request_routing"], {"status": "abort_routes_installed_before_fixture_navigation", "routes": ["http://**", "https://**", "file://**"], "action": "abort"})
        self.assertIn("whole_browser_egress_isolation_not_attested", receipt["limits"])
        self.assertEqual(first["page_errors"], {"status": "observed", "nonempty_line_count": 0})
        self.assertEqual(first["overflow"]["horizontal_overflow_pixels"], 16)
        self.assertEqual(first["primary_workflow_actions"]["status"], "observed")
        for observed in receipt["observations"]:
            for artifact in observed["artifacts"].values():
                path = self.output_dir / artifact["path"]
                self.assertEqual(RUNNER.digest_file(path), artifact["sha256"])
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertNotIn(str(self.source_dir), json.dumps(observed))

        route_index = fake.calls.index(("network", "route", "https://**", "--abort"))
        fixture_open_index = next(index for index, call in enumerate(fake.calls) if len(call) == 2 and call[0] == "open" and call[1].startswith("data:text/html;charset=utf-8;base64,"))
        self.assertLess(route_index, fixture_open_index)
        self.assertLess(fake.calls.index(("network", "route", "http://**", "--abort")), fixture_open_index)
        self.assertLess(fake.calls.index(("network", "route", "file://**", "--abort")), fixture_open_index)
        self.assertNotIn(("network", "route", "*", "--abort"), fake.calls)
        self.assertIn(("set", "viewport", "1280", "800"), fake.calls)
        self.assertIn(("snapshot",), fake.calls)
        self.assertLess(fake.calls.index(("click", "#continue")), fake.calls.index(("is", "visible", "#result")))
        self.assertEqual(receipt["executor_policy_revision"], RUNNER.EXECUTOR_POLICY_REVISION)
        self.assertEqual(receipt["collector_sha256"], RUNNER.digest_file(SCRIPT))
        screenshot_paths = {str(path.resolve()) for path in self.output_dir.glob("artifacts/**/viewport.png")}
        captured_paths = {Path(call[1]).resolve().__str__() for call in fake.calls if len(call) == 2 and call[0] == "screenshot"}
        self.assertEqual(screenshot_paths, captured_paths)
        self.assertTrue(all("private diagnostic data" not in env.values() for env in fake.environments))
        saved = self.workflow_snapshot()
        self.assertEqual(saved["status"], "implemented")
        self.assertFalse(saved["approval_required"])
        self.assertEqual(saved["children"][0]["status"], "completed")

    def test_interrupted_run_resumes_after_verified_checkpoint_without_replaying_it(self):
        _, manifest_digest = self.make_manifest(case_count=2, workflow=False)
        first_runner = FakeBrowser(interrupt_candidate_once=True)

        with self.assertRaises(RUNNER.EvidenceError) as interrupted:
            self.run_manifest(manifest_digest, first_runner)
        self.assertEqual(interrupted.exception.code, "run_interrupted")
        blocked = self.workflow_snapshot()
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["children"][0]["status"], "failed")

        retry_runner = FakeBrowser()
        receipt = self.run_manifest(manifest_digest, retry_runner)

        self.assertEqual(receipt["status"], "evidence_collected")
        self.assertEqual(len(receipt["observations"]), 4)
        baseline_page = next(call[1] for call in first_runner.calls if len(call) == 2 and call[0] == "open" and call[1].startswith("data:"))
        replay_count = sum(1 for call in retry_runner.calls if call == ("open", baseline_page))
        self.assertEqual(replay_count, 0)
        self.assertEqual(self.workflow_snapshot()["status"], "implemented")

    def test_manifest_input_and_artifact_drift_fail_closed_without_browser_calls(self):
        manifest, manifest_digest = self.make_manifest(workflow=False)
        fake = FakeBrowser()
        self.run_manifest(manifest_digest, fake)
        call_count = len(fake.calls)

        candidate = Path(manifest["cases"][0]["variants"]["candidate"]["html"]["path"])
        candidate.write_text("<main>changed after review</main>")
        with self.assertRaises(RUNNER.EvidenceError) as input_drift:
            self.run_manifest(manifest_digest, fake)
        self.assertIn("digest_mismatch", input_drift.exception.code)
        self.assertEqual(len(fake.calls), call_count)

        candidate.write_bytes(b"<main data-case='1'><button id='continue' onclick=\"document.querySelector('#result').hidden=false\">Continue</button><p id='result' hidden>Updated</p></main>")
        changed_manifest = json.loads(self.manifest_path.read_text())
        changed_manifest["cases"][0]["viewport"]["width"] = 1240
        changed_payload = json.dumps(changed_manifest, sort_keys=True, separators=(",", ":")).encode()
        self.manifest_path.write_bytes(changed_payload)
        changed_pin = RUNNER.digest_bytes(changed_payload)
        with self.assertRaises(RUNNER.EvidenceError) as manifest_drift:
            self.run_manifest(changed_pin, fake)
        self.assertEqual(manifest_drift.exception.code, "run_input_drift")
        self.assertEqual(len(fake.calls), call_count)

    def test_tampered_saved_screenshot_is_rejected_before_browser_resume(self):
        _, manifest_digest = self.make_manifest(workflow=False)
        fake = FakeBrowser()
        receipt = self.run_manifest(manifest_digest, fake)
        screenshot = self.output_dir / receipt["observations"][0]["artifacts"]["screenshot"]["path"]
        screenshot.write_bytes(PNG + b"changed")
        call_count = len(fake.calls)

        with self.assertRaises(RUNNER.EvidenceError) as tampered:
            self.run_manifest(manifest_digest, fake)
        self.assertEqual(tampered.exception.code, "evidence_artifact_tampered")
        self.assertEqual(len(fake.calls), call_count)

    def test_changed_execution_helpers_reject_interrupted_resume_before_browser(self):
        _, manifest_digest = self.make_manifest(workflow=False)
        first = FakeBrowser(interrupt_candidate_once=True)
        with self.assertRaises(RUNNER.EvidenceError):
            self.run_manifest(manifest_digest, first)
        original_digest = RUNNER.digest_file
        for name, helper_path in RUNNER.HELPER_PATHS.items():
            with self.subTest(helper=name):
                changed = dict(RUNNER.LOADED_HELPER_DIGESTS)
                changed[name] = "a" * 64

                def changed_digest(path):
                    return changed[name] if Path(path) == helper_path else original_digest(path)

                retry = FakeBrowser()
                with patch.object(RUNNER, "LOADED_HELPER_DIGESTS", changed), patch.object(RUNNER, "digest_file", side_effect=changed_digest):
                    with self.assertRaises(RUNNER.EvidenceError) as drift:
                        self.run_manifest(manifest_digest, retry)
                self.assertEqual(drift.exception.code, "run_input_drift")
                self.assertEqual(retry.calls, [])

    def test_execution_helper_changed_after_import_blocks_new_run(self):
        _, manifest_digest = self.make_manifest(workflow=False)
        changed = dict(RUNNER.LOADED_HELPER_DIGESTS)
        changed["workflow_store"] = "a" * 64
        fake = FakeBrowser()
        with patch.object(RUNNER, "LOADED_HELPER_DIGESTS", changed):
            with self.assertRaises(RUNNER.EvidenceError) as drift:
                self.run_manifest(manifest_digest, fake)
        self.assertEqual(drift.exception.code, "execution_helper_drift")
        self.assertEqual(fake.calls, [])

    def test_allowlisted_symlink_swap_keeps_invoking_pinned_target(self):
        _, manifest_digest = self.make_manifest(workflow=False)
        target = self.source_dir / "browser-original"
        target.write_bytes(self.browser_path.read_bytes())
        target.chmod(0o700)
        replacement = self.source_dir / "browser-replacement"
        replacement.write_bytes(b"must never be invoked")
        replacement.chmod(0o700)
        self.browser_path.unlink()
        self.browser_path.symlink_to(target)
        owner = self

        class SwappingBrowser(FakeBrowser):
            def __call__(self, argv, **kwargs):
                owner.assertEqual(argv[0], str(target.resolve()))
                result = super().__call__(argv, **kwargs)
                if len(self.calls) == 1:
                    owner.browser_path.unlink()
                    owner.browser_path.symlink_to(replacement)
                return result

        receipt = self.run_manifest(manifest_digest, SwappingBrowser())
        self.assertEqual(receipt["status"], "evidence_collected")
        self.assertEqual(receipt["browser_digest"], RUNNER.digest_file(target))

    def test_changed_pinned_browser_is_rejected_before_next_command(self):
        _, manifest_digest = self.make_manifest(workflow=False)
        owner = self

        class ChangingBrowser(FakeBrowser):
            def __call__(self, argv, **kwargs):
                result = super().__call__(argv, **kwargs)
                if len(self.calls) == 1:
                    owner.browser_path.write_bytes(b"changed executable")
                return result

        fake = ChangingBrowser()
        with self.assertRaises(RUNNER.EvidenceError) as drift:
            self.run_manifest(manifest_digest, fake)
        self.assertEqual(drift.exception.code, "browser_executable_drift")
        self.assertEqual(fake.calls, [("open",)])

    def test_manifest_rejects_unrecognized_execution_fields(self):
        _, manifest_digest = self.make_manifest(extras={"shell_command": "must never be executed"})
        with self.assertRaises(RUNNER.EvidenceError) as unsupported:
            self.run_manifest(manifest_digest, FakeBrowser())
        self.assertEqual(unsupported.exception.code, "unsupported_manifest")

    def test_external_assets_and_old_offline_policy_are_rejected_before_browser(self):
        manifest, _ = self.make_manifest(workflow=False)
        manifest["cases"][0]["variants"]["baseline"]["assets"] = [self.write_input("behavior.js", b"window.fixture = true")]
        payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        self.manifest_path.write_bytes(payload)
        fake = FakeBrowser()
        with self.assertRaises(RUNNER.EvidenceError) as external:
            self.run_manifest(RUNNER.digest_bytes(payload), fake)
        self.assertEqual(external.exception.code, "unsupported_artifact_assets")
        self.assertEqual(fake.calls, [])

        manifest["cases"][0]["variants"]["baseline"]["assets"] = []
        manifest["offline_asset_policy"] = "abort-http-requests-before-fixture-navigation"
        payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        self.manifest_path.write_bytes(payload)
        with self.assertRaises(RUNNER.EvidenceError) as old_policy:
            self.run_manifest(RUNNER.digest_bytes(payload), fake)
        self.assertEqual(old_policy.exception.code, "unsupported_offline_policy")
        self.assertEqual(fake.calls, [])

    def test_undeclared_script_change_cannot_change_digest_bound_page(self):
        manifest, _ = self.make_manifest(workflow=False)
        html = Path(manifest["cases"][0]["variants"]["baseline"]["html"]["path"])
        html.write_bytes(b"<main>Synthetic<script src='behavior.js'></script></main>")
        manifest["cases"][0]["variants"]["baseline"]["html"]["sha256"] = RUNNER.digest_file(html)
        payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        self.manifest_path.write_bytes(payload)
        script = self.source_dir / "behavior.js"
        script.write_bytes(b"document.body.textContent = 'first'")
        first = FakeBrowser()
        RUNNER.run_evaluation(self.manifest_path, RUNNER.digest_bytes(payload), self.root / "capture-one", command_runner=first)
        first_url = next(call[1] for call in first.calls if len(call) == 2 and call[0] == "open" and call[1].startswith("data:"))
        page = base64.b64decode(first_url.split(",", 1)[1])
        self.assertIn(b"Content-Security-Policy", page)
        self.assertIn(b"default-src 'none'", page)
        self.assertIn(b"<script src='behavior.js'>", page)
        self.assertLess(first.calls.index(("network", "route", "file://**", "--abort")), first.calls.index(("open", first_url)))
        script.write_bytes(b"document.body.textContent = 'changed'")
        second = FakeBrowser()
        RUNNER.run_evaluation(self.manifest_path, RUNNER.digest_bytes(payload), self.root / "capture-two", command_runner=second)
        second_url = next(call[1] for call in second.calls if len(call) == 2 and call[0] == "open" and call[1].startswith("data:"))
        self.assertEqual(first_url, second_url)

    def test_empty_planned_run_recovers_after_child_creation_interruption(self):
        _, manifest_digest = self.make_manifest(workflow=False)
        original = RUNNER._run_state.WorkflowStore.add_child
        interrupted = False

        def stop_after_create(store, *args, **kwargs):
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                raise KeyboardInterrupt
            return original(store, *args, **kwargs)

        with patch.object(RUNNER._run_state.WorkflowStore, "add_child", stop_after_create):
            with self.assertRaises(KeyboardInterrupt):
                self.run_manifest(manifest_digest, FakeBrowser())
        planned = self.workflow_snapshot()
        self.assertEqual(planned["status"], "planned")
        self.assertEqual(planned["children"], [])
        receipt = self.run_manifest(manifest_digest, FakeBrowser())
        self.assertEqual(receipt["status"], "evidence_collected")
        self.assertEqual(len(self.workflow_snapshot()["children"]), 1)

    def test_foreign_or_partial_empty_run_cannot_be_recovered(self):
        _, manifest_digest = self.make_manifest(workflow=False)
        self.output_dir.mkdir(mode=0o700)
        store = RUNNER._run_state.WorkflowStore(self.output_dir / "workflow.sqlite3")
        try:
            store.create_run("design-eval-test", "stack-design-intelligence-evaluation", "foreign-owner", str(ROOT), max_children=1, approval_required=False)
        finally:
            store.close()
        fake = FakeBrowser()
        with self.assertRaises(RUNNER.EvidenceError) as foreign:
            self.run_manifest(manifest_digest, fake)
        self.assertEqual(foreign.exception.code, "workflow_state_identity_mismatch")
        self.assertEqual(fake.calls, [])

        store = RUNNER._run_state.WorkflowStore(self.output_dir / "workflow.sqlite3")
        try:
            store.conn.execute("UPDATE runs SET owner = ? WHERE run_id = ?", (f"uid:{RUNNER.os.getuid()}", "design-eval-test"))
        finally:
            store.close()
        (self.output_dir / "unclaimed-artifact.json").write_text("{}")
        with self.assertRaises(RUNNER.EvidenceError) as partial:
            self.run_manifest(manifest_digest, fake)
        self.assertEqual(partial.exception.code, "workflow_state_invalid")
        self.assertEqual(fake.calls, [])

    def test_private_inputs_are_rejected_without_whole_process_egress_isolation(self):
        manifest, _ = self.make_manifest(workflow=False)
        manifest["content_scope"] = "private"
        payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        self.manifest_path.write_bytes(payload)
        fake = FakeBrowser()

        with self.assertRaises(RUNNER.EvidenceError) as rejected:
            self.run_manifest(RUNNER.digest_bytes(payload), fake)

        self.assertEqual(rejected.exception.code, "private_artifacts_require_egress_isolation")
        self.assertEqual(fake.calls, [])

    def test_browser_route_failure_blocks_before_fixture_navigation(self):
        _, manifest_digest = self.make_manifest(workflow=False)
        browser_failure = FakeBrowser(fail_command=("network", "route", "https://**", "--abort"))
        with self.assertRaises(RUNNER.EvidenceError) as browser_error:
            self.run_manifest(manifest_digest, browser_failure)
        self.assertEqual(browser_error.exception.code, "browser_command_failed")
        self.assertFalse(any(len(call) == 2 and call[0] == "open" and call[1].startswith("data:") for call in browser_failure.calls))
        self.assertEqual(self.workflow_snapshot()["status"], "blocked")

    def test_failed_primary_assertion_is_blocked_not_scored(self):
        _, manifest_digest = self.make_manifest(case_count=1, workflow=True)
        action_failure = FakeBrowser(visible=False)
        receipt = self.run_manifest(manifest_digest, action_failure)
        self.assertEqual(receipt["status"], "blocked")
        self.assertEqual(receipt["observations"][0]["primary_workflow_actions"]["status"], "failed")
        self.assertEqual(receipt["human_task_usefulness"], "pending")
        self.assertEqual(self.workflow_snapshot()["status"], "blocked")
        self.assertNotIn("score", receipt)
        self.assertNotIn("awaiting_approval", json.dumps(receipt))

    def test_failed_click_cannot_satisfy_primary_assertion(self):
        _, manifest_digest = self.make_manifest(workflow=True)
        fake = FakeBrowser(fail_command=("click", "#continue"))
        receipt = self.run_manifest(manifest_digest, fake)
        self.assertEqual(receipt["status"], "blocked")
        self.assertEqual(receipt["observations"][0]["primary_workflow_actions"]["status"], "failed")
        self.assertNotIn(("is", "visible", "#result"), fake.calls)

    def test_run_longer_than_initial_lease_renews_and_excludes_competing_collector(self):
        _, manifest_digest = self.make_manifest(case_count=2, workflow=False)
        clock = [1_000.0]
        competing_results = []
        owner = self

        class SlowBrowser(FakeBrowser):
            def __call__(self, argv, **kwargs):
                result = super().__call__(argv, **kwargs)
                clock[0] += 80
                if clock[0] > 1_960 and not competing_results:
                    store = RUNNER._run_state.WorkflowStore(owner.output_dir / "workflow.sqlite3")
                    try:
                        competing_results.append(store.claim_child("design-eval-test", "browser-evidence", "competing-owner", lease_seconds=900, now=clock[0]))
                    finally:
                        store.close()
                    with owner.assertRaises(RUNNER.EvidenceError) as blocked:
                        owner.run_manifest(manifest_digest, FakeBrowser())
                    competing_results.append(blocked.exception.code)
                return result

        with patch.object(RUNNER._run_state.time, "time", side_effect=lambda: clock[0]):
            receipt = self.run_manifest(manifest_digest, SlowBrowser())
        self.assertEqual(receipt["status"], "evidence_collected")
        self.assertGreater(clock[0] - 1_000, 900)
        self.assertEqual(competing_results, [False, "workflow_execution_locked"])
        self.assertEqual(self.workflow_snapshot()["status"], "implemented")

    def test_lost_renewal_stops_capture_and_still_closes_browser(self):
        _, manifest_digest = self.make_manifest(workflow=False)
        original = RUNNER._run_state.WorkflowStore.renew_child_lease
        renewals = 0

        def lose_during_browser(store, *args, **kwargs):
            nonlocal renewals
            renewals += 1
            if renewals == 8:
                return False
            return original(store, *args, **kwargs)

        fake = FakeBrowser()
        with patch.object(RUNNER._run_state.WorkflowStore, "renew_child_lease", lose_during_browser):
            with self.assertRaises(RUNNER.EvidenceError) as lost:
                self.run_manifest(manifest_digest, fake)
        self.assertEqual(lost.exception.code, "workflow_child_lease_lost")
        self.assertIn(("close",), fake.calls)
        self.assertEqual(self.workflow_snapshot()["status"], "blocked")

    def test_missing_accessibility_evidence_stays_blocked_not_passed(self):
        _, manifest_digest = self.make_manifest(workflow=False)
        fake = FakeBrowser(empty_snapshot=True)

        with self.assertRaises(RUNNER.EvidenceError) as missing:
            self.run_manifest(manifest_digest, fake)

        self.assertEqual(missing.exception.code, "accessibility_snapshot_missing")
        self.assertEqual(self.workflow_snapshot()["status"], "blocked")

    def test_manifest_digest_pin_and_argument_allowlist_are_enforced(self):
        _, manifest_digest = self.make_manifest(browser_arguments=["--proxy=http://example.invalid"])
        with self.assertRaises(RUNNER.EvidenceError) as rejected:
            self.run_manifest(manifest_digest, FakeBrowser())
        self.assertEqual(rejected.exception.code, "browser_arguments_not_allowlisted")
        with self.assertRaises(RUNNER.EvidenceError) as wrong_pin:
            self.run_manifest("0" * 64, FakeBrowser())
        self.assertEqual(wrong_pin.exception.code, "reviewed_manifest_digest_mismatch")


if __name__ == "__main__":
    unittest.main()
