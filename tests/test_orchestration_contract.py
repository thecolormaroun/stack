"""Focused behavior tests for the durable, local Stack orchestration contract."""
from __future__ import annotations

import importlib.util
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("stack_run_state", ROOT / "scripts" / "stack-run-state.py")
assert SPEC and SPEC.loader
STATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATE)


class OrchestrationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "runs.sqlite3"
        self.store = STATE.WorkflowStore(self.db)
        self.store.create_run("run-1", "project:example", "owner", "/project", max_children=2)
        self.store.add_child("run-1", "child-1", "implement", "codex", "worker", "/project", worktree="/project-wt")

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_concurrent_lease_claims_have_one_winner(self) -> None:
        barrier = threading.Barrier(2)
        results: list[bool] = []

        def claim(owner: str) -> None:
            store = STATE.WorkflowStore(self.db)
            try:
                barrier.wait()
                results.append(store.claim_child("run-1", "child-1", owner))
            finally:
                store.close()

        first = threading.Thread(target=claim, args=("adapter-a",))
        second = threading.Thread(target=claim, args=("adapter-b",))
        first.start(); second.start(); first.join(); second.join()
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 1)

    def test_stale_lease_recovers_without_duplication(self) -> None:
        self.assertTrue(self.store.claim_child("run-1", "child-1", "old", lease_seconds=1, now=100))
        self.assertTrue(self.store.claim_child("run-1", "child-1", "new", lease_seconds=30, now=102))
        child = self.store.snapshot("run-1")["children"][0]
        self.assertEqual(child["lease_owner"], "new")
        self.assertEqual(len(self.store.snapshot("run-1")["children"]), 1)

    def test_completed_child_is_idempotent_and_cannot_be_reclaimed(self) -> None:
        self.assertTrue(self.store.claim_child("run-1", "child-1", "worker"))
        self.store.checkpoint("run-1", "child-1", "worker", "docs/plan.md")
        self.store.finish_child("run-1", "child-1", "worker")
        self.assertFalse(self.store.claim_child("run-1", "child-1", "other"))
        with self.assertRaisesRegex(STATE.RunStateError, "already exists"):
            self.store.add_child("run-1", "child-1", "implement", "codex", "other", "/project")

    def test_failed_child_blocks_ship_gate(self) -> None:
        self.assertTrue(self.store.claim_child("run-1", "child-1", "worker"))
        self.store.finish_child("run-1", "child-1", "worker", failed=True, failure="test failure")
        self.store.set_gate("run-1", "review", "passed", "review.md")
        self.store.set_gate("run-1", "qa", "passed", "qa.md")
        with self.assertRaisesRegex(STATE.RunStateError, "ship is blocked"):
            self.store.set_gate("run-1", "ship", "passed", "ship.md")
        self.assertEqual(self.store.snapshot("run-1")["status"], "verified")

    def test_cancel_and_resume_release_child_for_reclaim(self) -> None:
        self.assertTrue(self.store.claim_child("run-1", "child-1", "worker"))
        self.store.cancel("run-1", "stop requested")
        self.assertEqual(self.store.snapshot("run-1")["status"], "cancelled")
        self.store.resume("run-1")
        self.assertTrue(self.store.claim_child("run-1", "child-1", "replacement"))

    def test_terminal_receipt_captures_gates_and_is_immutable(self) -> None:
        self.assertTrue(self.store.claim_child("run-1", "child-1", "worker"))
        self.store.finish_child("run-1", "child-1", "worker")
        self.store.set_gate("run-1", "review", "passed", "review.md")
        self.store.set_gate("run-1", "qa", "passed", "qa.md")
        self.store.set_gate("run-1", "ship", "passed", "ship.md")
        self.store.approve("run-1", True)
        self.store.ship("run-1")
        receipt = self.store.receipt("run-1")
        self.assertEqual(receipt["status"], "shipped")
        self.assertEqual(receipt["gates"]["qa"]["evidence"], "qa.md")
        self.assertEqual(self.store.snapshot("run-1")["status"], "receipted")
        with self.assertRaisesRegex(STATE.RunStateError, "immutable"):
            self.store.resume("run-1")

    def test_bounded_non_nested_fanout(self) -> None:
        self.store.add_child("run-1", "child-2", "review", "claude", "reviewer", "/project")
        with self.assertRaisesRegex(STATE.RunStateError, "bounded fan-out"):
            self.store.add_child("run-1", "child-3", "qa", "codex", "qa", "/project")
        with self.assertRaisesRegex(STATE.RunStateError, "nested"):
            self.store.add_child("run-1", "nested", "subtask", "codex", "worker", "/project", parent_child_id="child-1")

    def test_secure_state_files_ignore_ordinary_umask(self) -> None:
        self.store.close()
        secure_parent = Path(self.tmp.name) / "state"
        secure_database = secure_parent / "runs.sqlite3"
        old_umask = os.umask(0o022)
        try:
            self.store = STATE.WorkflowStore(secure_database)
            self.store.create_run("secure-run", "project:secure", "owner", "/project")
        finally:
            os.umask(old_umask)

        self.assertEqual(stat.S_IMODE(secure_parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(secure_database.stat().st_mode), 0o600)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{secure_database}{suffix}")
            self.assertTrue(sidecar.is_file())
            self.assertEqual(stat.S_IMODE(sidecar.stat().st_mode), 0o600)

    def test_symlink_parent_and_database_are_rejected(self) -> None:
        real_parent = Path(self.tmp.name) / "real"
        real_parent.mkdir(mode=0o700)
        linked_parent = Path(self.tmp.name) / "linked"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        with self.assertRaisesRegex(STATE.RunStateError, "parent must not be a symlink"):
            STATE.WorkflowStore(linked_parent / "runs.sqlite3")

        target = real_parent / "target.sqlite3"
        target.touch(mode=0o600)
        linked_database = real_parent / "linked.sqlite3"
        linked_database.symlink_to(target)
        with self.assertRaisesRegex(STATE.RunStateError, "database must not be a symlink"):
            STATE.WorkflowStore(linked_database)

    def test_wrong_parent_or_database_mode_is_rejected(self) -> None:
        loose_parent = Path(self.tmp.name) / "loose-parent"
        loose_parent.mkdir(mode=0o755)
        with self.assertRaisesRegex(STATE.RunStateError, "parent mode must be 0700"):
            STATE.WorkflowStore(loose_parent / "runs.sqlite3")

        secure_parent = Path(self.tmp.name) / "secure-parent"
        secure_parent.mkdir(mode=0o700)
        loose_database = secure_parent / "runs.sqlite3"
        loose_database.touch(mode=0o644)
        with self.assertRaisesRegex(STATE.RunStateError, "database mode must be 0600"):
            STATE.WorkflowStore(loose_database)

        sidecar_parent = Path(self.tmp.name) / "sidecar-parent"
        sidecar_database = sidecar_parent / "runs.sqlite3"
        sidecar_store = STATE.WorkflowStore(sidecar_database)
        sidecar_store.close()
        loose_sidecar = Path(f"{sidecar_database}-wal")
        loose_sidecar.touch(mode=0o644)
        with self.assertRaisesRegex(STATE.RunStateError, "wal sidecar mode must be 0600"):
            STATE.WorkflowStore(sidecar_database)

    def test_state_owned_by_another_user_is_rejected(self) -> None:
        state_parent = Path(self.tmp.name) / "owned-state"
        state_parent.mkdir(mode=0o700)
        with mock.patch.object(STATE.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaisesRegex(STATE.RunStateError, "owned by the current user"):
                STATE.WorkflowStore(state_parent / "runs.sqlite3")


if __name__ == "__main__":
    unittest.main()
