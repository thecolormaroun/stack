from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = load("design_intelligence_generation", ROOT / "scripts/generate-design-intelligence-artifacts.py")
MAT = load("generation_test_materializer", ROOT / "scripts/materialize-capability-change.py")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def private(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(content)
    path.chmod(0o600)
    return path


def events(html: str, *, tool: bool = False, multiple: bool = False) -> bytes:
    rows = [{"type": "thread.started", "thread_id": "synthetic-thread"}, {"type": "turn.started"}]
    if tool:
        rows.append({"type": "item.completed", "item": {"type": "command_execution", "command": "pwd"}})
    rows.append({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"html": html})}})
    if multiple:
        rows.append({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"html": html})}})
    rows.append({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 20}})
    return b"\n".join(json.dumps(row).encode() for row in rows) + b"\n"


class FakeCodex:
    def __init__(self, *, auth: bytes = b"Logged in using ChatGPT\n", bad: bytes | None = None):
        self.auth, self.bad = auth, bad
        self.calls: list[tuple[list[str], bytes | None, dict[str, str]]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs["input"], kwargs["env"]))
        if argv[1:3] == ["login", "status"]:
            return subprocess.CompletedProcess(argv, 0, b"", self.auth)
        if self.bad is not None:
            return subprocess.CompletedProcess(argv, 0, self.bad, b"secret stderr must stay hidden")
        body = "candidate" if b"New synthetic rule." in kwargs["input"] else "baseline"
        return subprocess.CompletedProcess(argv, 0, events(f"<!doctype html><html><head></head><body><h1>{body}</h1></body></html>"), b"")

    @property
    def provider_calls(self):
        return [call for call in self.calls if call[0][1] == "exec"]


class DesignIntelligenceGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.repo = self.root / "repo"
        self.repo.mkdir(mode=0o700)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Fixture"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "fixture@example.invalid"], check=True)
        self.skill = "skills/design/fixture/SKILL.md"
        self.reference = "skills/design/fixture/references/rule.md"
        self.reference_two = "skills/design/fixture/references/rule-two.md"
        (self.repo / self.reference).parent.mkdir(parents=True)
        (self.repo / self.skill).write_text("---\nname: fixture\n---\n# Public synthetic instructions\n")
        (self.repo / self.reference).write_text("# Existing synthetic rule.\n")
        (self.repo / self.reference_two).write_text("# Other synthetic rule.\n")
        (self.repo / "registry").mkdir()
        (self.repo / "registry/capabilities.json").write_text(json.dumps({"capabilities": [{
            "canonical_name": "fixture", "ownership": {"provider": "stack", "package": "stack", "source_path": self.skill},
            "source": {"skill_path": self.skill}}]}))
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "base"], check=True)
        self.base = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        self.inputs = self.root / "inputs"
        self.inputs.mkdir(mode=0o700)
        self.output = self.root / "generation"
        self.command, self.launcher, self.native, self.node = (self.root / name for name in ("codex", "codex.js", "native-codex", "node"))
        for file in (self.launcher, self.native, self.node):
            file.write_bytes(b"public fake executable\n")
            file.chmod(0o700)
        self.command.symlink_to(self.launcher)
        self.original_commands = (GEN.CODEX_COMMAND, GEN.CODEX_LAUNCHER, GEN.CODEX_NATIVE, GEN.NODE_COMMAND)
        GEN.CODEX_COMMAND, GEN.CODEX_LAUNCHER, GEN.CODEX_NATIVE, GEN.NODE_COMMAND = self.command, self.launcher, self.native, self.node
        self.make_inputs()

    def tearDown(self) -> None:
        GEN.CODEX_COMMAND, GEN.CODEX_LAUNCHER, GEN.CODEX_NATIVE, GEN.NODE_COMMAND = self.original_commands
        self.tmp.cleanup()

    def make_inputs(self, *, reference_update: bool = False) -> None:
        edit_path = self.reference if reference_update else self.skill
        before = (self.repo / edit_path).read_bytes()
        after = before + b"\nNew synthetic rule.\n"
        role = "reference" if reference_update else "skill"
        self.packet = {
            "schema_version": 1, "change_id": "change:" + "a" * 16,
            "state": "candidate_quarantined", "approval_state": "candidate_unapproved", "base_commit": self.base,
            "source_lineage": {"packet_id": "packet:" + "b" * 16, "packet_digest": "c" * 64,
                               "card_ids": ["card:" + "d" * 16], "revision_ids": ["revision:" + "e" * 16],
                               "evidence_ids": ["evidence:" + "f" * 16], "parent_digests": ["1" * 64]},
            "target": {"canonical_name": "fixture", "capability_path": self.skill,
                       "provider": "stack", "package": "stack", "upstream_pin": None},
            "rationale": {"change_kind": "reference-update" if reference_update else "skill-update",
                          "expected_behavior": ["Apply the synthetic rule."],
                          "overlap_analysis": {"status": "no_collision", "compared_capabilities": [], "explanation": "No overlap."},
                          "license_posture": "stack-owned-reviewed-derivative", "privacy_class": "reviewed-software-derivative"},
            "rollback": {"base_commit": self.base, "path_digests": {edit_path: sha(before)}},
            "edits": [{"path": edit_path, "role": role, "operation": "replace",
                       "before_digest": sha(before), "after_digest": sha(after), "content": after.decode()}],
            "evaluation": {"profile": "design-learning-v1", "development_manifest_digest": "2" * 64,
                           "holdout_manifest_digest": "3" * 64, "rotating_canary_manifest_digest": "4" * 64,
                           "harness_required": True},
        }
        auth = {"schema_version": 1, "change_digest": MAT.digest_json(self.packet), "base_commit": self.base,
                "scope": "isolated-owner-local-patch-only", "decision": "approved",
                "reviewed_by": "fixture-reviewer", "reviewed_at": "2026-08-23T00:00:00Z"}
        materialization_dir = self.root / ("materialization-reference" if reference_update else "materialization")
        MAT.materialize_change(self.packet, auth, repository=self.repo, output_dir=materialization_dir,
                               policy={"materialization": {"maximum_changed_files": 5, "maximum_total_bytes": 131072,
                                                           "allowed_roles": ["skill", "reference", "registry", "test", "documentation"]}})
        self.packet_path = private(self.inputs / "packet.json", MAT.canonical_json(self.packet).encode())
        self.receipt_path = materialization_dir / "materialization-receipt.json"
        self.patch_path = materialization_dir / "capability-change.patch"
        skill_digest = sha((self.repo / self.skill).read_bytes())
        paths = ([{"path": self.skill, "before_sha256": skill_digest, "after_sha256": skill_digest}]
                 if reference_update else [])
        paths.append({"path": edit_path, "before_sha256": sha(before), "after_sha256": sha(after)})
        self.manifest = {"schema_version": 1, "run_id": "synthetic-generation", "content_scope": "synthetic_non_private",
                         "task": {"case_id": "case-one", "text": "Build a public synthetic dashboard.",
                                  "viewport": {"width": 1280, "height": 800}},
                         "model": {"name": "gpt-6-luna", "reasoning_effort": "max"},
                         "codex": {"executable": str(self.command), "launcher_sha256": sha(self.launcher.read_bytes()),
                                   "native_sha256": sha(self.native.read_bytes()), "node_sha256": sha(self.node.read_bytes())},
                         "candidate_packet": {"path": str(self.packet_path), "sha256": sha(self.packet_path.read_bytes())},
                         "materialization": {"path": str(self.receipt_path), "sha256": sha(self.receipt_path.read_bytes())},
                         "patch": {"path": str(self.patch_path), "sha256": sha(self.patch_path.read_bytes())},
                         "target": self.packet["target"], "instruction_paths": paths}
        self.save_manifest()

    def save_manifest(self) -> str:
        self.manifest_path = private(self.inputs / "generation.json", json.dumps(self.manifest, sort_keys=True).encode())
        return sha(self.manifest_path.read_bytes())

    def prepare(self):
        return GEN.prepare_generation(self.manifest_path, self.save_manifest(), self.repo)

    def execute(self, runner):
        return GEN.execute_generation(self.manifest_path, self.save_manifest(), self.repo, self.output, runner=runner)

    def test_exact_byte_conditioning_and_unrelated_dirty_preserved(self) -> None:
        (self.repo / "do-not-read.md").write_text("User-owned unrelated file.\n")
        status = subprocess.check_output(["git", "-C", str(self.repo), "status", "--porcelain=v1", "--untracked-files=all"])
        context = self.prepare()
        self.assertEqual(status, subprocess.check_output(["git", "-C", str(self.repo), "status", "--porcelain=v1", "--untracked-files=all"]))
        self.assertIn("New synthetic rule.", context["prompts"]["candidate"])
        self.assertNotIn("New synthetic rule.", context["prompts"]["baseline"])
        for prompt in context["prompts"].values():
            for excluded in ("change:", "packet:", "baseline", "candidate", str(self.root)):
                self.assertNotIn(excluded, prompt)

    def test_reference_update_conditions_target_and_reference(self) -> None:
        self.make_inputs(reference_update=True)
        context = self.prepare()
        for prompt in context["prompts"].values():
            self.assertIn("Public synthetic instructions", prompt)
            self.assertIn("Existing synthetic rule", prompt)
        self.assertNotIn("New synthetic rule.", context["prompts"]["baseline"])
        self.assertIn("New synthetic rule.", context["prompts"]["candidate"])

    def test_all_edited_references_are_required(self) -> None:
        self.make_inputs(reference_update=True)
        before = (self.repo / self.reference_two).read_bytes()
        after = before + b"Another synthetic rule.\n"
        self.packet["edits"].append({"path": self.reference_two, "role": "reference", "operation": "replace",
                                     "before_digest": sha(before), "after_digest": sha(after), "content": after.decode()})
        self.packet["rollback"]["path_digests"][self.reference_two] = sha(before)
        auth = {"schema_version": 1, "change_digest": MAT.digest_json(self.packet), "base_commit": self.base,
                "scope": "isolated-owner-local-patch-only", "decision": "approved",
                "reviewed_by": "fixture-reviewer", "reviewed_at": "2026-08-23T00:00:00Z"}
        materialization_dir = self.root / "materialization-two-refs"
        MAT.materialize_change(self.packet, auth, repository=self.repo, output_dir=materialization_dir,
                               policy={"materialization": {"maximum_changed_files": 5, "maximum_total_bytes": 131072,
                                                           "allowed_roles": ["skill", "reference", "registry", "test", "documentation"]}})
        self.packet_path = private(self.inputs / "packet.json", MAT.canonical_json(self.packet).encode())
        self.receipt_path = materialization_dir / "materialization-receipt.json"
        self.patch_path = materialization_dir / "capability-change.patch"
        for field, path in (("candidate_packet", self.packet_path), ("materialization", self.receipt_path), ("patch", self.patch_path)):
            self.manifest[field] = {"path": str(path), "sha256": sha(path.read_bytes())}
        with self.assertRaisesRegex(GEN.GenerationError, "instruction_paths_incomplete"):
            self.prepare()

    def test_two_html_outputs_and_zero_call_resume(self) -> None:
        runner = FakeCodex()
        receipt = self.execute(runner)
        self.assertEqual("generated_quarantined", receipt["status"])
        self.assertEqual(2, len(runner.provider_calls))
        self.assertEqual(receipt, self.execute(runner))
        self.assertEqual(2, len(runner.provider_calls))
        for argv, prompt, env in runner.provider_calls:
            self.assertIn("--ignore-user-config", argv)
            self.assertIn("read-only", argv)
            self.assertIn("--output-schema", argv)
            for secret in ("HOME", "CODEX_HOME", "OPENAI_API_KEY"):
                self.assertNotIn(secret, env)
            self.assertIsInstance(prompt, bytes)
        self.assertEqual({"baseline", "candidate"}, {row["variant"] for row in receipt["outputs"]})
        self.assertTrue(all(row["observed_model"] is None for row in receipt["outputs"]))
        self.assertEqual("not_evaluated", receipt["evaluation_status"])

    def test_target_dirty_patch_tamper_and_manifest_scope_fail(self) -> None:
        (self.repo / self.skill).write_text("Changed by user.\n")
        with self.assertRaises(GEN.GenerationError):
            self.prepare()
        (self.repo / self.skill).write_bytes(subprocess.check_output(["git", "-C", str(self.repo), "show", f"{self.base}:{self.skill}"]))
        self.patch_path.write_bytes(self.patch_path.read_bytes() + b"extra")
        self.patch_path.chmod(0o600)
        self.manifest["patch"]["sha256"] = sha(self.patch_path.read_bytes())
        with self.assertRaises(GEN.GenerationError):
            self.prepare()

    def test_missing_instruction_and_private_task_fail(self) -> None:
        original = self.manifest["instruction_paths"]
        self.manifest["instruction_paths"] = []
        with self.assertRaises(GEN.GenerationError):
            self.prepare()
        self.manifest["instruction_paths"] = original
        self.manifest["task"]["text"] = "Use my /Users/fixture/private data"
        with self.assertRaises(GEN.GenerationError):
            self.prepare()

    def test_symlinked_input_parent_and_base_blob_drift_fail(self) -> None:
        alias = self.root / "input-alias"
        alias.symlink_to(self.inputs, target_is_directory=True)
        with self.assertRaisesRegex(GEN.GenerationError, "manifest"):
            GEN.prepare_generation(alias / "generation.json", self.save_manifest(), self.repo)
        real_git = GEN._git_bytes

        def changed_blob(repository, args, **kwargs):
            if args[0] == "show":
                return b"unreviewed bytes"
            return real_git(repository, args, **kwargs)

        with patch.object(GEN, "_git_bytes", side_effect=changed_blob):
            with self.assertRaisesRegex(GEN.GenerationError, "base_blob_mismatch"):
                self.prepare()

    def test_auth_tools_multiple_messages_unsafe_html_and_unknown_event_fail(self) -> None:
        with self.assertRaisesRegex(GEN.GenerationError, "chatgpt_auth_required"):
            self.execute(FakeCodex(auth=b"Logged in using API key\n"))
        for payload in (events("<html><body>x</body></html>", tool=True),
                        events("<html><body>x</body></html>", multiple=True),
                        events("<html><body><img src='https://example.invalid/x'></body></html>"),
                        b'{"type":"unexpected"}\n'):
            with self.subTest(payload=payload[:35]), self.assertRaises(GEN.GenerationError):
                GEN._parse_events(payload)

    def test_uncertain_attempt_blocks_replay_and_hides_raw_stderr(self) -> None:
        runner = FakeCodex(bad=b"secret raw output should never leak")
        with self.assertRaises(GEN.GenerationError) as first:
            self.execute(runner)
        self.assertNotIn("secret", str(first.exception))
        self.assertEqual(1, len(runner.provider_calls))
        with self.assertRaisesRegex(GEN.GenerationError, "attempt_started_reconciliation_required"):
            self.execute(runner)
        self.assertEqual(1, len(runner.provider_calls))

    def test_input_helper_drift_and_foreign_state_block(self) -> None:
        self.execute(FakeCodex())
        self.manifest["task"]["text"] = "Another public synthetic dashboard."
        with self.assertRaises(GEN.GenerationError):
            self.execute(FakeCodex())
        self.manifest["task"]["text"] = "Build a public synthetic dashboard."
        old = GEN.LOADED_HELPERS
        try:
            GEN.LOADED_HELPERS = dict(old) | {"policy": "0" * 64}
            with self.assertRaisesRegex(GEN.GenerationError, "helper_drift"):
                self.prepare()
        finally:
            GEN.LOADED_HELPERS = old
        state_dir = self.root / "foreign"
        state_dir.mkdir(mode=0o700)
        store = GEN._store.WorkflowStore(state_dir / "workflow.sqlite3")
        store.create_run("other", "foreign", "foreign", "foreign", approval_required=False)
        store.close()
        with self.assertRaisesRegex(GEN.GenerationError, "workflow_state_foreign"):
            GEN.execute_generation(self.manifest_path, self.save_manifest(), self.repo, state_dir, runner=FakeCodex())

    def test_completed_html_tamper_and_execution_lock_block(self) -> None:
        self.execute(FakeCodex())
        artifact = self.output / "artifacts/baseline.html"
        artifact.write_text("<html><body>tampered</body></html>")
        artifact.chmod(0o600)
        with self.assertRaises(GEN.GenerationError):
            self.execute(FakeCodex())
        other = self.root / "locked"
        other.mkdir(mode=0o700)
        descriptor = GEN._collector._acquire_execution_lock(other)
        try:
            with self.assertRaisesRegex(GEN.GenerationError, "workflow_execution_locked_or_invalid"):
                GEN.execute_generation(self.manifest_path, self.save_manifest(), self.repo, other, runner=FakeCodex())
        finally:
            GEN._collector._release_execution_lock(descriptor)

    def test_timeout_kills_owned_process_group_without_model(self) -> None:
        actual_killpg = os.killpg
        killed = []

        def record_killpg(pid, sig):
            killed.append((pid, sig))
            return actual_killpg(pid, sig)

        with patch.object(GEN.os, "killpg", side_effect=record_killpg):
            with self.assertRaisesRegex(GEN.GenerationError, "provider_timeout"):
                GEN._call_runner(subprocess.run, [sys.executable, "-c", "import time; time.sleep(5)"],
                                 prompt=b"public", cwd=self.root, timeout=1, ensure_lease=lambda: None)
        self.assertEqual(1, len(killed))
        self.assertEqual(signal.SIGKILL, killed[0][1])

    def test_real_process_success_streams_prompt_and_renews_lease(self) -> None:
        prompt = b"public synthetic prompt\n" * 4096
        renewals = []
        result = GEN._call_runner(
            subprocess.run,
            [sys.executable, "-c", "import sys; data=sys.stdin.buffer.read(); "
             "sys.stderr.buffer.write(b'public diagnostic'); "
             "sys.stdout.buffer.write(data)"],
            prompt=prompt, cwd=self.root, timeout=10,
            ensure_lease=lambda: renewals.append(True),
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual(prompt, result.stdout)
        self.assertEqual(b"", result.stderr)
        self.assertGreaterEqual(len(renewals), 2)

    def test_real_process_limits_output_and_stops_on_lease_loss(self) -> None:
        for script, expected in (
            ("import sys; sys.stdout.buffer.write(b'x'*1000001)", "provider_output_limit"),
            ("import sys; sys.stderr.buffer.write(b'x'*65537)", "provider_output_limit"),
        ):
            with self.subTest(expected=script), self.assertRaisesRegex(GEN.GenerationError, expected):
                GEN._call_runner(subprocess.run, [sys.executable, "-c", script],
                                 prompt=b"public", cwd=self.root, timeout=10,
                                 ensure_lease=lambda: None)

        def lost_lease():
            raise GEN.GenerationError("workflow_child_lease_lost")

        with self.assertRaisesRegex(GEN.GenerationError, "workflow_child_lease_lost"):
            GEN._call_runner(subprocess.run, [sys.executable, "-c", "import time; time.sleep(5)"],
                             prompt=b"public", cwd=self.root, timeout=10, ensure_lease=lost_lease)

    def test_static_html_rejects_scripts_and_inserts_network_denial(self) -> None:
        document = "<html><head><style>p{color:blue}</style></head><body><p>Public</p></body></html>"
        guarded = GEN._validate_html(document)
        self.assertIn(b"default-src 'none'", guarded)
        self.assertLess(guarded.index(b"Content-Security-Policy"), guarded.index(b"<style>"))
        self.assertEqual(guarded, GEN._validate_html(guarded.decode()))
        computed_request = "<html><head></head><body><script>new Image().src='ht'+'tps:'+'/'+'/example.invalid';</script></body></html>"
        with self.assertRaises(GEN.GenerationError):
            GEN._validate_html(computed_request)

    def test_static_html_rejects_ambiguous_prefixes_and_active_elements(self) -> None:
        for document in (
            "<!--><html><head></head><body>Public</body></html>",
            "<!-- Public --><html><head></head><body>Public</body></html>",
            "<?public?><html><head></head><body>Public</body></html>",
            "<html><body><head></head>Public</body></html>",
            "<html><head></head><body><svg></svg></body></html>",
            '<html><head><meta http-equiv="refresh" content="0"></head><body>Public</body></html>',
            '<html><head></head><body><button onclick="alert(1)">Public</button></body></html>',
        ):
            with self.subTest(document=document), self.assertRaises(GEN.GenerationError):
                GEN._validate_html(document)

    def test_malformed_comments_cannot_hide_refresh_or_scripts(self) -> None:
        for hidden in (
            '<meta http-equiv=refresh content="0;url=&#x68;ttps:&#x2f;&#x2f;example.invalid/ping">',
            '<script>alert(1)</script>',
        ):
            document = f"<html><head><!-->{hidden}--></head><body>Public</body></html>"
            with self.subTest(hidden=hidden), self.assertRaises(GEN.GenerationError):
                GEN._validate_html(document)

    def test_rejected_release_event_shapes_have_content_free_reasons(self) -> None:
        prefix = [{"type": "thread.started", "thread_id": "synthetic-thread"}, {"type": "turn.started"}]
        for event, expected in (
            ({"type": "error", "message": "not-a-real-private-provider-message"}, "provider_stream_error"),
            ({"type": "turn.failed", "error": {"message": "not-a-real-private-provider-message"}}, "provider_turn_failed"),
            ({"type": "item.completed", "item": {"type": "error", "message": "not-a-real-private-provider-message"}}, "provider_item_error"),
            ({"type": "item.updated", "item": {"type": "todo_list", "items": []}}, "tool_item"),
            ({"type": "item.updated", "item": {"type": "agent_message", "text": "Public"}}, "invalid_agent_message_lifecycle"),
            ({"type": "not-a-real-private-event-name"}, "unknown_event_or_order"),
            ({"type": "item.completed", "item": {"type": "not-a-real-private-item-name"}}, "unknown_item"),
        ):
            payload = b"\n".join(json.dumps(row).encode() for row in [*prefix, event])
            with self.subTest(reason=expected), self.assertRaises(GEN.GenerationError) as caught:
                GEN._parse_events(payload)
            self.assertEqual("provider_tool_or_output_rejected", caught.exception.code)
            self.assertEqual(expected, caught.exception.reason)
            self.assertNotIn("not-a-real", str(caught.exception))

    def test_unapproved_diagnostic_reason_is_never_exposed(self) -> None:
        error = GEN.GenerationError("provider_tool_or_output_rejected", reason="not-a-real-private-event-name")
        self.assertIsNone(error.reason)

    def test_multiple_schema_shaped_messages_still_fail(self) -> None:
        html = "<html><head></head><body>Public</body></html>"
        with self.assertRaises(GEN.GenerationError) as caught:
            GEN._parse_events(events(html, multiple=True))
        self.assertEqual("multiple_agent_messages", caught.exception.reason)

    def test_receipts_separate_provider_and_guarded_html_digests(self) -> None:
        runner = FakeCodex()
        receipt = self.execute(runner)
        for output in receipt["outputs"]:
            original = f'<!doctype html><html><head></head><body><h1>{output["variant"]}</h1></body></html>'
            self.assertEqual(sha(original.encode()), output["provider_html_sha256"])
            guarded = (self.output / "artifacts" / f'{output["variant"]}.html').read_bytes()
            self.assertEqual(sha(guarded), output["html_sha256"])
            self.assertNotEqual(output["provider_html_sha256"], output["html_sha256"])
            self.assertEqual(GEN.HTML_POLICY_REVISION, output["html_policy_revision"])

    def test_verified_final_receipt_recovers_failed_and_expired_child(self) -> None:
        runner = FakeCodex()
        receipt = self.execute(runner)
        for state, run_state, expires in (("failed", "blocked", None), ("leased", "dispatched", 0)):
            store = GEN._store.WorkflowStore(self.output / "workflow.sqlite3")
            store.conn.execute("UPDATE children SET status=?, lease_owner='abandoned', lease_expires_at=?", (state, expires))
            store.conn.execute("UPDATE runs SET status=?", (run_state,))
            store.conn.commit()
            store.close()
            self.assertEqual(receipt, self.execute(runner))
            self.assertEqual(2, len(runner.provider_calls))

        store = GEN._store.WorkflowStore(self.output / "workflow.sqlite3")
        store.conn.execute("UPDATE children SET status='leased', lease_owner='live', lease_expires_at=?", (time.time() + 300,))
        store.conn.execute("UPDATE runs SET status='dispatched'")
        store.conn.commit()
        store.close()
        with self.assertRaisesRegex(GEN.GenerationError, "workflow_child_lease_unavailable"):
            self.execute(runner)
        self.assertEqual(2, len(runner.provider_calls))

    def test_interruption_before_final_child_completion_is_zero_call_recovery(self) -> None:
        runner = FakeCodex()
        original_finish = GEN._store.WorkflowStore.finish_child

        def interrupt_finish(store, run_id, child_id, lease_owner, **kwargs):
            if not kwargs.get("failed", False):
                raise KeyboardInterrupt
            return original_finish(store, run_id, child_id, lease_owner, **kwargs)

        with patch.object(GEN._store.WorkflowStore, "finish_child", interrupt_finish):
            with self.assertRaisesRegex(GEN.GenerationError, "run_interrupted"):
                self.execute(runner)
        self.assertEqual(2, len(runner.provider_calls))
        self.assertEqual("generated_quarantined", self.execute(runner)["status"])
        self.assertEqual(2, len(runner.provider_calls))

    def test_interruption_before_final_checkpoint_reuses_identical_receipt(self) -> None:
        runner = FakeCodex()
        original_checkpoint = GEN._store.WorkflowStore.checkpoint

        def interrupt_final(store, run_id, child_id, lease_owner, encoded):
            if json.loads(encoded)["kind"] == "final":
                raise KeyboardInterrupt
            return original_checkpoint(store, run_id, child_id, lease_owner, encoded)

        with patch.object(GEN._store.WorkflowStore, "checkpoint", interrupt_final):
            with self.assertRaisesRegex(GEN.GenerationError, "run_interrupted"):
                self.execute(runner)
        saved = (self.output / "run-receipt.json").read_bytes()
        self.assertEqual(2, len(runner.provider_calls))
        self.assertEqual("generated_quarantined", self.execute(runner)["status"])
        self.assertEqual(saved, (self.output / "run-receipt.json").read_bytes())
        self.assertEqual(2, len(runner.provider_calls))

    def test_completed_baseline_survives_interruption_before_candidate(self) -> None:
        class InterruptedBeforeCandidate(FakeCodex):
            auth_calls = 0

            def __call__(self, argv, **kwargs):
                if argv[1:3] == ["login", "status"]:
                    self.auth_calls += 1
                    if self.auth_calls == 2:
                        raise KeyboardInterrupt
                return super().__call__(argv, **kwargs)

        runner = InterruptedBeforeCandidate()
        with self.assertRaisesRegex(GEN.GenerationError, "run_interrupted"):
            self.execute(runner)
        baseline_sha = sha((self.output / "artifacts/baseline.html").read_bytes())
        self.assertEqual(1, len(runner.provider_calls))
        receipt = self.execute(runner)
        self.assertEqual(2, len(runner.provider_calls))
        self.assertEqual(baseline_sha, receipt["outputs"][0]["html_sha256"])

    def test_periodic_lease_loss_terminates_an_in_flight_process(self) -> None:
        clock = [0]
        renewals = []

        def advance():
            clock[0] += 21
            return clock[0]

        def renew():
            renewals.append(True)
            if len(renewals) == 2:
                raise GEN.GenerationError("workflow_child_lease_lost")

        with patch.object(GEN.time, "monotonic", advance):
            with self.assertRaisesRegex(GEN.GenerationError, "workflow_child_lease_lost"):
                GEN._call_runner(subprocess.run, [sys.executable, "-c", "import time; time.sleep(5)"],
                                 prompt=b"public", cwd=self.root, timeout=300, ensure_lease=renew)
        self.assertEqual(2, len(renewals))


if __name__ == "__main__":
    unittest.main()
