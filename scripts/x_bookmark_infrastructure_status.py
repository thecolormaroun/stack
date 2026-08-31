#!/usr/bin/env python3
"""Read-only X-bookmark infrastructure status and guarded local controls.

The status and inspect actions read only owner-local metadata.  The weekly
preflight writes one small owner-local receipt so a scheduler can stop with a
machine-readable reason.  It never imports, indexes, embeds, syncs, or edits
the cross-project knowledge service.  ``run`` and ``resume`` are deliberately
separate guarded actions: they require an owner-only authorization receipt
before invoking the existing Field Theory maintenance controller.

No bookmark bodies, URLs, credentials, arbitrary paths, or subprocess output
are included in any result.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import plistlib
import pwd
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
FRESHNESS_SPEC = importlib.util.spec_from_file_location(
    "x_bookmark_field_theory_freshness", ROOT / "scripts" / "field_theory_freshness.py"
)
if FRESHNESS_SPEC is None or FRESHNESS_SPEC.loader is None:
    raise RuntimeError("field_theory_freshness_unavailable")
FRESHNESS = importlib.util.module_from_spec(FRESHNESS_SPEC)
FRESHNESS_SPEC.loader.exec_module(FRESHNESS)


STATUS_SCHEMA = "x-bookmark-infrastructure-status/v1"
PREFLIGHT_SCHEMA = "x-bookmark-weekly-preflight/v1"
AUTHORIZATION_SCHEMA = "x-bookmark-owner-authorization/v1"
GBRAIN_HOLD_SCHEMA = "gbrain-maintenance-hold/v1"
DEFAULT_STATE_RELATIVE = Path(".local/state/stack")
DEFAULT_HOLD_NAME = "gbrain-maintenance-hold.json"
DEFAULT_PREFLIGHT_NAME = "weekly-preflight.json"
DEFAULT_DAILY_LAUNCH_AGENT = Path("Library/LaunchAgents/ai.hermes.daily-maintenance.plist")
DEFAULT_HERMES_JOBS = Path("hermes/cron/jobs.json")
DEFAULT_CONTROLLER = Path("hermes/scripts/mookie-daily-maintenance.py")
EXPECTED_CRON_JOBS = ("stack-bookmark-collection", "stack-bookmark-curation")
EXPECTED_CRON_SPECS = {
    "stack-bookmark-collection": {
        "schedule": "17 4,6 * * *",
        "script": "stack-bookmark-collection.sh",
    },
    "stack-bookmark-curation": {
        "schedule": "23 9 * * 1",
        "script": "stack-bookmark-curation.sh",
    },
}
MAX_PREFLIGHT_AGE_SECONDS = getattr(FRESHNESS, "MAX_AGE_SECONDS", 36 * 60 * 60)
SAFE_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
SAFE_RECEIPT_NAME_RE = re.compile(r"^(collection|curation)-[A-Za-z0-9_.-]{1,100}\.json$")


class InfrastructureError(RuntimeError):
    """A redacted, stable operational failure."""


def owner_home() -> Path:
    """Return the current account's home without trusting ``$HOME``."""

    return Path(pwd.getpwuid(os.getuid()).pw_dir).absolute()


def _expand(value: str | Path) -> Path:
    text = str(value)
    home = owner_home()
    if text == "~":
        return home
    if text.startswith("~/"):
        return home / text[2:]
    return Path(text)


def _state_root() -> Path:
    configured = os.environ.get("STACK_BOOKMARK_STATE_ROOT")
    return (_expand(configured) if configured else owner_home() / DEFAULT_STATE_RELATIVE).absolute()


def _safe_path_parts(path: Path, *, allow_missing_leaf: bool = False) -> None:
    """Reject symlink substitution for a local status/control path."""

    lexical = Path(os.path.abspath(str(path.expanduser())))
    current = Path(lexical.anchor)
    for component in lexical.parts[1:]:
        current /= component
        try:
            details = current.lstat()
        except FileNotFoundError:
            if allow_missing_leaf and current == lexical:
                return
            continue
        except OSError as exc:
            raise InfrastructureError("owner_local_path_unavailable") from exc
        if stat.S_ISLNK(details.st_mode):
            # macOS's /var and /tmp aliases are system-owned and are not a
            # user-controlled redirection.  Do not extend this exception.
            expected = {
                Path("/tmp"): Path("/private/tmp"),
                Path("/var"): Path("/private/var"),
                Path("/etc"): Path("/private/etc"),
            }.get(current)
            if expected is None or Path(os.path.realpath(current)) != expected:
                raise InfrastructureError("owner_local_symlink_detected")


def _owner_file_details(path: Path, *, private: bool = False) -> os.stat_result:
    _safe_path_parts(path)
    try:
        details = path.lstat()
    except FileNotFoundError as exc:
        raise InfrastructureError("owner_local_file_missing") from exc
    except OSError as exc:
        raise InfrastructureError("owner_local_path_unavailable") from exc
    if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid():
        raise InfrastructureError("owner_local_file_invalid")
    if stat.S_IMODE(details.st_mode) & 0o022:
        raise InfrastructureError("owner_local_file_permissions_invalid")
    if private and stat.S_IMODE(details.st_mode) != 0o600:
        raise InfrastructureError("owner_local_file_permissions_invalid")
    return details


def _owner_directory_details(path: Path, *, create: bool = False) -> os.stat_result:
    path = path.absolute()
    if create and not path.exists():
        _safe_path_parts(path, allow_missing_leaf=True)
        try:
            path.mkdir(parents=True, mode=0o700, exist_ok=True)
        except OSError as exc:
            raise InfrastructureError("owner_local_directory_unavailable") from exc
    _safe_path_parts(path)
    try:
        details = path.lstat()
    except FileNotFoundError as exc:
        raise InfrastructureError("owner_local_directory_missing") from exc
    except OSError as exc:
        raise InfrastructureError("owner_local_path_unavailable") from exc
    if not stat.S_ISDIR(details.st_mode) or details.st_uid != os.getuid():
        raise InfrastructureError("owner_local_directory_invalid")
    if stat.S_IMODE(details.st_mode) != 0o700:
        raise InfrastructureError("owner_local_directory_permissions_invalid")
    return details


def _read_json(path: Path, *, private: bool = False) -> tuple[Mapping[str, Any] | None, str | None, os.stat_result | None]:
    try:
        details = _owner_file_details(path, private=private)
    except InfrastructureError as exc:
        return None, str(exc), None
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | nofollow)
        opened = os.fstat(descriptor)
        if opened.st_ino != details.st_ino or opened.st_dev != details.st_dev:
            return None, "owner_local_file_changed", opened
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            value = json.load(handle)
    except FileNotFoundError:
        return None, "owner_local_file_missing", details
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, "metadata_malformed", details
    finally:
        if descriptor != -1:
            os.close(descriptor)
    if not isinstance(value, dict):
        return None, "metadata_malformed", details
    return value, None, details


def _safe_timestamp(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _now(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _safe_status(value: Any, *, default: str = "unknown") -> str:
    if isinstance(value, str) and SAFE_TOKEN_RE.fullmatch(value):
        return value
    return default


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _safe_media_metadata(value: Any) -> dict[str, Any]:
    """Keep only bounded media counters and state labels from a receipt."""

    if not isinstance(value, Mapping):
        return {"state": "unknown"}
    allowed = {
        "state",
        "budget_deferred",
        "count",
        "pending_count",
        "processed_count",
        "deferred_count",
        "downloaded_count",
        "resolved_count",
        "unavailable_count",
        "metadata_only_count",
        "failed_count",
        "remaining_count",
        "limit",
        "max_bytes",
        "elapsed_seconds",
        "pending_bookmark_limit",
        "per_asset_max_bytes",
        "timeout_seconds",
        "skipped_too_large",
    }
    result: dict[str, Any] = {}
    for key in sorted(allowed):
        raw = value.get(key)
        if key in {"state", "budget_deferred"}:
            if isinstance(raw, str) and SAFE_TOKEN_RE.fullmatch(raw):
                result[key] = raw
        else:
            safe = _safe_int(raw)
            if safe is not None:
                result[key] = safe
    if isinstance(value.get("resume_manifest_present"), bool):
        result["resume_manifest_present"] = value["resume_manifest_present"]
    if "state" not in result and {
        "pending_bookmark_limit",
        "per_asset_max_bytes",
        "timeout_seconds",
    }.issubset(result):
        result["state"] = "bounded"
    return result or {"state": "unknown"}


def _safe_stage_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"state": "unknown"}
    allowed_stages = {
        "source",
        "media",
        "classification",
        "deterministic",
        "llm",
        "markdown",
        "index",
        "wiki",
        "smoke",
        "rollback",
        "recovery",
        "commands_validate",
        "field-theory-fetch-media",
        "field-theory-index",
        "field-theory-llm-writes",
        "field-theory-md-changed",
        "field-theory-sync",
        "field-theory-wiki",
        "field-theory-write-surfaces",
        "lint",
        "status",
    }
    result: dict[str, Any] = {}
    for key in sorted(allowed_stages):
        raw = value.get(key)
        if isinstance(raw, Mapping):
            raw = raw.get("state", raw.get("status", raw.get("outcome")))
        if isinstance(raw, str) and SAFE_TOKEN_RE.fullmatch(raw):
            result[key] = raw
    return result or {"state": "unknown"}


def _receipt_metadata(receipt_path: Path) -> dict[str, Any]:
    try:
        receipt, details, error = FRESHNESS._read_private_receipt(receipt_path)
    except (AttributeError, OSError):
        return {"present": False, "reason": "receipt_unavailable"}
    if error or receipt is None or details is None:
        return {"present": False, "reason": error or "receipt_unavailable"}
    result: dict[str, Any] = {
        "present": True,
        "generated_at": _safe_timestamp(receipt.get("generated_at")),
        "outcome": _safe_status(receipt.get("outcome")),
        "authoritative": receipt.get("authoritative") is True,
        "deterministic_checks_passed": receipt.get("deterministic_checks_passed") is True,
        "media": _safe_media_metadata(receipt.get("media")),
        "stages": _safe_stage_metadata(receipt.get("stages")),
    }
    age = _now().timestamp() - details.st_mtime
    if age >= 0:
        result["age_seconds"] = int(age)
    return result


def _field_theory_source(document: Mapping[str, Any]) -> Mapping[str, Any] | None:
    sources = document.get("sources")
    if not isinstance(sources, list):
        return None
    for source in sources:
        if isinstance(source, Mapping) and source.get("id") == "field-theory" and source.get("enabled", True):
            return source
    return None


def _media_summary(database_path: Path) -> dict[str, Any]:
    """Read aggregate media counters only; never select bookmark content."""

    try:
        details = database_path.lstat()
        if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid():
            return {"status": "unavailable", "reason": "database_path_invalid"}
        from urllib.parse import quote

        uri = f"file:{quote(str(database_path.absolute()), safe='/')}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
    except (OSError, sqlite3.Error):
        return {"status": "unavailable", "reason": "database_unavailable"}
    try:
        try:
            row = connection.execute(
                'SELECT COUNT(*), '
                'COALESCE(SUM(CASE WHEN "media_count" > 0 THEN 1 ELSE 0 END), 0), '
                'COALESCE(SUM(CASE WHEN "media_count" = 0 THEN 1 ELSE 0 END), 0), '
                'COALESCE(SUM(CASE WHEN "media_count" IS NULL THEN 1 ELSE 0 END), 0), '
                'COALESCE(SUM(CASE WHEN "media_count" > 0 THEN "media_count" ELSE 0 END), 0) '
                'FROM "bookmarks"'
            ).fetchone()
        except sqlite3.Error:
            return {"status": "unavailable", "reason": "database_contract_invalid"}
    finally:
        connection.close()
    assert row is not None
    return {
        "status": "observed",
        "bookmark_count": int(row[0]),
        "bookmarks_with_media": int(row[1]),
        "bookmarks_without_media": int(row[2]),
        "bookmarks_with_unknown_media": int(row[3]),
        "media_asset_count": int(row[4]),
    }


def _field_theory_summary(document: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    source = _field_theory_source(document)
    if source is None:
        return {
            "status": "blocked",
            "reason": "field_theory_source_not_configured",
            "receipt": {"present": False, "reason": "source_not_configured"},
            "source": {"row_count": None, "max_source_timestamp": None},
            "media": {"status": "unavailable", "reason": "source_not_configured"},
        }
    preflight = FRESHNESS.preflight_source(source)
    result: dict[str, Any] = {
        "status": "healthy" if preflight.get("ok") else "blocked",
        "reason": _safe_status(preflight.get("reason"), default="field_theory_preflight_failed"),
    }
    try:
        database_path = FRESHNESS._database_path(source)
        receipt_path = FRESHNESS._configured_receipt_path(source)
    except (AttributeError, ValueError):
        database_path = None
        receipt_path = None
    result["receipt"] = _receipt_metadata(receipt_path) if receipt_path else {"present": False, "reason": "receipt_path_invalid"}
    binding: Mapping[str, Any] | None = None
    if database_path is not None:
        try:
            # The current projection is safe to report even if the receipt is
            # stale; it is explicitly labelled observed rather than verified.
            binding = FRESHNESS.read_database_binding(database_path)
        except ValueError:
            binding = None
        result["media"] = _media_summary(database_path)
    else:
        result["media"] = {"status": "unavailable", "reason": "database_path_invalid"}
    if binding is None:
        result["source"] = {"row_count": None, "max_source_timestamp": None}
    else:
        result["source"] = {
            "row_count": _safe_int(binding.get("row_count")),
            "max_source_timestamp": _safe_timestamp(binding.get("max_source_timestamp"))
            or (binding.get("max_source_timestamp") if isinstance(binding.get("max_source_timestamp"), str) else None),
            "identity_revision_sha256": binding.get("identity_revision_sha256")
            if isinstance(binding.get("identity_revision_sha256"), str)
            and re.fullmatch(r"[a-f0-9]{64}", binding["identity_revision_sha256"])
            else None,
        }
    if preflight.get("ok") and isinstance(preflight.get("age_seconds"), int):
        result["receipt"]["verified_age_seconds"] = preflight["age_seconds"]
        result["verified_binding"] = preflight.get("database_binding")
    return result


def _latest_receipt(receipts_root: Path, phase: str) -> dict[str, Any]:
    if not receipts_root.exists():
        return {"status": "not_observed", "reason": "receipts_directory_missing"}
    try:
        _owner_directory_details(receipts_root)
    except InfrastructureError as exc:
        return {"status": "blocked", "reason": str(exc)}
    candidates: list[tuple[Path, os.stat_result]] = []
    try:
        paths = list(receipts_root.iterdir())
    except OSError:
        return {"status": "blocked", "reason": "receipts_directory_unavailable"}
    for path in paths:
        if not path.name.startswith(f"{phase}-") or path.suffix != ".json":
            continue
        try:
            details = _owner_file_details(path)
        except InfrastructureError:
            continue
        candidates.append((path, details))
    if not candidates:
        return {"status": "not_observed", "reason": "receipt_missing"}
    path, details = max(candidates, key=lambda pair: pair[1].st_mtime)
    payload, error, _ = _read_json(path)
    if error or payload is None:
        return {"status": "invalid", "reason": error or "receipt_malformed"}
    now = _now()
    age = now.timestamp() - details.st_mtime
    result: dict[str, Any] = {
        "status": "observed",
        "receipt_name": path.name if SAFE_RECEIPT_NAME_RE.fullmatch(path.name) else "untrusted_name",
        "age_seconds": int(age) if age >= 0 else None,
        "phase": phase,
        "complete": payload.get("complete") is True,
        "manual_run": payload.get("manual_run") is True,
        "mode": _safe_status(payload.get("mode"), default="unknown"),
        "receipt_type": _safe_status(payload.get("receipt_type"), default="unknown"),
    }
    if isinstance(payload.get("reason"), str) and SAFE_TOKEN_RE.fullmatch(payload["reason"]):
        result["reason"] = payload["reason"]
    return result


def _stack_receipts(state_root: Path) -> dict[str, Any]:
    return {
        "collection": _latest_receipt(state_root / "receipts", "collection"),
        "curation": _latest_receipt(state_root / "receipts", "curation"),
    }


def _launch_agent_summary(path: Path) -> dict[str, Any]:
    try:
        _owner_file_details(path)
    except InfrastructureError as exc:
        return {"status": "not_observed", "reason": str(exc)}
    try:
        payload = plistlib.loads(path.read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError):
        return {"status": "invalid", "reason": "launch_agent_malformed"}
    if not isinstance(payload, Mapping):
        return {"status": "invalid", "reason": "launch_agent_malformed"}
    args = payload.get("ProgramArguments")
    args = args if isinstance(args, list) else []
    arg_text = [item for item in args if isinstance(item, str)]
    calendar = payload.get("StartCalendarInterval")
    calendar = calendar if isinstance(calendar, Mapping) else {}
    label = _safe_status(payload.get("Label"), default="unknown")
    hour = _safe_int(calendar.get("Hour"))
    minute = _safe_int(calendar.get("Minute"))
    try:
        controller_index = next(
            index
            for index, item in enumerate(arg_text)
            if item.endswith("mookie-daily-maintenance.py")
        )
    except StopIteration:
        controller_index = -1
    controller_tail = arg_text[controller_index:] if controller_index >= 0 else []
    field_theory_only = bool(
        len(controller_tail) == 4
        and controller_tail[1:] == ["--live", "--only", "field-theory-bookmarks"]
    )
    contract_matches = bool(
        label == "ai.hermes.daily-maintenance"
        and hour == 2
        and minute == 7
        and field_theory_only
    )
    controller = Path(controller_tail[0]).name if controller_tail else None
    return {
        "status": "configured" if contract_matches else "drifted",
        "label": label,
        "schedule": {
            "hour": hour,
            "minute": minute,
        },
        "entrypoint": controller,
        "field_theory_only": field_theory_only,
        "gbrain_lane_excluded": field_theory_only,
        "contract_matches": contract_matches,
        "loaded_state": "not_observed",
    }


def _cron_summary(path: Path) -> dict[str, Any]:
    payload, error, _ = _read_json(path)
    if error or payload is None:
        return {"status": "not_observed", "reason": error or "cron_jobs_unavailable"}
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        return {"status": "invalid", "reason": "cron_jobs_malformed"}
    counts = {name: 0 for name in EXPECTED_CRON_JOBS}
    total_seen = {name: 0 for name in EXPECTED_CRON_JOBS}
    contract_matches = {name: False for name in EXPECTED_CRON_JOBS}
    for job in jobs:
        if not isinstance(job, Mapping):
            continue
        name = job.get("name")
        if name not in counts:
            continue
        total_seen[name] += 1
        if job.get("paused") is True or job.get("enabled") is False:
            continue
        counts[name] += 1
        schedule = job.get("schedule")
        schedule = schedule if isinstance(schedule, Mapping) else {}
        expression = schedule.get("expr") or job.get("schedule_display")
        script = Path(str(job.get("script") or "")).name
        expected = EXPECTED_CRON_SPECS[name]
        contract_matches[name] = bool(
            expression == expected["schedule"]
            and script == expected["script"]
            and job.get("no_agent") is True
        )
    if any(counts[name] > 1 or total_seen[name] > 1 for name in EXPECTED_CRON_JOBS):
        status = "duplicate"
    elif not all(counts[name] == 1 for name in EXPECTED_CRON_JOBS):
        status = "missing"
    elif all(contract_matches.values()):
        status = "unique"
    else:
        status = "drifted"
    return {
        "status": status,
        "active_counts": counts,
        "total_counts": total_seen,
        "contract_matches": contract_matches,
    }


def _scheduler_summary() -> dict[str, Any]:
    launch_path = _expand(os.environ.get("STACK_DAILY_LAUNCH_AGENT", owner_home() / DEFAULT_DAILY_LAUNCH_AGENT))
    cron_path = _expand(os.environ.get("STACK_HERMES_CRON_JOBS", owner_home() / DEFAULT_HERMES_JOBS))
    gateway_path = _expand(os.environ.get("STACK_HERMES_GATEWAY_STATE", owner_home() / ".hermes/gateway_state.json"))
    gateway, gateway_error, _ = _read_json(gateway_path)
    gateway_state = {
        "status": _safe_status(gateway.get("gateway_state"), default="not_observed") if gateway else "not_observed",
        "updated_at": _safe_timestamp(gateway.get("updated_at")) if gateway else None,
    }
    return {
        "daily_field_theory": _launch_agent_summary(launch_path),
        "hermes_gateway": gateway_state if not gateway_error else {"status": "not_observed", "reason": gateway_error},
        "hermes_bookmark_jobs": _cron_summary(cron_path),
    }


def _circuit_summary(state_root: Path) -> dict[str, Any]:
    configured = os.environ.get("STACK_WEEKLY_CIRCUIT_FILE")
    path = _expand(configured) if configured else state_root / "weekly-intelligence/live/coordinator/weekly-intelligence.circuit.json"
    payload, error, _ = _read_json(path, private=True)
    if error or payload is None:
        return {"status": "not_observed", "reason": error or "circuit_unavailable"}
    opened = payload.get("open") is True or payload.get("status") == "open"
    result = {
        "status": "open" if opened else "closed",
        "strike_count": _safe_int(payload.get("strike_count")) or 0,
    }
    if isinstance(payload.get("reason_code"), str) and SAFE_TOKEN_RE.fullmatch(payload["reason_code"]):
        result["reason_code"] = payload["reason_code"]
    return result


def _gbrain_hold(state_root: Path) -> dict[str, Any]:
    env_value = os.environ.get("GBRAIN_MAINTENANCE_ACTIVE")
    if env_value is not None:
        active = env_value.strip().lower() in {"1", "true", "yes", "active", "on"}
        return {
            "status": "active" if active else "inactive",
            "reason": "gbrain_maintenance_active" if active else "explicit_handoff_recorded",
            "source": "owner_environment",
        }
    configured = os.environ.get("STACK_GBRAIN_HOLD_FILE")
    path = _expand(configured) if configured else state_root / DEFAULT_HOLD_NAME
    if path.exists():
        payload, error, _ = _read_json(path, private=True)
        if error or payload is None:
            return {"status": "active", "reason": "gbrain_maintenance_state_untrusted", "source": "owner_marker"}
        if payload.get("schema") != GBRAIN_HOLD_SCHEMA or not isinstance(payload.get("active"), bool):
            return {"status": "active", "reason": "gbrain_maintenance_state_untrusted", "source": "owner_marker"}
        active = payload.get("active") is True
        if not active and payload.get("handoff_status") != "completed":
            return {"status": "active", "reason": "gbrain_maintenance_state_untrusted", "source": "owner_marker"}
        return {
            "status": "active" if active else "inactive",
            "reason": "gbrain_maintenance_active" if active else "explicit_handoff_recorded",
            "source": "owner_marker",
        }
    # Fail closed until the separate task records its stable handoff.  This is
    # a status default, not a claim that the separate task has changed state.
    return {"status": "active", "reason": "gbrain_maintenance_active", "source": "safe_default_hold"}


def _locks(state_root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for phase in ("collection", "curation"):
        path = state_root / f"{phase}.lock"
        result[phase] = {"busy": path.exists() and path.is_dir()}
    return result


def _allowed_actions(
    field_theory: Mapping[str, Any],
    scheduler: Mapping[str, Any],
    receipts: Mapping[str, Any],
    circuit: Mapping[str, Any],
    gbrain: Mapping[str, Any],
    locks: Mapping[str, Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    actions: list[dict[str, Any]] = [
        {"id": "status", "allowed": True, "trust_class": "read-only"},
        {"id": "inspect", "allowed": True, "trust_class": "read-only"},
        {"id": "weekly-preflight", "allowed": True, "trust_class": "owner-local-receipt"},
        {
            "id": "run",
            "allowed": False,
            "trust_class": "local-mutation",
            "requires": "owner_authorization_receipt",
        },
        {
            "id": "resume",
            "allowed": False,
            "trust_class": "local-mutation",
            "requires": "owner_authorization_receipt",
        },
    ]
    next_actions = ["status", "inspect", "weekly-preflight"]
    if gbrain.get("status") == "active":
        next_actions.append("wait_for_gbrain_handoff")
    if field_theory.get("status") != "healthy":
        next_actions.append("repair_field_theory_source")
    if any(isinstance(value, Mapping) and value.get("busy") for value in locks.values()):
        next_actions.append("retry_after_lock_release")
    if circuit.get("status") == "open":
        next_actions.append("manual_clear_required")
    cron = scheduler.get("hermes_bookmark_jobs") if isinstance(scheduler, Mapping) else None
    if not isinstance(cron, Mapping) or cron.get("status") in {"missing", "duplicate", "not_observed", "invalid"}:
        next_actions.append("reconcile_unique_bookmark_jobs")
    elif cron.get("status") != "unique":
        next_actions.append("reconcile_bookmark_job_contract")
    for phase in EXPECTED_CRON_JOBS:
        key = "collection" if phase.endswith("collection") else "curation"
        receipt = receipts.get(key) if isinstance(receipts, Mapping) else None
        if not isinstance(receipt, Mapping) or receipt.get("complete") is not True:
            next_actions.append(f"produce_{key}_apply_receipt")
    return next_actions, actions


def status_report(*, now: datetime | None = None) -> dict[str, Any]:
    reference = _now(now)
    source_path = _expand(os.environ.get("STACK_BOOKMARK_SOURCES", ROOT / "config/bookmark-sources.json"))
    document, error, _ = _read_json(source_path)
    if error or document is None:
        document = {}
    state_root = _state_root()
    field_theory = _field_theory_summary(document, reference)
    receipts = _stack_receipts(state_root)
    scheduler = _scheduler_summary()
    daily_schedule = scheduler.get("daily_field_theory") if isinstance(scheduler, Mapping) else {}
    cron_schedule = scheduler.get("hermes_bookmark_jobs") if isinstance(scheduler, Mapping) else {}
    gateway = scheduler.get("hermes_gateway") if isinstance(scheduler, Mapping) else {}
    circuit = _circuit_summary(state_root)
    gbrain = _gbrain_hold(state_root)
    locks = _locks(state_root)
    next_actions, action_contract = _allowed_actions(field_theory, scheduler, receipts, circuit, gbrain, locks)
    if error:
        overall = "blocked"
        overall_reason = "bookmark_sources_unavailable"
    elif field_theory.get("status") != "healthy":
        overall = "blocked"
        overall_reason = "field_theory_source_unhealthy"
    elif gbrain.get("status") == "active":
        overall = "held"
        overall_reason = "gbrain_maintenance_active"
    elif not isinstance(daily_schedule, Mapping) or daily_schedule.get("status") != "configured":
        overall = "blocked"
        overall_reason = "daily_field_theory_schedule_unhealthy"
    elif not isinstance(cron_schedule, Mapping) or cron_schedule.get("status") != "unique":
        overall = "blocked"
        overall_reason = "bookmark_job_contract_unhealthy"
    elif not isinstance(gateway, Mapping) or gateway.get("status") != "running":
        overall = "blocked"
        overall_reason = "hermes_gateway_unhealthy"
    elif circuit.get("status") == "open":
        overall = "held"
        overall_reason = "weekly_circuit_open"
    else:
        overall = "healthy"
        overall_reason = "ready"
    return {
        "schema": STATUS_SCHEMA,
        "generated_at": reference.isoformat(),
        "status": overall,
        "reason": overall_reason,
        "field_theory": field_theory,
        "scheduler": scheduler,
        "stack_receipts": receipts,
        "job_uniqueness": scheduler.get("hermes_bookmark_jobs", {"status": "not_observed"}),
        "gbrain_hold": gbrain,
        "weekly_circuit": circuit,
        "locks": locks,
        "allowed_next_actions": next_actions,
        "action_contract": action_contract,
        "safety": {
            "bookmark_bodies_included": False,
            "credentials_included": False,
            "gbrain_mutation_performed": False,
        },
    }


def _write_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    # Keep the default status lane below the same owner-only state root used
    # for its lock and receipt observations.  This also prevents an explicit
    # output path from silently creating a sibling state tree with weaker
    # directory controls.
    state_root = _state_root()
    try:
        path.absolute().relative_to(state_root.absolute())
    except ValueError:
        raise InfrastructureError("preflight_receipt_path_not_allowlisted") from None
    _owner_directory_details(state_root, create=True)
    _owner_directory_details(path.parent, create=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        temporary = Path(name)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        os.chmod(path, 0o600)
    except OSError as exc:
        raise InfrastructureError("owner_local_receipt_write_failed") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def weekly_preflight(*, now: datetime | None = None) -> dict[str, Any]:
    report = status_report(now=now)
    if report["gbrain_hold"]["status"] == "active":
        reason_code = "gbrain_maintenance_active"
        status = "held"
    elif report["field_theory"]["status"] != "healthy":
        reason_code = "field_theory_source_unhealthy"
        status = "blocked"
    elif report["status"] == "blocked":
        reason_code = _safe_status(report.get("reason"), default="bookmark_scheduler_unhealthy")
        status = "blocked"
    elif report["status"] == "held":
        reason_code = _safe_status(report.get("reason"), default="weekly_upstream_hold")
        status = "held"
    else:
        reason_code = "ready"
        status = "ready"
    result = {
        "schema": PREFLIGHT_SCHEMA,
        "generated_at": report["generated_at"],
        "status": status,
        "reason_code": reason_code,
        "source": {
            "status": report["field_theory"].get("status"),
            "reason": report["field_theory"].get("reason"),
            "row_count": (report["field_theory"].get("source") or {}).get("row_count"),
            "max_source_timestamp": (report["field_theory"].get("source") or {}).get("max_source_timestamp"),
            "receipt_age_seconds": (report["field_theory"].get("receipt") or {}).get("verified_age_seconds"),
        },
        "gbrain": {
            "status": report["gbrain_hold"].get("status"),
            "reason": report["gbrain_hold"].get("reason"),
            "mutation_allowed": False,
            "mutator_invoked": False,
        },
        "allowed_next_actions": report["allowed_next_actions"],
        "safety": {
            "bookmark_bodies_included": False,
            "credentials_included": False,
            "gbrain_mutation_performed": False,
        },
    }
    configured = os.environ.get("STACK_WEEKLY_PREFLIGHT_RECEIPT")
    output = _expand(configured) if configured else _state_root() / "x-bookmark-infrastructure" / DEFAULT_PREFLIGHT_NAME
    _write_private_json(output, result)
    result["persisted"] = True
    return result


def _parse_auth_timestamp(value: Any) -> datetime | None:
    parsed = _safe_timestamp(value)
    if parsed is None:
        return None
    return datetime.fromisoformat(parsed)


def validate_authorization(receipt_path: Path, action: str, *, now: datetime | None = None) -> dict[str, Any]:
    payload, error, _ = _read_json(receipt_path, private=True)
    if error or payload is None:
        return {"ok": False, "reason": "owner_authorization_missing" if error == "owner_local_file_missing" else "owner_authorization_unavailable"}
    if payload.get("schema") != AUTHORIZATION_SCHEMA:
        return {"ok": False, "reason": "owner_authorization_schema_invalid"}
    if payload.get("authorized") is not True or payload.get("purpose") != "field-theory-bookmarks":
        return {"ok": False, "reason": "owner_authorization_scope_invalid"}
    if payload.get("action") not in {"run", "resume"} or payload.get("action") != action:
        return {"ok": False, "reason": "owner_authorization_action_mismatch"}
    issued = _parse_auth_timestamp(payload.get("issued_at"))
    expires = _parse_auth_timestamp(payload.get("expires_at"))
    reference = _now(now)
    if issued is None or expires is None or issued > reference or expires <= reference:
        return {"ok": False, "reason": "owner_authorization_expired"}
    return {"ok": True, "reason": "owner_authorized"}


def _controller_path() -> Path:
    configured = os.environ.get("FIELD_THEORY_CONTROLLER")
    return (_expand(configured) if configured else owner_home() / DEFAULT_CONTROLLER).absolute()


def run_controller(action: str, authorization_receipt: Path, *, now: datetime | None = None) -> tuple[int, dict[str, Any]]:
    authorization = validate_authorization(authorization_receipt, action, now=now)
    if not authorization.get("ok"):
        return 75, {"status": "blocked", "action": action, "reason_code": authorization["reason"]}
    controller = _controller_path()
    try:
        details = _owner_file_details(controller)
    except InfrastructureError:
        return 75, {"status": "blocked", "action": action, "reason_code": "field_theory_controller_unavailable"}
    if stat.S_IMODE(details.st_mode) & 0o111 == 0:
        return 75, {"status": "blocked", "action": action, "reason_code": "field_theory_controller_not_executable"}
    argv = [sys.executable, str(controller), "--live", "--only", "field-theory-bookmarks"]
    environment = {
        "PATH": f"{owner_home() / '.bun/bin'}:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(owner_home()),
        "HERMES_HOME": str(owner_home() / "hermes"),
        "MOOKIE_USER_HOME": str(owner_home()),
        "PYTHONUNBUFFERED": "1",
    }
    try:
        completed = subprocess.run(argv, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except OSError:
        return 1, {"status": "failed", "action": action, "reason_code": "field_theory_controller_unavailable"}
    if completed.returncode != 0:
        return 1, {"status": "failed", "action": action, "reason_code": "field_theory_controller_failed"}
    return 0, {"status": "completed", "action": action, "reason_code": "field_theory_controller_completed"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action")
    subparsers.add_parser("status")
    subparsers.add_parser("inspect")
    subparsers.add_parser("weekly-preflight")
    for name in ("run", "resume"):
        command = subparsers.add_parser(name)
        command.add_argument("--authorization-receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    action = args.action or "status"
    try:
        if action in {"status", "inspect"}:
            result = status_report()
            result["requested_action"] = action
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if action == "weekly-preflight":
            result = weekly_preflight()
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["status"] == "ready" else 75
        code, result = run_controller(action, args.authorization_receipt)
        print(json.dumps(result, sort_keys=True))
        return code
    except InfrastructureError as exc:
        print(json.dumps({"status": "blocked", "reason_code": str(exc)}, sort_keys=True))
        return 75
    except Exception:
        print(json.dumps({"status": "failed", "reason_code": "unexpected_failure"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
