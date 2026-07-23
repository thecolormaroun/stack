#!/usr/bin/env python3
"""Local, runtime-neutral control store for Stack orchestration runs.

This intentionally manages only durable coordination metadata. Plans, patches,
and evidence remain project artifacts named by the records below.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import stat
import time
from pathlib import Path
from typing import Any


RUN_STATES = {"planned", "dispatched", "implemented", "blocked", "reviewed", "verified", "awaiting_approval", "shipped", "cancelled", "receipted"}
TERMINAL_FOR_RECEIPT = {"shipped", "cancelled"}
GATES = {"review", "qa", "ship"}
MAX_CHILDREN = 16


class RunStateError(ValueError):
    """A requested lifecycle transition violates the shared contract."""


class WorkflowStore:
    def __init__(self, database: str | Path):
        database_path = Path(database)
        self._prepare_database(database_path)
        self.database = str(database_path)
        self.conn = sqlite3.connect(self.database, timeout=5, isolation_level=None)
        try:
            self._verify_file(database_path, 0o600, "workflow database")
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA journal_mode = WAL")
            self._migrate()
            self._secure_sidecars(database_path)
        except Exception:
            self.conn.close()
            raise

    @staticmethod
    def _verify_file(path: Path, expected_mode: int, label: str) -> None:
        try:
            metadata = path.lstat()
        except FileNotFoundError as exc:
            raise RunStateError(f"{label} does not exist: {path}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise RunStateError(f"{label} must not be a symlink: {path}")
        if not stat.S_ISREG(metadata.st_mode):
            raise RunStateError(f"{label} must be a regular file: {path}")
        if metadata.st_uid != os.getuid():
            raise RunStateError(f"{label} must be owned by the current user: {path}")
        actual_mode = stat.S_IMODE(metadata.st_mode)
        if actual_mode != expected_mode:
            raise RunStateError(f"{label} mode must be {expected_mode:04o}, found {actual_mode:04o}: {path}")

    @staticmethod
    def _verify_parent(path: Path) -> None:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            path.mkdir(parents=True, mode=0o700)
            metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise RunStateError(f"workflow state parent must not be a symlink: {path}")
        if not stat.S_ISDIR(metadata.st_mode):
            raise RunStateError(f"workflow state parent must be a directory: {path}")
        if metadata.st_uid != os.getuid():
            raise RunStateError(f"workflow state parent must be owned by the current user: {path}")
        actual_mode = stat.S_IMODE(metadata.st_mode)
        if actual_mode != 0o700:
            raise RunStateError(f"workflow state parent mode must be 0700, found {actual_mode:04o}: {path}")

    @classmethod
    def _prepare_database(cls, path: Path) -> None:
        cls._verify_parent(path.parent)
        if path.is_symlink():
            raise RunStateError(f"workflow database must not be a symlink: {path}")
        if not path.exists():
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(path, flags, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
        cls._verify_file(path, 0o600, "workflow database")
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{path}{suffix}")
            if sidecar.exists() or sidecar.is_symlink():
                cls._verify_file(sidecar, 0o600, f"SQLite {suffix[1:]} sidecar")

    @classmethod
    def _secure_sidecars(cls, database: Path) -> None:
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{database}{suffix}")
            if not sidecar.exists() and not sidecar.is_symlink():
                continue
            cls._verify_file(sidecar, stat.S_IMODE(sidecar.lstat().st_mode), f"SQLite {suffix[1:]} sidecar")
            os.chmod(sidecar, 0o600, follow_symlinks=False)
            cls._verify_file(sidecar, 0o600, f"SQLite {suffix[1:]} sidecar")

    def close(self) -> None:
        self.conn.close()

    def _migrate(self) -> None:
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
          run_id TEXT PRIMARY KEY, project_identity TEXT NOT NULL, owner TEXT NOT NULL,
          workspace TEXT NOT NULL, worktree TEXT, status TEXT NOT NULL,
          max_children INTEGER NOT NULL, approval_required INTEGER NOT NULL,
          approval_state TEXT NOT NULL DEFAULT 'pending', created_at REAL NOT NULL, updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS children (
          run_id TEXT NOT NULL REFERENCES runs(run_id), child_id TEXT NOT NULL,
          role TEXT NOT NULL, model_role TEXT NOT NULL, owner TEXT NOT NULL,
          workspace TEXT NOT NULL, worktree TEXT, status TEXT NOT NULL DEFAULT 'pending',
          checkpoint_json TEXT NOT NULL DEFAULT '[]', failure TEXT,
          lease_owner TEXT, lease_expires_at REAL, PRIMARY KEY(run_id, child_id)
        );
        CREATE TABLE IF NOT EXISTS gates (
          run_id TEXT NOT NULL REFERENCES runs(run_id), gate TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending', evidence TEXT, updated_at REAL NOT NULL,
          PRIMARY KEY(run_id, gate)
        );
        CREATE TABLE IF NOT EXISTS receipts (
          receipt_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id),
          terminal_state TEXT NOT NULL, payload_json TEXT NOT NULL, created_at REAL NOT NULL
        );
        """)

    def _transaction(self):
        self.conn.execute("BEGIN IMMEDIATE")

    def _run(self, run_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if not row:
            raise RunStateError(f"unknown run: {run_id}")
        return row

    def create_run(self, run_id: str, project_identity: str, owner: str, workspace: str, *, worktree: str | None = None, max_children: int = 4, approval_required: bool = True) -> dict[str, Any]:
        if not run_id or not project_identity or not owner or not workspace:
            raise RunStateError("run_id, project_identity, owner, and workspace are required")
        if not 1 <= max_children <= MAX_CHILDREN:
            raise RunStateError(f"max_children must be between 1 and {MAX_CHILDREN}")
        now = time.time()
        try:
            self.conn.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, 'planned', ?, ?, ?, ?, ?)",
                              (run_id, project_identity, owner, workspace, worktree, max_children, int(approval_required), "pending" if approval_required else "not_required", now, now))
        except sqlite3.IntegrityError as exc:
            raise RunStateError(f"run already exists: {run_id}") from exc
        for gate in sorted(GATES):
            self.conn.execute("INSERT INTO gates VALUES (?, ?, 'pending', NULL, ?)", (run_id, gate, now))
        return self.snapshot(run_id)

    def add_child(self, run_id: str, child_id: str, role: str, model_role: str, owner: str, workspace: str, *, worktree: str | None = None, parent_child_id: str | None = None) -> dict[str, Any]:
        if parent_child_id:
            raise RunStateError("children cannot create nested children; fan-out belongs to the run owner")
        self._transaction()
        try:
            run = self._run(run_id)
            count = self.conn.execute("SELECT count(*) FROM children WHERE run_id = ?", (run_id,)).fetchone()[0]
            if count >= run["max_children"]:
                raise RunStateError("bounded fan-out exceeded")
            try:
                self.conn.execute("INSERT INTO children(run_id, child_id, role, model_role, owner, workspace, worktree) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                  (run_id, child_id, role, model_role, owner, workspace, worktree))
            except sqlite3.IntegrityError as exc:
                raise RunStateError(f"child already exists: {child_id}") from exc
            self.conn.execute("UPDATE runs SET status = 'dispatched', updated_at = ? WHERE run_id = ? AND status = 'planned'", (time.time(), run_id))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return self.snapshot(run_id)

    def claim_child(self, run_id: str, child_id: str, lease_owner: str, *, lease_seconds: int = 300, now: float | None = None) -> bool:
        if lease_seconds <= 0:
            raise RunStateError("lease_seconds must be positive")
        now = time.time() if now is None else now
        self._transaction()
        try:
            run = self._run(run_id)
            if run["status"] in {"cancelled", "receipted", "shipped"}:
                self.conn.rollback()
                return False
            # Recovery and claiming occur in one writer transaction, so exactly one adapter wins.
            self.conn.execute("UPDATE children SET status = 'pending', lease_owner = NULL, lease_expires_at = NULL WHERE run_id = ? AND status = 'leased' AND lease_expires_at <= ?", (run_id, now))
            updated = self.conn.execute("UPDATE children SET status = 'leased', lease_owner = ?, lease_expires_at = ? WHERE run_id = ? AND child_id = ? AND status = 'pending'", (lease_owner, now + lease_seconds, run_id, child_id)).rowcount
            self.conn.commit()
            return bool(updated)
        except Exception:
            self.conn.rollback()
            raise

    def checkpoint(self, run_id: str, child_id: str, lease_owner: str, artifact: str) -> None:
        self._transaction()
        try:
            row = self.conn.execute("SELECT checkpoint_json FROM children WHERE run_id = ? AND child_id = ? AND status = 'leased' AND lease_owner = ?", (run_id, child_id, lease_owner)).fetchone()
            if not row:
                raise RunStateError("checkpoint requires the active child lease")
            checkpoints = json.loads(row[0]); checkpoints.append(artifact)
            self.conn.execute("UPDATE children SET checkpoint_json = ? WHERE run_id = ? AND child_id = ?", (json.dumps(checkpoints), run_id, child_id))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def finish_child(self, run_id: str, child_id: str, lease_owner: str, *, failed: bool = False, failure: str | None = None) -> None:
        self._transaction()
        try:
            status = "failed" if failed else "completed"
            updated = self.conn.execute("UPDATE children SET status = ?, failure = ?, lease_owner = NULL, lease_expires_at = NULL WHERE run_id = ? AND child_id = ? AND status = 'leased' AND lease_owner = ?", (status, failure, run_id, child_id, lease_owner)).rowcount
            if not updated:
                raise RunStateError("finish requires the active child lease")
            if not failed and not self.conn.execute("SELECT 1 FROM children WHERE run_id = ? AND status NOT IN ('completed', 'cancelled')", (run_id,)).fetchone():
                self.conn.execute("UPDATE runs SET status = 'implemented', updated_at = ? WHERE run_id = ?", (time.time(), run_id))
            elif failed:
                self.conn.execute("UPDATE runs SET status = 'blocked', updated_at = ? WHERE run_id = ?", (time.time(), run_id))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def set_gate(self, run_id: str, gate: str, status: str, evidence: str) -> None:
        if gate not in GATES or status not in {"passed", "failed"}:
            raise RunStateError("gate must be review, qa, or ship with passed or failed status")
        self._transaction()
        try:
            self._run(run_id)
            if gate == "ship":
                failures = self.conn.execute("SELECT 1 FROM children WHERE run_id = ? AND status = 'failed'", (run_id,)).fetchone()
                preceding = self.conn.execute("SELECT count(*) FROM gates WHERE run_id = ? AND gate IN ('review', 'qa') AND status = 'passed'", (run_id,)).fetchone()[0]
                if status == "passed" and (failures or preceding != 2):
                    raise RunStateError("ship is blocked until all children succeed and review and qa pass")
            self.conn.execute("UPDATE gates SET status = ?, evidence = ?, updated_at = ? WHERE run_id = ? AND gate = ?", (status, evidence, time.time(), run_id, gate))
            run_status = {"review": "reviewed", "qa": "verified"}.get(gate)
            if status == "passed" and run_status:
                self.conn.execute("UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?", (run_status, time.time(), run_id))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def approve(self, run_id: str, approved: bool) -> None:
        self._transaction()
        try:
            run = self._run(run_id)
            if not run["approval_required"]:
                raise RunStateError("this run has no approval gate")
            ship_gate = self.conn.execute("SELECT status FROM gates WHERE run_id = ? AND gate = 'ship'", (run_id,)).fetchone()[0]
            if approved and ship_gate != "passed":
                raise RunStateError("approval waits for a passed ship gate")
            self.conn.execute("UPDATE runs SET approval_state = ?, status = ?, updated_at = ? WHERE run_id = ?", ("approved" if approved else "declined", "awaiting_approval" if approved else "cancelled", time.time(), run_id))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def ship(self, run_id: str) -> None:
        self._transaction()
        try:
            run = self._run(run_id)
            gate = self.conn.execute("SELECT status FROM gates WHERE run_id = ? AND gate = 'ship'", (run_id,)).fetchone()[0]
            if gate != "passed" or (run["approval_required"] and run["approval_state"] != "approved"):
                raise RunStateError("ship requires a passed ship gate and explicit approval")
            self.conn.execute("UPDATE runs SET status = 'shipped', updated_at = ? WHERE run_id = ?", (time.time(), run_id))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def cancel(self, run_id: str, reason: str = "cancelled") -> None:
        self._transaction()
        try:
            self._run(run_id)
            self.conn.execute("UPDATE children SET status = 'cancelled', failure = ?, lease_owner = NULL, lease_expires_at = NULL WHERE run_id = ? AND status IN ('pending', 'leased')", (reason, run_id))
            self.conn.execute("UPDATE runs SET status = 'cancelled', updated_at = ? WHERE run_id = ?", (time.time(), run_id))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def resume(self, run_id: str) -> None:
        self._transaction()
        try:
            run = self._run(run_id)
            if run["status"] == "receipted":
                raise RunStateError("a receipted run is immutable")
            if run["status"] not in {"blocked", "cancelled"}:
                raise RunStateError("only blocked or cancelled runs can resume")
            self.conn.execute("UPDATE children SET status = 'pending', failure = NULL WHERE run_id = ? AND status IN ('failed', 'cancelled')", (run_id,))
            self.conn.execute("UPDATE runs SET status = 'dispatched', updated_at = ? WHERE run_id = ?", (time.time(), run_id))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def receipt(self, run_id: str) -> dict[str, Any]:
        self._transaction()
        try:
            run = self._run(run_id)
            if run["status"] not in TERMINAL_FOR_RECEIPT:
                raise RunStateError("only shipped or cancelled runs can receive a terminal receipt")
            payload = self.snapshot(run_id)
            self.conn.execute("INSERT INTO receipts(run_id, terminal_state, payload_json, created_at) VALUES (?, ?, ?, ?)", (run_id, run["status"], json.dumps(payload, sort_keys=True), time.time()))
            self.conn.execute("UPDATE runs SET status = 'receipted', updated_at = ? WHERE run_id = ?", (time.time(), run_id))
            self.conn.commit()
            return payload
        except Exception:
            self.conn.rollback()
            raise

    def snapshot(self, run_id: str) -> dict[str, Any]:
        run = dict(self._run(run_id))
        run["approval_required"] = bool(run["approval_required"])
        run["children"] = [dict(row) | {"checkpoints": json.loads(row["checkpoint_json"])} for row in self.conn.execute("SELECT * FROM children WHERE run_id = ? ORDER BY child_id", (run_id,))]
        for child in run["children"]:
            child.pop("checkpoint_json")
        run["gates"] = {row["gate"]: {"status": row["status"], "evidence": row["evidence"]} for row in self.conn.execute("SELECT * FROM gates WHERE run_id = ?", (run_id,))}
        receipt = self.conn.execute("SELECT receipt_id, terminal_state, created_at FROM receipts WHERE run_id = ?", (run_id,)).fetchone()
        run["receipt"] = dict(receipt) if receipt else None
        return run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("STACK_RUN_STATE_DB", str(Path.home() / ".local/state/stack/runs.sqlite3")))
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create"); create.add_argument("run_id"); create.add_argument("project_identity"); create.add_argument("owner"); create.add_argument("workspace"); create.add_argument("--worktree"); create.add_argument("--max-children", type=int, default=4); create.add_argument("--no-approval", action="store_true")
    child = sub.add_parser("add-child"); child.add_argument("run_id"); child.add_argument("child_id"); child.add_argument("role"); child.add_argument("model_role"); child.add_argument("owner"); child.add_argument("workspace"); child.add_argument("--worktree")
    claim = sub.add_parser("claim"); claim.add_argument("run_id"); claim.add_argument("child_id"); claim.add_argument("lease_owner"); claim.add_argument("--seconds", type=int, default=300)
    finish = sub.add_parser("finish"); finish.add_argument("run_id"); finish.add_argument("child_id"); finish.add_argument("lease_owner"); finish.add_argument("--failed", action="store_true"); finish.add_argument("--failure")
    gate = sub.add_parser("gate"); gate.add_argument("run_id"); gate.add_argument("gate", choices=sorted(GATES)); gate.add_argument("status", choices=["passed", "failed"]); gate.add_argument("evidence")
    approve = sub.add_parser("approve"); approve.add_argument("run_id"); approve.add_argument("--decline", action="store_true")
    cancel = sub.add_parser("cancel"); cancel.add_argument("run_id"); cancel.add_argument("--reason", default="cancelled")
    for name in ("resume", "ship", "receipt", "show"):
        item = sub.add_parser(name); item.add_argument("run_id")
    args = parser.parse_args(); store = WorkflowStore(args.db)
    try:
        if args.command == "create": result = store.create_run(args.run_id, args.project_identity, args.owner, args.workspace, worktree=args.worktree, max_children=args.max_children, approval_required=not args.no_approval)
        elif args.command == "add-child": result = store.add_child(args.run_id, args.child_id, args.role, args.model_role, args.owner, args.workspace, worktree=args.worktree)
        elif args.command == "claim": result = {"claimed": store.claim_child(args.run_id, args.child_id, args.lease_owner, lease_seconds=args.seconds)}
        elif args.command == "finish": store.finish_child(args.run_id, args.child_id, args.lease_owner, failed=args.failed, failure=args.failure); result = store.snapshot(args.run_id)
        elif args.command == "gate": store.set_gate(args.run_id, args.gate, args.status, args.evidence); result = store.snapshot(args.run_id)
        elif args.command == "approve": store.approve(args.run_id, not args.decline); result = store.snapshot(args.run_id)
        elif args.command == "cancel": store.cancel(args.run_id, args.reason); result = store.snapshot(args.run_id)
        elif args.command == "resume": store.resume(args.run_id); result = store.snapshot(args.run_id)
        elif args.command == "ship": store.ship(args.run_id); result = store.snapshot(args.run_id)
        elif args.command == "receipt": result = store.receipt(args.run_id)
        else: result = store.snapshot(args.run_id)
        print(json.dumps(result, sort_keys=True))
    except RunStateError as exc:
        parser.error(str(exc))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
