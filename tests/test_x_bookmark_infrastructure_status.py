from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "x_bookmark_infrastructure_status",
    ROOT / "scripts" / "x_bookmark_infrastructure_status.py",
)
assert SPEC and SPEC.loader
STATUS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATUS)


class BookmarkInfrastructureStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root.chmod(0o700)
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        self.sources = self.root / "sources.json"
        self.database = self.root / "bookmarks.db"
        connection = sqlite3.connect(self.database)
        connection.execute(
            "CREATE TABLE bookmarks (tweet_id TEXT, synced_at TEXT, text TEXT, media_count INTEGER)"
        )
        connection.executemany(
            "INSERT INTO bookmarks VALUES (?, ?, ?, ?)",
            [
                ("tweet-2", "2026-08-30T02:00:00Z", "private body", 2),
                ("tweet-1", "2026-08-29T02:00:00Z", "another private body", 0),
            ],
        )
        connection.commit()
        connection.close()
        self.database.chmod(0o600)
        self.receipt = (
            self.root
            / ".local"
            / "state"
            / "field-theory"
            / "refresh"
            / "field-theory-refresh-receipt.json"
        )
        self.receipt.parent.mkdir(parents=True, mode=0o700)
        for directory in (
            self.root / ".local",
            self.root / ".local" / "state",
            self.root / ".local" / "state" / "field-theory",
            self.receipt.parent,
        ):
            directory.chmod(0o700)
        self.launch_agent = self.root / "daily-maintenance.plist"
        self.launch_agent.write_bytes(
            b"<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
            b"<plist version=\"1.0\"><dict>"
            b"<key>Label</key><string>ai.hermes.daily-maintenance</string>"
            b"<key>ProgramArguments</key><array><string>/usr/bin/python3</string>"
            b"<string>mookie-daily-maintenance.py</string><string>--live</string>"
            b"<string>--only</string>"
            b"<string>field-theory-bookmarks</string></array>"
            b"<key>StartCalendarInterval</key><dict><key>Hour</key><integer>2</integer>"
            b"<key>Minute</key><integer>7</integer></dict></dict></plist>"
        )
        self.launch_agent.chmod(0o600)
        self.hold = self.state / STATUS.DEFAULT_HOLD_NAME
        self.hold.write_text(
            json.dumps(
                {
                    "schema": "gbrain-maintenance-hold/v1",
                    "active": False,
                    "handoff_status": "completed",
                }
            ),
            encoding="utf-8",
        )
        self.hold.chmod(0o600)
        self.sources.write_text(
            json.dumps(
                {
                    "sources": [
                        {
                            "id": "field-theory",
                            "adapter": "field_theory",
                            "enabled": True,
                            "paths": [str(self.database)],
                            "field_theory_contract": {
                                "freshness_receipt": str(self.receipt)
                            },
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.sources.chmod(0o600)
        self._environment = {
            "STACK_BOOKMARK_STATE_ROOT": str(self.state),
            "STACK_BOOKMARK_SOURCES": str(self.sources),
            "STACK_DAILY_LAUNCH_AGENT": str(self.launch_agent),
            "STACK_GBRAIN_HOLD_FILE": str(self.hold),
            "STACK_HERMES_CRON_JOBS": str(self.root / "jobs.json"),
            "STACK_HERMES_GATEWAY_STATE": str(self.root / "gateway.json"),
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def binding(self) -> dict[str, object]:
        return STATUS.FRESHNESS.read_database_binding(self.database)

    def write_refresh_receipt(self, *, generated_at: datetime | None = None) -> None:
        database_digest = STATUS.FRESHNESS.file_sha256(self.database)
        empty_state = {
            "md": {"exists": False, "file_count": 0, "total_size": 0, "content_hash": "", "truncated": False},
            "library": {"exists": False, "file_count": 0, "total_size": 0, "content_hash": "", "truncated": False},
            "commands": {"exists": False, "file_count": 0, "total_size": 0, "content_hash": "", "truncated": False},
            "media_cache": {"exists": False, "file_count": 0, "total_size": 0, "metadata_hash": "", "truncated": False, "transactional": True, "snapshot": "apfs_copy_on_write_clone"},
            "root_files": {"bookmarks_db": {"exists": True, "size": self.database.stat().st_size, "sha256": database_digest}},
        }
        payload = {
            "schema": STATUS.FRESHNESS.RECEIPT_SCHEMA,
            "run_id": "status-test-run",
            "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
            "outcome": "applied_verified",
            "authoritative": True,
            "deterministic_checks_passed": True,
            "source": {"id": "field-theory"},
            "database_binding": self.binding(),
            "state_binding_before": empty_state,
            "state_binding_after": empty_state,
            "media": {
                "pending_bookmark_limit": 50,
                "per_asset_max_bytes": 209715200,
                "timeout_seconds": 2700,
                "processed": 2,
                "downloaded": 2,
                "skipped_too_large": 0,
                "failed": 0,
                "budget_deferred": "bounded_unmeasured",
                "resume_manifest_present": True,
            },
            "stages": {
                "field-theory-wiki": {"state": "passed", "exit_code": 0},
                "commands_validate": {"state": "passed", "exit_code": 0},
            },
            "stage_contract": {
                "expected": ["field-theory-wiki", "commands_validate"],
                "complete": True,
                "missing": [],
                "invalid_states": [],
            },
            "safe_restart": {
                "snapshot_created": True,
                "media_cache_transactional": True,
            },
        }
        self.receipt.write_text(json.dumps(payload), encoding="utf-8")
        self.receipt.chmod(0o600)

    def write_stack_receipts(self, *, complete: bool = True) -> None:
        receipts = self.state / "receipts"
        receipts.mkdir(mode=0o700)
        for phase in ("collection", "curation"):
            path = receipts / f"{phase}-20260830T020000Z.json"
            path.write_text(
                json.dumps(
                    {
                        "receipt_type": phase,
                        "phase": phase,
                        "complete": complete,
                        "manual_run": True,
                        "mode": "apply",
                    }
                ),
                encoding="utf-8",
            )
            path.chmod(0o600)

    def write_scheduler_files(self, *, duplicate: bool = False, drifted: bool = False) -> None:
        jobs = [
            {
                "name": "stack-bookmark-collection",
                "enabled": True,
                "schedule": {"kind": "cron", "expr": "17 1 * * *" if drifted else "17 4,6 * * *"},
                "script": "stack-bookmark-collection.sh",
                "no_agent": True,
            },
            {
                "name": "stack-bookmark-curation",
                "enabled": True,
                "schedule": {"kind": "cron", "expr": "23 9 * * 1"},
                "script": "stack-bookmark-curation.sh",
                "no_agent": True,
            },
        ]
        if duplicate:
            jobs.append(dict(jobs[0]))
        jobs_path = Path(self._environment["STACK_HERMES_CRON_JOBS"])
        jobs_path.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
        jobs_path.chmod(0o600)
        gateway_path = Path(self._environment["STACK_HERMES_GATEWAY_STATE"])
        gateway_path.write_text(
            json.dumps({"gateway_state": "running", "updated_at": "2026-08-30T02:00:00Z"}),
            encoding="utf-8",
        )
        gateway_path.chmod(0o600)

    def report(self, **extra_env: str) -> dict[str, object]:
        environment = {**self._environment, **extra_env}
        with (
            mock.patch.object(STATUS, "owner_home", return_value=self.root),
            mock.patch.object(STATUS.FRESHNESS, "owner_home", return_value=self.root),
            mock.patch.dict(os.environ, environment, clear=False),
        ):
            return STATUS.status_report(now=datetime(2026, 8, 30, 3, 0, tzinfo=timezone.utc))

    def test_healthy_report_is_redacted_and_reports_binding_media_scheduler_and_receipts(self) -> None:
        self.write_refresh_receipt(generated_at=datetime(2026, 8, 30, 2, 30, tzinfo=timezone.utc))
        self.write_stack_receipts()
        self.write_scheduler_files()
        report = self.report()
        encoded = json.dumps(report)
        self.assertEqual("healthy", report["status"])
        self.assertEqual(2, report["field_theory"]["source"]["row_count"])
        self.assertEqual("2026-08-30T02:00:00+00:00", report["field_theory"]["source"]["max_source_timestamp"])
        self.assertEqual(1, report["field_theory"]["media"]["bookmarks_with_media"])
        self.assertEqual("bounded", report["field_theory"]["receipt"]["media"]["state"])
        self.assertEqual(
            "passed",
            report["field_theory"]["receipt"]["stages"]["field-theory-wiki"],
        )
        self.assertEqual("unique", report["job_uniqueness"]["status"])
        self.assertEqual("configured", report["scheduler"]["daily_field_theory"]["status"])
        self.assertTrue(report["scheduler"]["daily_field_theory"]["gbrain_lane_excluded"])
        self.assertTrue(report["stack_receipts"]["collection"]["complete"])
        self.assertTrue(report["stack_receipts"]["curation"]["complete"])
        self.assertFalse(report["safety"]["bookmark_bodies_included"])
        self.assertNotIn("private body", encoded)
        self.assertNotIn("another private body", encoded)

    def test_drifted_collection_schedule_blocks_weekly_preflight(self) -> None:
        self.write_refresh_receipt()
        self.write_scheduler_files(drifted=True)
        output = self.state / "preflight.json"

        report = self.report()
        self.assertEqual("blocked", report["status"])
        self.assertEqual("bookmark_job_contract_unhealthy", report["reason"])
        self.assertEqual("drifted", report["job_uniqueness"]["status"])
        self.assertFalse(
            report["job_uniqueness"]["contract_matches"]["stack-bookmark-collection"]
        )
        self.assertIn("reconcile_bookmark_job_contract", report["allowed_next_actions"])

        with (
            mock.patch.object(STATUS, "owner_home", return_value=self.root),
            mock.patch.object(STATUS.FRESHNESS, "owner_home", return_value=self.root),
            mock.patch.dict(
                os.environ,
                {**self._environment, "STACK_WEEKLY_PREFLIGHT_RECEIPT": str(output)},
                clear=False,
            ),
        ):
            result = STATUS.weekly_preflight(
                now=datetime(2026, 8, 30, 3, 0, tzinfo=timezone.utc)
            )
        self.assertEqual("blocked", result["status"])
        self.assertEqual("bookmark_job_contract_unhealthy", result["reason_code"])

    def test_media_metadata_derives_bounded_state_when_untrusted_labels_are_absent(self) -> None:
        metadata = STATUS._safe_media_metadata(
            {
                "pending_bookmark_limit": 50,
                "per_asset_max_bytes": 209715200,
                "timeout_seconds": 2700,
                "budget_deferred": "not a safe token",
                "resume_manifest_present": True,
            }
        )

        self.assertEqual("bounded", metadata["state"])
        self.assertEqual(50, metadata["pending_bookmark_limit"])
        self.assertEqual(209715200, metadata["per_asset_max_bytes"])
        self.assertEqual(2700, metadata["timeout_seconds"])
        self.assertTrue(metadata["resume_manifest_present"])
        self.assertNotIn("budget_deferred", metadata)

    def test_stale_or_missing_source_receipt_is_blocked_without_body_leak(self) -> None:
        self.write_refresh_receipt(
            generated_at=datetime.now(timezone.utc) - timedelta(hours=37)
        )
        report = self.report()
        self.assertEqual("blocked", report["status"])
        self.assertEqual("field_theory_source_unhealthy", report["reason"])
        self.assertEqual("receipt_stale", report["field_theory"]["reason"])
        self.assertNotIn("private body", json.dumps(report))
        self.receipt.unlink()
        missing = self.report()
        self.assertEqual("receipt_missing", missing["field_theory"]["reason"])

    def test_duplicate_jobs_and_active_gbrain_hold_are_visible_as_exact_holds(self) -> None:
        self.write_refresh_receipt()
        self.write_scheduler_files(duplicate=True)
        self.hold.write_text(
            json.dumps({"schema": "gbrain-maintenance-hold/v1", "active": True}),
            encoding="utf-8",
        )
        self.hold.chmod(0o600)
        report = self.report()
        self.assertEqual("held", report["status"])
        self.assertEqual("gbrain_maintenance_active", report["reason"])
        self.assertEqual("active", report["gbrain_hold"]["status"])
        self.assertEqual("duplicate", report["job_uniqueness"]["status"])
        self.assertIn("wait_for_gbrain_handoff", report["allowed_next_actions"])
        self.assertIn("reconcile_unique_bookmark_jobs", report["allowed_next_actions"])

    def test_inactive_gbrain_marker_requires_completed_handoff(self) -> None:
        self.write_refresh_receipt()
        self.hold.write_text(
            json.dumps({"schema": "gbrain-maintenance-hold/v1", "active": False}),
            encoding="utf-8",
        )
        self.hold.chmod(0o600)

        report = self.report()

        self.assertEqual("active", report["gbrain_hold"]["status"])
        self.assertEqual("gbrain_maintenance_state_untrusted", report["gbrain_hold"]["reason"])

    def test_weekly_preflight_persists_a_gbrain_hold_without_subprocess(self) -> None:
        self.write_refresh_receipt()
        self.hold.write_text(
            json.dumps({"schema": "gbrain-maintenance-hold/v1", "active": True}),
            encoding="utf-8",
        )
        self.hold.chmod(0o600)
        output = self.state / "preflight.json"
        with (
            mock.patch.object(STATUS, "owner_home", return_value=self.root),
            mock.patch.object(STATUS.FRESHNESS, "owner_home", return_value=self.root),
            mock.patch.dict(
                os.environ,
                {**self._environment, "STACK_WEEKLY_PREFLIGHT_RECEIPT": str(output)},
                clear=False,
            ),
            mock.patch.object(STATUS.subprocess, "run") as subprocess_run,
        ):
            result = STATUS.weekly_preflight(now=datetime(2026, 8, 30, 3, 0, tzinfo=timezone.utc))
        self.assertEqual("gbrain_maintenance_active", result["reason_code"])
        self.assertEqual("held", result["status"])
        self.assertTrue(result["persisted"])
        self.assertFalse(result["gbrain"]["mutation_allowed"])
        self.assertFalse(subprocess_run.called)
        persisted = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual("x-bookmark-weekly-preflight/v1", persisted["schema"])
        self.assertEqual("gbrain_maintenance_active", persisted["reason_code"])
        self.assertEqual(0o600, stat.S_IMODE(output.stat().st_mode))

    def test_mutation_actions_require_owner_authorization_and_invoke_only_field_theory(self) -> None:
        controller = self.root / "controller.py"
        controller.write_text("# fixture\n", encoding="utf-8")
        controller.chmod(0o700)
        auth = self.root / "authorization.json"
        now = datetime(2026, 8, 30, 3, 0, tzinfo=timezone.utc)
        auth.write_text(
            json.dumps(
                {
                    "schema": STATUS.AUTHORIZATION_SCHEMA,
                    "authorized": True,
                    "purpose": "field-theory-bookmarks",
                    "action": "resume",
                    "issued_at": "2026-08-30T02:00:00Z",
                    "expires_at": "2026-08-30T04:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        auth.chmod(0o600)
        with (
            mock.patch.object(STATUS, "owner_home", return_value=self.root),
            mock.patch.dict(os.environ, {"FIELD_THEORY_CONTROLLER": str(controller)}, clear=False),
            mock.patch.object(STATUS.subprocess, "run", return_value=mock.Mock(returncode=0)) as run,
        ):
            code, result = STATUS.run_controller("resume", auth, now=now)
        self.assertEqual(0, code)
        self.assertEqual("completed", result["status"])
        argv = run.call_args.args[0]
        self.assertEqual(["--live", "--only", "field-theory-bookmarks"], argv[-3:])
        self.assertNotIn("authorization", " ".join(argv))
        auth.write_text(
            json.dumps(
                {
                    "schema": STATUS.AUTHORIZATION_SCHEMA,
                    "authorized": True,
                    "purpose": "field-theory-bookmarks",
                    "action": "run",
                    "issued_at": "2026-08-30T02:00:00Z",
                    "expires_at": "2026-08-30T02:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        auth.chmod(0o600)
        code, result = STATUS.run_controller("run", auth, now=now)
        self.assertEqual(75, code)
        self.assertEqual("owner_authorization_expired", result["reason_code"])

    def test_weekly_preflight_source_failure_is_persisted(self) -> None:
        output = self.state / "preflight.json"
        with (
            mock.patch.object(STATUS, "owner_home", return_value=self.root),
            mock.patch.object(STATUS.FRESHNESS, "owner_home", return_value=self.root),
            mock.patch.dict(
                os.environ,
                {**self._environment, "STACK_WEEKLY_PREFLIGHT_RECEIPT": str(output)},
                clear=False,
            ),
        ):
            result = STATUS.weekly_preflight(now=datetime(2026, 8, 30, 3, 0, tzinfo=timezone.utc))
        self.assertEqual("field_theory_source_unhealthy", result["reason_code"])
        self.assertEqual("blocked", result["status"])
        self.assertTrue(output.exists())

    def test_registry_contract_keeps_observation_read_only_and_controls_mutation(self) -> None:
        registry = json.loads(
            (ROOT / "registry" / "bookmark-infrastructure.json").read_text(encoding="utf-8")
        )
        actions = {item["id"]: item for item in registry["actions"]}
        self.assertEqual(
            {"status", "inspect", "weekly-preflight", "run", "resume"},
            set(actions),
        )
        self.assertEqual("read-only", actions["status"]["trust_class"])
        self.assertEqual("read-only", actions["inspect"]["trust_class"])
        self.assertEqual("owner-local-receipt", actions["weekly-preflight"]["trust_class"])
        for action in (actions["run"], actions["resume"]):
            self.assertEqual("local-mutation", action["trust_class"])
            self.assertEqual("owner-local-authorization-receipt", action["authorization"])
            self.assertEqual("field-theory-only", action["controller"])
        root_command = json.loads((ROOT / "registry" / "commands.json").read_text(encoding="utf-8"))["commands"][0]
        self.assertIn("bookmarks", root_command["subcommands"])
        rules = json.loads((ROOT / "registry" / "routing-rules.json").read_text(encoding="utf-8"))["rules"]
        self.assertTrue(any(rule.get("subcommand") == "bookmarks" for rule in rules))

    def test_weekly_preflight_surface_has_no_external_or_cross_project_route(self) -> None:
        source = (ROOT / "scripts" / "x_bookmark_infrastructure_status.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("import-bookmark-deltas", source)
        self.assertNotIn("GBRAIN_CLI", source)


if __name__ == "__main__":
    unittest.main()
