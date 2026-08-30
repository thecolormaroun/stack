#!/usr/bin/env python3
"""Run the local collection phase of Stack's weekly intelligence campaign.

The coordinator is intentionally small and deterministic. It owns no model,
provider, scheduler, Git, or maintenance execution path. WorkflowStore from
stack-run-state.py is loaded with importlib and remains the sole durable
coordination store for run/child state, leases, and checkpoints.
"""
from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import importlib.util
import inspect
import json
import os
import pwd
import re
import stat
import sys
import tempfile
import time
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9 can still expose --help and fail closed.
    class _TomlUnavailable:
        class TOMLDecodeError(ValueError):
            pass

        @staticmethod
        def loads(_value: str) -> dict[str, Any]:
            raise _TomlUnavailable.TOMLDecodeError("tomllib requires Python 3.11+")

    tomllib = _TomlUnavailable()
from pathlib import Path
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "weekly-intelligence.json"
DEFAULT_TEMPLATE = ROOT / "templates" / "weekly-stack-report.md"
DEFAULT_SCHEMA = ROOT / "registry" / "weekly-campaign-receipt.schema.json"
ACCOUNT_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
DEFAULT_AUTOMATION_ROOT = ACCOUNT_HOME / ".codex" / "automations"
DEFAULT_AUTOMATION_WORKDIR = ACCOUNT_HOME / "Projects" / "stack"
TASK_ID = "stack-weekly-intelligence"
SCHEMA_VERSION = 1
TERMINAL_STATES = {
    "no_action",
    "prepared",
    "awaiting_approval",
    "blocked",
    "partial",
    "failed",
}
STAGE_STATUSES = {
    "completed",
    "reused",
    "failed",
    "blocked",
    "pending",
    "cancelled",
    "leased_elsewhere",
}
STAGE_IDS = (
    "source_intake",
    "design_packet",
    "retrieval",
    "candidate_evaluation",
    "maintenance_link",
    "report_receipt",
)
VOLATILE_KEYS = {
    "observed_at",
    "observation_time",
    "timestamp",
    "checked_at",
    "updated_at",
    "created_at",
    "acquired_at",
    "expires_at",
    "cleared_at",
    "opened_at",
    "run_id",
    "lease_owner",
    "lease_expires_at",
}
DIGEST_RE = re.compile(r"^[a-f0-9]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PATH_RE = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._/-]+$")
CODE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,127}$")


def _safe_code(value: Any, fallback: str = "unknown") -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_-]+", "_", text).strip("_")
    text = text[:128]
    return text if text and CODE_RE.fullmatch(text) else fallback


class WeeklyIntelligenceError(Exception):
    """A redacted, user-safe campaign error."""

    def __init__(self, code: str, retry_class: str = "non_transient") -> None:
        self.code = _safe_code(code, "campaign_failed")
        self.retry_class = retry_class if retry_class in {"transient", "non_transient"} else "non_transient"
        super().__init__(self.code)


CampaignError = WeeklyIntelligenceError


class StageFailure(WeeklyIntelligenceError):
    """Raised by an injected stage adapter without exposing its raw message."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def canonical_prompt_bytes(value: bytes) -> bytes:
    """Match only the automation store's single terminal-LF normalization."""
    return value[:-1] if value.endswith(b"\n") else value


def file_digest(path: Path, missing_marker: str = "MISSING") -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, IOError):
        return hashlib.sha256(missing_marker.encode("utf-8")).hexdigest()


def _without_volatile(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _without_volatile(item)
            for key, item in value.items()
            if str(key).lower() not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_without_volatile(item) for item in value]
    if isinstance(value, tuple):
        return [_without_volatile(item) for item in value]
    return value


def canonical_fingerprint(value: Any) -> str:
    """Fingerprint semantic JSON while excluding run/observation volatility."""
    return digest(_without_volatile(value))


def _safe_id(value: Any, prefix: str) -> str:
    text = str(value or "").strip()
    if ID_RE.fullmatch(text):
        return text
    return f"{prefix}-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:20]}"


def _now_iso(now: float) -> str:
    return _datetime.datetime.fromtimestamp(now, tz=_datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = _datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_datetime.timezone.utc)
    return parsed.timestamp()


def _verify_dir(path: Path, *, create: bool = True) -> None:
    if path.is_symlink():
        raise WeeklyIntelligenceError("state_symlink")
    if not path.exists():
        if not create:
            raise WeeklyIntelligenceError("state_missing")
        try:
            path.mkdir(parents=True, mode=0o700)
        except OSError as exc:
            raise WeeklyIntelligenceError("state_create_failed") from exc
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise WeeklyIntelligenceError("state_unreadable") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise WeeklyIntelligenceError("state_symlink")
    if not stat.S_ISDIR(metadata.st_mode):
        raise WeeklyIntelligenceError("state_not_directory")
    if metadata.st_uid != os.getuid():
        raise WeeklyIntelligenceError("state_owner_mismatch")
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise WeeklyIntelligenceError("state_mode_mismatch")


def _verify_file(path: Path, *, mode: int = 0o600, required: bool = False) -> bool:
    if path.is_symlink():
        raise WeeklyIntelligenceError("state_file_symlink")
    if not path.exists():
        if required:
            raise WeeklyIntelligenceError("state_file_missing")
        return False
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise WeeklyIntelligenceError("state_file_unreadable") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise WeeklyIntelligenceError("state_file_symlink")
    if not stat.S_ISREG(metadata.st_mode):
        raise WeeklyIntelligenceError("state_file_not_regular")
    if metadata.st_uid != os.getuid():
        raise WeeklyIntelligenceError("state_file_owner_mismatch")
    if stat.S_IMODE(metadata.st_mode) != mode:
        raise WeeklyIntelligenceError("state_file_mode_mismatch")
    return True


def _write_atomic_json(path: Path, value: Mapping[str, Any], *, overwrite: bool = False) -> None:
    _verify_dir(path.parent)
    if path.exists() or path.is_symlink():
        _verify_file(path, required=True)
        if not overwrite:
            raise WeeklyIntelligenceError("state_file_exists")
    fd = -1
    temporary: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=".weekly-json-", suffix=".tmp", dir=str(path.parent))
        temporary = Path(name)
        os.fchmod(fd, 0o600)
        payload = (canonical_json(value) + "\n").encode("utf-8")
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        os.chmod(path, 0o600, follow_symlinks=False)
        _verify_file(path, mode=0o600, required=True)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    except WeeklyIntelligenceError:
        raise
    except OSError as exc:
        raise WeeklyIntelligenceError("state_write_failed") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def _write_atomic_text(path: Path, text: str) -> None:
    _verify_dir(path.parent)
    if path.exists() or path.is_symlink():
        _verify_file(path, required=True)
        raise WeeklyIntelligenceError("state_file_exists")
    fd = -1
    temporary: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=".weekly-report-", suffix=".tmp", dir=str(path.parent))
        temporary = Path(name)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        os.chmod(path, 0o600, follow_symlinks=False)
        _verify_file(path, mode=0o600, required=True)
    except WeeklyIntelligenceError:
        raise
    except (OSError, UnicodeError) as exc:
        raise WeeklyIntelligenceError("report_write_failed") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WeeklyIntelligenceError("input_unreadable") from exc


def _read_owner_json(path: Path) -> Any:
    """Read a caller-supplied private input only from an owner-local file."""
    _verify_file(path, mode=0o600, required=True)
    _verify_dir(path.parent, create=False)
    return _read_json(path)


def _coerce_input(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, Path):
        return _read_owner_json(value)
    if isinstance(value, str):
        candidate = Path(value)
        if candidate.exists() or candidate.is_symlink():
            return _read_owner_json(candidate)
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _load_workflow_module() -> Any:
    path = ROOT / "scripts" / "stack-run-state.py"
    spec = importlib.util.spec_from_file_location("stack_run_state_weekly_intelligence", path)
    if spec is None or spec.loader is None:
        raise WeeklyIntelligenceError("workflow_store_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


WORKFLOW_STORE_MODULE = None


def workflow_store_module() -> Any:
    global WORKFLOW_STORE_MODULE
    if WORKFLOW_STORE_MODULE is None:
        WORKFLOW_STORE_MODULE = _load_workflow_module()
    return WORKFLOW_STORE_MODULE


def load_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    value = _read_json(Path(path))
    if not isinstance(value, dict):
        raise WeeklyIntelligenceError("config_not_object")
    required = {
        "schema_version", "campaign_id", "provider_egress", "analysis_budget",
        "automatic_promotion", "stages", "maintenance", "scheduler", "state",
        "approval",
    }
    if set(value) != required:
        raise WeeklyIntelligenceError("config_fields_invalid")
    if value.get("schema_version") != SCHEMA_VERSION or value.get("campaign_id") != TASK_ID:
        raise WeeklyIntelligenceError("config_identity_invalid")
    if value.get("provider_egress") != "deny":
        raise WeeklyIntelligenceError("provider_egress_not_denied")
    budget = value.get("analysis_budget")
    if not isinstance(budget, dict) or set(budget) != {"unit", "maximum", "authorized", "note"} or budget.get("unit") != "concurrent_model_contexts" or budget.get("maximum") != 3 or budget.get("authorized") is not True or not isinstance(budget.get("note"), str) or not budget["note"]:
        raise WeeklyIntelligenceError("analysis_budget_invalid")
    promotion = value.get("automatic_promotion")
    expected_promotion = {
        "state": "active",
        "authorization_contract": "weekly-design-auto-promotion-approved-v1",
        "runtime_receipts_root": "~/.local/state/stack/runtime-receipts",
        "allowed_path_patterns": [
            "skills/**/SKILL.md",
            "skills/**/references/**/*.md",
        ],
        "required_gates": [
            "material-evidence",
            "isolated-materialization",
            "frozen-design-eval",
            "full-repository-tests",
            "fresh-independent-review",
            "pull-request-ci",
            "merge-verification",
            "runtime-publication",
            "rollback-receipt",
        ],
        "weak_candidate_outcome": "no_action",
        "rejected_candidate_outcome": "rejected_no_queue",
        "operational_failure_outcome": "retry_with_alert",
    }
    if promotion != expected_promotion:
        raise WeeklyIntelligenceError("automatic_promotion_contract_invalid")
    stages = value.get("stages")
    if not isinstance(stages, list) or [item.get("id") for item in stages if isinstance(item, dict)] != list(STAGE_IDS):
        raise WeeklyIntelligenceError("stage_graph_invalid")
    for item in stages:
        if not isinstance(item, dict) or set(item) != {"id", "role", "model_heavy"} or not ID_RE.fullmatch(str(item["id"])) or not isinstance(item["role"], str) or not isinstance(item["model_heavy"], bool):
            raise WeeklyIntelligenceError("stage_graph_invalid")
    maintenance = value.get("maintenance")
    if not isinstance(maintenance, dict) or set(maintenance) != {"task_id", "receipt_directory", "receipt_max_age_seconds", "safe_restart"} or maintenance.get("task_id") != "stack-maintenance":
        raise WeeklyIntelligenceError("maintenance_contract_invalid")
    if not isinstance(maintenance.get("receipt_directory"), str) or Path(maintenance["receipt_directory"]).is_absolute() or not isinstance(maintenance.get("receipt_max_age_seconds"), int) or maintenance["receipt_max_age_seconds"] <= 0 or not isinstance(maintenance.get("safe_restart"), str):
        raise WeeklyIntelligenceError("maintenance_contract_invalid")
    scheduler = value.get("scheduler")
    scheduler_fields = {
        "contract_id", "automation_id", "project_id", "day", "local_time",
        "timezone", "rrule", "model", "reasoning_effort",
        "execution_environment", "prompt_path", "prompt_digest", "enabled",
        "approval_required", "state",
    }
    if not isinstance(scheduler, dict) or set(scheduler) != scheduler_fields:
        raise WeeklyIntelligenceError("scheduler_contract_invalid")
    if (
        scheduler.get("automation_id") != "weekly-design-intelligence-loop"
        or not ID_RE.fullmatch(str(scheduler.get("project_id", "")))
        or scheduler.get("day") != "Saturday"
        or scheduler.get("local_time") != "09:00"
        or scheduler.get("timezone") != "America/Los_Angeles"
        or scheduler.get("rrule") != "FREQ=WEEKLY;BYDAY=SA;BYHOUR=9;BYMINUTE=0"
        or scheduler.get("model") != "gpt-5.6-sol"
        or scheduler.get("reasoning_effort") != "high"
        or scheduler.get("execution_environment") != "local"
        or scheduler.get("prompt_path") != "config/weekly-intelligence-automation-prompt.md"
        or not isinstance(scheduler.get("prompt_digest"), str)
        or not DIGEST_RE.fullmatch(scheduler["prompt_digest"])
        or scheduler.get("enabled") is not True
        or scheduler.get("approval_required") is not True
        or scheduler.get("state") != "active"
    ):
        raise WeeklyIntelligenceError("scheduler_contract_invalid")
    prompt_path = ROOT / scheduler["prompt_path"]
    try:
        prompt_digest = hashlib.sha256(canonical_prompt_bytes(prompt_path.read_bytes())).hexdigest()
    except OSError as exc:
        raise WeeklyIntelligenceError("scheduler_prompt_unavailable") from exc
    if prompt_digest != scheduler["prompt_digest"]:
        raise WeeklyIntelligenceError("scheduler_prompt_digest_mismatch")
    state = value.get("state")
    if not isinstance(state, dict) or set(state) != {"directory_mode", "file_mode", "receipts_directory", "reports_directory", "circuit_file", "run_state_db", "lease_seconds", "circuit_threshold", "health_window_seconds"}:
        raise WeeklyIntelligenceError("state_contract_invalid")
    if state["directory_mode"] != "0700" or state["file_mode"] != "0600" or any(not isinstance(state.get(name), str) or Path(state[name]).name != state[name] for name in ("receipts_directory", "reports_directory", "circuit_file", "run_state_db")):
        raise WeeklyIntelligenceError("state_contract_invalid")
    if not isinstance(state["lease_seconds"], int) or state["lease_seconds"] <= 0 or not isinstance(state["circuit_threshold"], int) or state["circuit_threshold"] != 3 or not isinstance(state["health_window_seconds"], int) or state["health_window_seconds"] <= 0:
        raise WeeklyIntelligenceError("state_contract_invalid")
    approval = value.get("approval")
    if approval != {
        "evidence": "bounded_model_analysis_approved",
        "promotion": "automatic_evaluated",
        "publication": "automatic_after_merge",
        "upstream_maintenance": "separate_approved_workflow",
    }:
        raise WeeklyIntelligenceError("approval_contract_invalid")
    return value


def stage_graph(config: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    config = config or load_config()
    return [dict(stage) for stage in config["stages"]]


def _safe_relative_path(value: Any, fallback: str) -> str:
    text = str(value or "")
    return text if PATH_RE.fullmatch(text) else fallback


def _owner_artifact_exists(state_dir: Path, relative: Any) -> bool:
    if not isinstance(relative, str) or PATH_RE.fullmatch(relative) is None:
        return False
    target = state_dir / relative
    try:
        resolved_state = state_dir.resolve(strict=True)
        resolved_target = target.resolve(strict=True)
    except OSError:
        return False
    if resolved_state not in resolved_target.parents or target.is_symlink():
        return False
    try:
        return _verify_file(target, mode=0o600, required=True)
    except WeeklyIntelligenceError:
        return False


def _maintenance_candidates(explicit: Any, config: Mapping[str, Any]) -> list[Path]:
    if explicit is not None:
        if isinstance(explicit, (str, Path)):
            candidate = Path(explicit)
            if candidate.is_dir():
                return sorted(candidate.glob("*.json"))
            return [candidate]
        return []
    candidates: list[Path] = []
    roots: list[Path] = []
    env_root = os.environ.get("STACK_MAINTENANCE_STATE_DIR")
    if env_root:
        roots.append(Path(env_root))
    roots.append(Path.home() / ".local" / "state" / "stack" / "maintenance")
    roots.append(Path.home() / ".local" / "state" / "stack")
    receipt_directory = Path(str(config["maintenance"]["receipt_directory"]))
    for root in roots:
        for directory in (root / "receipts", root / receipt_directory, root):
            if directory.is_dir() and not directory.is_symlink():
                candidates.extend(directory.glob("*.json"))
    return list(dict.fromkeys(candidates))


def read_latest_maintenance_receipt(
    explicit: Any = None,
    *,
    config: Mapping[str, Any] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Read and digest only the newest canonical maintenance receipt."""
    config = config or load_config()
    now = time.time() if now is None else float(now)
    # Import validation only; never execute the maintenance runner here.
    spec = importlib.util.spec_from_file_location("weekly_maintenance_contract", ROOT / "scripts" / "stack-maintenance.py")
    if spec is None or spec.loader is None:
        raise WeeklyIntelligenceError("maintenance_validator_unavailable")
    maintenance_contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(maintenance_contract)
    if isinstance(explicit, Mapping):
        records = [(None, dict(explicit))]
    else:
        records = []
        for path in _maintenance_candidates(explicit, config):
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                metadata = path.lstat()
                if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
                    continue
                data = _read_json(path)
            except WeeklyIntelligenceError:
                continue
            if isinstance(data, dict):
                records.append((path, data))
    canonical: list[tuple[Path | None, dict[str, Any], float]] = []
    for path, data in records:
        try:
            maintenance_contract.validate_receipt(data)
        except maintenance_contract.MaintenanceError:
            continue
        observed = _parse_time(data.get("observed_at"))
        if observed is None or observed > now:
            continue
        canonical.append((path, data, observed))
    if not canonical:
        return {
            "status": "alert_missing" if explicit is None else "alert_invalid",
            "receipt_digest": None,
            "age_seconds": None,
            "safe_restart": str(config["maintenance"]["safe_restart"]),
            "observed_at": None,
            "path": None,
        }
    path, data, observed = max(canonical, key=lambda item: (item[2], str(item[0] or "")))
    age = max(0, int(now - observed))
    receipt_digest = (
        hashlib.sha256(path.read_bytes()).hexdigest()
        if path is not None
        else digest(data)
    )
    if age > int(config["maintenance"]["receipt_max_age_seconds"]):
        status = "alert_stale"
    elif data.get("terminal_classification", data.get("terminal_state")) in {"blocked", "partial", "failed"}:
        status = "alert_blocked"
    else:
        status = "linked"
    return {
        "status": status,
        "receipt_digest": receipt_digest,
        "age_seconds": age,
        "safe_restart": (
            "No maintenance action required."
            if status == "linked"
            else str(config["maintenance"]["safe_restart"])
        ),
        "observed_at": _now_iso(observed),
        "path": _safe_relative_path(path.name if path else None, "maintenance-receipt.json"),
    }


def _input_bundle(
    *,
    config: Mapping[str, Any],
    source_manifest: Any,
    source_delta: Any,
    model_config: Any,
    prompt_config: Any,
    eval_config: Any,
    maintenance: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, str], str]:
    inputs = {
        "source_manifest": _without_volatile(source_manifest),
        "source_delta": _without_volatile(source_delta),
        "model_config": _without_volatile(model_config),
        "prompt_config": _without_volatile(prompt_config),
        "eval_config": _without_volatile(eval_config),
        "maintenance_receipt": maintenance.get("receipt_digest"),
    }
    input_digests = {name: digest(value) for name, value in inputs.items()}
    semantic_config = _without_volatile(config)
    overall = canonical_fingerprint({"config": semantic_config, "inputs": inputs})
    return inputs, input_digests, overall


def stage_input_fingerprints(
    *,
    config: Mapping[str, Any],
    input_digests: Mapping[str, str],
    maintenance: Mapping[str, Any],
) -> dict[str, str]:
    source = digest({
        "source_manifest": input_digests["source_manifest"],
        "source_delta": input_digests["source_delta"],
    })
    design = digest({
        "source": source,
        "model_config": input_digests["model_config"],
        "prompt_config": input_digests["prompt_config"],
    })
    retrieval = digest({"source": source, "design": design})
    candidate = digest({
        "retrieval": retrieval,
        "eval_config": input_digests["eval_config"],
    })
    return {
        "source_intake": source,
        "design_packet": design,
        "retrieval": retrieval,
        "candidate_evaluation": candidate,
        "maintenance_link": digest({"maintenance_receipt": maintenance.get("receipt_digest")}),
        "report_receipt": digest({
            "config": _without_volatile(config),
            "input": input_digests,
            "maintenance_status": maintenance.get("status"),
        }),
    }


def _load_receipts(state_dir: Path) -> list[dict[str, Any]]:
    receipts_dir = state_dir / "receipts"
    if not receipts_dir.exists():
        return []
    _verify_dir(receipts_dir, create=False)
    records: list[dict[str, Any]] = []
    for path in sorted(receipts_dir.glob("*.json")):
        try:
            _verify_file(path, required=True)
            data = _read_json(path)
            validate_receipt(data)
        except WeeklyIntelligenceError:
            continue
        if isinstance(data, dict) and data.get("task_id") == TASK_ID:
            records.append(data)
    records.sort(key=lambda item: (
        _parse_time(item.get("observed_at")) or 0,
        str(item.get("run_id", "")),
    ))
    return records


def _stage_artifact_valid(state_dir: Path, stage: Mapping[str, Any]) -> bool:
    relative = stage.get("artifact_path")
    if not _owner_artifact_exists(state_dir, relative):
        return False
    return file_digest(state_dir / relative) == stage.get("output_digest")


def latest_receipt(state_dir: str | Path) -> dict[str, Any] | None:
    records = _load_receipts(Path(state_dir))
    return records[-1] if records else None


def _prior_reusable_receipt(state_dir: Path, input_fp: str) -> dict[str, Any] | None:
    for record in reversed(_load_receipts(state_dir)):
        if (
            record.get("input_fingerprint") == input_fp
            and record.get("terminal_state") in {"no_action", "prepared", "awaiting_approval"}
            and record.get("reason_code") != "duplicate_run"
            and {stage["id"] for stage in record["stages"]} == set(STAGE_IDS)
            and all(
                stage.get("status") in {"completed", "reused"} and _stage_artifact_valid(state_dir, stage)
                for stage in record.get("stages", [])
            )
        ):
            return record
    return None


def _previous_stage_map(state_dir: Path, run_id: str | None = None) -> dict[str, dict[str, Any]]:
    for record in reversed(_load_receipts(state_dir)):
        if run_id is not None and record.get("run_id") != run_id:
            continue
        stages = record.get("stages")
        if isinstance(stages, list):
            values = {
                stage.get("id"): stage
                for stage in stages
                if isinstance(stage, dict)
                and stage.get("status") in {"completed", "reused"}
            }
            if values:
                return values
    return {}


def _circuit_path(state_dir: Path, config: Mapping[str, Any]) -> Path:
    return state_dir / str(config["state"]["circuit_file"])


def _read_circuit(state_dir: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    path = _circuit_path(state_dir, config)
    if not path.exists() and not path.is_symlink():
        return {
            "open": False,
            "strike_count": 0,
            "threshold": int(config["state"]["circuit_threshold"]),
            "blocker_digest": None,
            "input_fingerprint": None,
        }
    _verify_file(path, required=True)
    data = _read_json(path)
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("strike_count"), int)
        or not isinstance(data.get("threshold"), int)
    ):
        raise WeeklyIntelligenceError("circuit_invalid")
    data.setdefault("open", False)
    data.setdefault("blocker_digest", None)
    data.setdefault("input_fingerprint", None)
    return data


def _circuit_summary(
    circuit: Mapping[str, Any],
    *,
    transient: bool = False,
) -> dict[str, Any]:
    if transient:
        status = "transient_not_struck"
    elif circuit.get("open"):
        status = "open"
    elif circuit.get("strike_count", 0):
        status = "closed"
    else:
        status = "not_struck"
    blocker = circuit.get("blocker_digest")
    return {
        "status": status,
        "strike_count": int(circuit.get("strike_count", 0)),
        "threshold": int(circuit.get("threshold", 3)),
        "blocker_digest": blocker if isinstance(blocker, str) and DIGEST_RE.fullmatch(blocker) else None,
    }


def _manual_clear_circuit(state_dir: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    circuit = _read_circuit(state_dir, config)
    circuit.update({
        "open": False,
        "strike_count": 0,
        "blocker_digest": None,
        "input_fingerprint": None,
        "manual_clear": True,
    })
    _write_atomic_json(_circuit_path(state_dir, config), circuit, overwrite=True)
    return circuit


def _record_circuit_failure(
    state_dir: Path,
    config: Mapping[str, Any],
    *,
    input_fp: str,
    code: str,
    retry_class: str,
) -> tuple[dict[str, Any], bool]:
    circuit = _read_circuit(state_dir, config)
    if retry_class == "transient":
        return circuit, False
    if circuit.get("open"):
        return circuit, True
    blocker_digest = digest({"input_fingerprint": input_fp, "reason_code": code})
    if circuit.get("blocker_digest") == blocker_digest:
        strike_count = int(circuit.get("strike_count", 0)) + 1
    else:
        strike_count = 1
    circuit.update({
        "open": strike_count >= int(config["state"]["circuit_threshold"]),
        "strike_count": strike_count,
        "threshold": int(config["state"]["circuit_threshold"]),
        "blocker_digest": blocker_digest,
        "input_fingerprint": input_fp,
    })
    _write_atomic_json(_circuit_path(state_dir, config), circuit, overwrite=True)
    return circuit, bool(circuit["open"])


def _reset_circuit_after_success(
    state_dir: Path,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    circuit = _read_circuit(state_dir, config)
    if circuit.get("open"):
        return circuit
    if circuit.get("strike_count"):
        circuit.update({
            "open": False,
            "strike_count": 0,
            "blocker_digest": None,
            "input_fingerprint": None,
        })
        _write_atomic_json(_circuit_path(state_dir, config), circuit, overwrite=True)
    return circuit


def _invoke_adapter(adapter: Any, stage_id: str, context: Mapping[str, Any]) -> Any:
    if adapter is None:
        return {"status": "prepared"}
    if hasattr(adapter, "run") and callable(adapter.run):
        adapter = adapter.run
    if not callable(adapter):
        raise StageFailure("adapter_invalid")
    try:
        signature = inspect.signature(adapter)
        parameters = list(signature.parameters.values())
    except (TypeError, ValueError):
        parameters = []
    names = {parameter.name for parameter in parameters}
    positional = [
        parameter
        for parameter in parameters
        if parameter.kind in {
            parameter.POSITIONAL_ONLY,
            parameter.POSITIONAL_OR_KEYWORD,
        }
    ]
    try:
        if "stage" in names and "context" in names:
            return adapter(stage=stage_id, context=context)
        if any(parameter.kind == parameter.VAR_KEYWORD for parameter in parameters):
            return adapter(stage=stage_id, context=context)
        if any(parameter.kind == parameter.VAR_POSITIONAL for parameter in parameters) or len(positional) >= 2:
            return adapter(stage_id, context)
        if positional:
            return adapter(context)
        return adapter()
    except WeeklyIntelligenceError:
        raise
    except Exception as exc:
        retry_class = getattr(
            exc,
            "retry_class",
            "transient" if isinstance(exc, (TimeoutError, ConnectionError)) else "non_transient",
        )
        code = getattr(exc, "code", "adapter_failed")
        raise StageFailure(code, retry_class) from None


def _default_adapter(stage_id: str, context: Mapping[str, Any]) -> dict[str, Any]:
    # A missing integration is a block, never synthetic evidence of success.
    return {
        "status": "blocked",
        "reason_code": f"{stage_id}_adapter_not_configured",
        "retry_class": "non_transient",
    }


def _adapter_for(
    adapters: Mapping[str, Any] | Callable[..., Any] | None,
    stage_id: str,
) -> Any:
    if adapters is None:
        return _default_adapter
    if isinstance(adapters, Mapping):
        return adapters.get(stage_id, _default_adapter)
    return adapters


def _sanitize_adapter_result(
    stage_id: str,
    run_id: str,
    stage_input_fp: str,
    result: Any,
) -> tuple[str, str]:
    if result is None:
        result = {}
    if not isinstance(result, Mapping):
        result = {"value_type": type(result).__name__}
    status = str(result.get("status", "prepared"))
    if status in {"failed", "blocked", "error"}:
        retry_class = str(result.get("retry_class", "non_transient"))
        raise StageFailure(
            _safe_code(result.get("reason_code", f"{stage_id}_blocked")),
            retry_class,
        )
    output = result.get("output_digest")
    output_digest = (
        output
        if isinstance(output, str) and DIGEST_RE.fullmatch(output)
        else digest({
            "stage": stage_id,
            "input_fingerprint": stage_input_fp,
            "result": _without_volatile(dict(result)),
        })
    )
    artifact = _safe_relative_path(
        result.get("artifact_path"),
        f"artifacts/{run_id}/{stage_id}.json",
    )
    return output_digest, artifact


def _render_report(
    *,
    config: Mapping[str, Any],
    input_fp: str,
    terminal_state: str,
    maintenance_status: str,
    stages: list[dict[str, Any]],
    safe_restart: str,
    observed_at: float,
) -> str:
    try:
        template = DEFAULT_TEMPLATE.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        template = "# Weekly Stack Intelligence - {{WINDOW_LABEL}}\n\n{{STAGE_SUMMARY}}\n\n{{SAFE_RESTART}}\n"
    summary_lines = []
    for stage in stages:
        output = stage.get("output_digest") or "none"
        summary_lines.append(
            f"- {stage.get('id')} - {stage.get('status')}; output {output}"
        )
    replacements = {
        "{{WINDOW_LABEL}}": _now_iso(observed_at)[:10],
        "{{CAMPAIGN_ID}}": str(config["campaign_id"]),
        "{{TERMINAL_STATE}}": terminal_state,
        "{{INPUT_FINGERPRINT}}": input_fp,
        "{{MAINTENANCE_STATUS}}": maintenance_status,
        "{{STAGE_SUMMARY}}": "\n".join(summary_lines),
        "{{SAFE_RESTART}}": safe_restart,
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template


def scheduler_contract_status(
    config: Mapping[str, Any],
) -> str:
    scheduler = config["scheduler"]
    if scheduler.get("enabled") is not True or scheduler.get("state") != "active":
        return "blocked"
    expected_path = DEFAULT_AUTOMATION_ROOT / scheduler["automation_id"] / "automation.toml"
    candidate = Path(os.path.abspath(str(expected_path)))
    try:
        account_home = ACCOUNT_HOME.resolve(strict=True)
        relative = candidate.relative_to(account_home)
        current = account_home
        for component in relative.parts:
            current = current / component
            metadata = current.lstat()
            if (
                stat.S_ISLNK(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) & 0o022
            ):
                return "blocked"
        resolved = candidate.resolve(strict=True)
        parent = resolved.parent.stat()
        details = resolved.stat()
        document = tomllib.loads(resolved.read_text(encoding="utf-8"))
        prompt = (ROOT / scheduler["prompt_path"]).read_bytes()
    except (OSError, ValueError, UnicodeError, tomllib.TOMLDecodeError):
        return "blocked"
    if (
        resolved != candidate
        or not resolved.is_file()
        or details.st_uid != os.getuid()
        or parent.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) & 0o022
        or stat.S_IMODE(parent.st_mode) & 0o022
    ):
        return "blocked"
    target = document.get("target")
    persisted = {
        "id": document.get("id"),
        "kind": document.get("kind"),
        "status": document.get("status"),
        "rrule": document.get("rrule"),
        "model": document.get("model"),
        "reasoning_effort": document.get("reasoning_effort"),
        "execution_environment": document.get("execution_environment"),
        "target": target,
        "cwds": document.get("cwds"),
        "prompt_digest": hashlib.sha256(str(document.get("prompt", "")).encode("utf-8")).hexdigest(),
    }
    expected = {
        "id": scheduler["automation_id"],
        "kind": "cron",
        "status": "ACTIVE",
        "rrule": scheduler["rrule"],
        "model": scheduler["model"],
        "reasoning_effort": scheduler["reasoning_effort"],
        "execution_environment": scheduler["execution_environment"],
        "target": {"type": "project", "project_id": scheduler["project_id"]},
        "cwds": [str(DEFAULT_AUTOMATION_WORKDIR)],
        "prompt_digest": hashlib.sha256(canonical_prompt_bytes(prompt)).hexdigest(),
    }
    if expected["prompt_digest"] != scheduler["prompt_digest"]:
        return "mismatch"
    return "approved_and_persisted" if persisted == expected else "mismatch"


def scheduler_contract_digest(config: Mapping[str, Any]) -> str:
    scheduler = config["scheduler"]
    return digest({
        key: scheduler[key]
        for key in (
            "contract_id", "automation_id", "project_id", "day", "local_time",
            "timezone", "rrule", "model", "reasoning_effort",
            "execution_environment", "prompt_digest", "enabled",
            "approval_required", "state",
        )
    })


def eight_day_health_check(
    *,
    state_dir: str | Path,
    config: Mapping[str, Any] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Return health only after enabled-state and persisted scheduler proof."""
    config = config or load_config()
    now = time.time() if now is None else float(now)
    state_path = Path(state_dir)
    records = _load_receipts(state_path) if state_path.exists() else []
    successful = [
        record
        for record in records
        if record.get("terminal_state") in {"no_action", "prepared", "awaiting_approval"}
        and record.get("reason_code") != "duplicate_run"
        and record.get("receipt_persisted") is True
    ]
    latest = successful[-1] if successful else None
    last_success = latest.get("observed_at") if latest else None
    last_time = _parse_time(last_success) if latest else None
    age = max(0, int(now - last_time)) if last_time is not None else None
    scheduler_status = scheduler_contract_status(config)
    if scheduler_status != "approved_and_persisted":
        return {
            "status": "alert",
            "blocking_stage": "scheduler",
            "last_success": last_success,
            "age_seconds": age,
            "safe_restart": "Restore the exact active Codex automation contract, then retry the health check.",
            "scheduler_status": scheduler_status,
        }
    if (
        latest is None
        or last_time is None
        or now - last_time > int(config["state"]["health_window_seconds"])
    ):
        return {
            "status": "alert",
            "blocking_stage": "campaign",
            "last_success": last_success,
            "age_seconds": age,
            "safe_restart": "Run the campaign manually and inspect its owner-local terminal receipt before enabling automation.",
            "scheduler_status": scheduler_status,
        }
    return {
        "status": "pass",
        "blocking_stage": None,
        "last_success": last_success,
        "age_seconds": age,
        "safe_restart": "No action required.",
        "scheduler_status": scheduler_status,
    }


health_check = eight_day_health_check
check_eight_day_health = eight_day_health_check


def validate_receipt(receipt: Mapping[str, Any]) -> None:
    """Dependency-free receipt validation used by tests and the CLI boundary."""
    if not isinstance(receipt, Mapping):
        raise WeeklyIntelligenceError("receipt_not_object")
    required = {
        "schema_version",
        "task_id",
        "run_id",
        "owner_id",
        "observed_at",
        "input_fingerprint",
        "inputs",
        "stages",
        "maintenance",
        "scheduler",
        "circuit",
        "health",
        "terminal_state",
        "reason_code",
        "report_path",
        "safe_restart",
        "publication",
        "receipt_persisted",
    }
    if set(receipt) != required:
        raise WeeklyIntelligenceError("receipt_fields_invalid")
    if (
        receipt["schema_version"] != 1
        or receipt["task_id"] != TASK_ID
        or not ID_RE.fullmatch(str(receipt["run_id"]))
        or not ID_RE.fullmatch(str(receipt["owner_id"]))
        or _parse_time(receipt["observed_at"]) is None
        or not DIGEST_RE.fullmatch(str(receipt["input_fingerprint"]))
        or receipt["terminal_state"] not in TERMINAL_STATES
        or not CODE_RE.fullmatch(str(receipt["reason_code"]))
        or receipt["receipt_persisted"] is not True
    ):
        raise WeeklyIntelligenceError("receipt_identity_invalid")
    inputs = receipt["inputs"]
    if (
        not isinstance(inputs, Mapping)
        or set(inputs) != {
            "source_manifest",
            "source_delta",
            "model_config",
            "prompt_config",
            "eval_config",
            "maintenance_receipt",
        }
        or any(not DIGEST_RE.fullmatch(str(inputs[key])) for key in inputs)
    ):
        raise WeeklyIntelligenceError("receipt_inputs_invalid")
    if not isinstance(receipt["stages"], list) or not receipt["stages"]:
        raise WeeklyIntelligenceError("receipt_stages_invalid")
    for stage in receipt["stages"]:
        if (
            not isinstance(stage, Mapping)
            or set(stage)
            - {
                "id",
                "role",
                "status",
                "input_fingerprint",
                "output_digest",
                "artifact_path",
                "failure_code",
                "retry_class",
            }
            or not ID_RE.fullmatch(str(stage.get("id")))
            or stage.get("status") not in STAGE_STATUSES
            or not DIGEST_RE.fullmatch(str(stage.get("input_fingerprint")))
        ):
            raise WeeklyIntelligenceError("receipt_stage_invalid")
        if stage.get("output_digest") is not None and not DIGEST_RE.fullmatch(str(stage["output_digest"])):
            raise WeeklyIntelligenceError("receipt_stage_invalid")
        if stage.get("artifact_path") is not None and not PATH_RE.fullmatch(str(stage["artifact_path"])):
            raise WeeklyIntelligenceError("receipt_stage_invalid")
    _validate_receipt_envelope(receipt)


def _validate_receipt_envelope(receipt: Mapping[str, Any]) -> None:
    maintenance = receipt["maintenance"]
    if (
        not isinstance(maintenance, Mapping)
        or set(maintenance) != {"status", "receipt_digest", "age_seconds", "safe_restart"}
        or maintenance.get("status")
        not in {"linked", "alert_missing", "alert_stale", "alert_invalid", "alert_blocked"}
        or not isinstance(maintenance.get("safe_restart"), str)
        or not maintenance["safe_restart"]
    ):
        raise WeeklyIntelligenceError("receipt_maintenance_invalid")
    if (
        maintenance.get("receipt_digest") is not None
        and not DIGEST_RE.fullmatch(str(maintenance["receipt_digest"]))
    ):
        raise WeeklyIntelligenceError("receipt_maintenance_invalid")
    scheduler = receipt["scheduler"]
    if (
        not isinstance(scheduler, Mapping)
        or set(scheduler) != {"status", "contract_id", "approval_required"}
        or scheduler.get("status")
        not in {"blocked", "approved_and_persisted", "mismatch", "not_checked"}
        or scheduler.get("approval_required") is not True
    ):
        raise WeeklyIntelligenceError("receipt_scheduler_invalid")
    circuit = receipt["circuit"]
    if (
        not isinstance(circuit, Mapping)
        or set(circuit) != {"status", "strike_count", "threshold", "blocker_digest"}
        or circuit.get("status")
        not in {"closed", "open", "not_struck", "transient_not_struck"}
        or not isinstance(circuit.get("strike_count"), int)
        or not isinstance(circuit.get("threshold"), int)
    ):
        raise WeeklyIntelligenceError("receipt_circuit_invalid")
    if (
        circuit.get("blocker_digest") is not None
        and not DIGEST_RE.fullmatch(str(circuit["blocker_digest"]))
    ):
        raise WeeklyIntelligenceError("receipt_circuit_invalid")
    health = receipt["health"]
    if (
        not isinstance(health, Mapping)
        or set(health) != {
            "status",
            "blocking_stage",
            "last_success",
            "age_seconds",
            "safe_restart",
        }
        or health.get("status") not in {"pass", "alert"}
        or not isinstance(health.get("safe_restart"), str)
        or not health["safe_restart"]
    ):
        raise WeeklyIntelligenceError("receipt_health_invalid")
    if not isinstance(receipt.get("safe_restart"), str) or not receipt["safe_restart"]:
        raise WeeklyIntelligenceError("receipt_restart_invalid")
    publication = receipt["publication"]
    if publication != {"status": "not_published", "promotion_approved": False}:
        raise WeeklyIntelligenceError("receipt_publication_invalid")


def _build_stage_record(
    stage: Mapping[str, Any],
    stage_fp: str,
    *,
    status: str = "pending",
    output_digest: str | None = None,
    artifact_path: str | None = None,
    failure_code: str | None = None,
    retry_class: str = "none",
) -> dict[str, Any]:
    return {
        "id": str(stage["id"]),
        "role": str(stage["role"]),
        "status": status,
        "input_fingerprint": stage_fp,
        "output_digest": output_digest,
        "artifact_path": artifact_path,
        "failure_code": failure_code,
        "retry_class": retry_class,
    }


def _receipt_path(state_dir: Path, run_id: str) -> Path:
    receipts_dir = state_dir / "receipts"
    _verify_dir(receipts_dir)
    base = receipts_dir / f"{run_id}.json"
    if not base.exists() and not base.is_symlink():
        return base
    index = 2
    while True:
        candidate = receipts_dir / f"{run_id}-{index}.json"
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
        index += 1


def _safe_restart_for(
    terminal_state: str,
    reason_code: str,
    maintenance: Mapping[str, Any],
) -> str:
    if reason_code == "circuit_open":
        return "Clear the campaign circuit manually after reviewing the repeated blocker, then retry the failed run."
    if maintenance.get("status") != "linked":
        return str(
            maintenance.get("safe_restart")
            or "Repair the linked maintenance evidence and retry manually."
        )
    if terminal_state in {"partial", "failed"}:
        return "Repair the failed child, then resume the run by its exact run ID; completed checkpoints are retained."
    if terminal_state == "prepared" and reason_code == "automatic_promotion_pending":
        return "Continue the approved automatic evaluation and publication tail; weak or rejected candidates create no review queue."
    if terminal_state == "awaiting_approval":
        return "Review the owner-local packet; promotion and publication remain separately approval-gated."
    return "No action required."


class WeeklyIntelligenceCoordinator:
    """Testable campaign coordinator with injectable stage adapters."""

    def __init__(
        self,
        *,
        config_path: str | Path = DEFAULT_CONFIG,
        state_dir: str | Path | None = None,
        owner_id: str | None = None,
        adapters: Mapping[str, Any] | Callable[..., Any] | None = None,
        now: float | None = None,
    ):
        self.config_path = Path(config_path)
        self.config = load_config(self.config_path)
        raw_state = (
            state_dir
            or os.environ.get("STACK_WEEKLY_INTELLIGENCE_STATE_DIR")
            or str(Path.home() / ".local" / "state" / "stack" / "weekly-intelligence")
        )
        self.state_dir = Path(raw_state)
        self.owner_id = _safe_id(
            owner_id or os.environ.get("STACK_WEEKLY_INTELLIGENCE_OWNER") or "codex",
            "owner",
        )
        self.adapters = adapters
        self.now = time.time() if now is None else float(now)

    def _prepare_state(self) -> tuple[Path, Path, Path]:
        _verify_dir(self.state_dir)
        receipts = self.state_dir / str(self.config["state"]["receipts_directory"])
        reports = self.state_dir / str(self.config["state"]["reports_directory"])
        _verify_dir(receipts)
        _verify_dir(reports)
        return self.state_dir, receipts, reports

    def _persist_stage_artifact(
        self,
        *,
        run_id: str,
        stage_id: str,
        stage_input_fingerprint: str,
        output_digest: str,
        requested_path: str | None,
    ) -> str:
        if requested_path is not None:
            if PATH_RE.fullmatch(requested_path) is None:
                raise WeeklyIntelligenceError("stage_artifact_path_invalid")
            if not _owner_artifact_exists(self.state_dir, requested_path):
                raise WeeklyIntelligenceError("stage_artifact_missing")
            return requested_path
        relative = f"artifacts/{run_id}/{stage_id}.json"
        target = self.state_dir / relative
        _write_atomic_json(
            target,
            {
                "schema_version": 1,
                "task_id": TASK_ID,
                "run_id": run_id,
                "stage_id": stage_id,
                "input_fingerprint": stage_input_fingerprint,
                "output_digest": output_digest,
                "private_payload_included": False,
            },
        )
        return relative

    def _make_inputs(
        self,
        inputs: Mapping[str, Any] | None = None,
        **values: Any,
    ) -> tuple[
        dict[str, Any],
        dict[str, str],
        str,
        dict[str, str],
        dict[str, Any],
    ]:
        inputs = dict(inputs or {})
        source_manifest = _coerce_input(
            values.get("source_manifest") if values.get("source_manifest") is not None else inputs.get("source_manifest"),
            {"sources": []},
        )
        source_delta = _coerce_input(
            values.get("source_delta") if values.get("source_delta") is not None else inputs.get("source_delta"),
            {"changes": []},
        )
        model_config = _coerce_input(
            values.get("model_config") if values.get("model_config") is not None else inputs.get("model_config"),
            {},
        )
        prompt_config = _coerce_input(
            values.get("prompt_config") if values.get("prompt_config") is not None else inputs.get("prompt_config"),
            {},
        )
        eval_config = _coerce_input(
            values.get("eval_config") if values.get("eval_config") is not None else inputs.get("eval_config"),
            {},
        )
        maintenance_explicit = values.get("maintenance_receipt")
        if maintenance_explicit is None:
            maintenance_explicit = inputs.get("maintenance_receipt")
        maintenance = read_latest_maintenance_receipt(
            maintenance_explicit,
            config=self.config,
            now=self.now,
        )
        bundle, input_digests, overall = _input_bundle(
            config=self.config,
            source_manifest=source_manifest,
            source_delta=source_delta,
            model_config=model_config,
            prompt_config=prompt_config,
            eval_config=eval_config,
            maintenance=maintenance,
        )
        stage_fps = stage_input_fingerprints(
            config=self.config,
            input_digests=input_digests,
            maintenance=maintenance,
        )
        context_inputs = {
            "source_manifest": source_manifest,
            "source_delta": source_delta,
            "model_config": model_config,
            "prompt_config": prompt_config,
            "eval_config": eval_config,
        }
        return (
            bundle,
            input_digests,
            overall,
            stage_fps,
            {"maintenance": maintenance, "raw": context_inputs},
        )

    def _new_run_id(
        self,
        requested: str | None,
        input_fp: str,
        *,
        noop: bool = False,
    ) -> str:
        if requested and ID_RE.fullmatch(requested):
            if not noop:
                return requested
            return _safe_id(f"noop-{input_fp[:24]}", "noop")
        return _safe_id(
            ("noop-" if noop else "weekly-") + input_fp[:24],
            "weekly",
        )

    def _store_and_run(
        self,
        run_id: str,
        *,
        resume: bool,
    ) -> tuple[Any, dict[str, Any]]:
        module = workflow_store_module()
        db_path = self.state_dir / str(self.config["state"]["run_state_db"])
        store = module.WorkflowStore(db_path)
        try:
            try:
                snapshot = store.snapshot(run_id)
                existed = True
            except Exception:
                existed = False
                snapshot = None
            if not existed:
                try:
                    snapshot = store.create_run(
                        run_id,
                        "project:stack-weekly-intelligence",
                        self.owner_id,
                        str(ROOT),
                        max_children=len(STAGE_IDS),
                        approval_required=True,
                    )
                    for stage in stage_graph(self.config):
                        snapshot = store.add_child(
                            run_id,
                            stage["id"],
                            stage["role"],
                            "weekly-coordinator",
                            self.owner_id,
                            str(ROOT),
                        )
                except Exception as exc:
                    # A concurrent creator may have won between snapshot and
                    # create; use its graph instead of proposing a duplicate.
                    if "already exists" not in str(exc):
                        raise
                    snapshot = store.snapshot(run_id)
            elif resume and snapshot.get("status") in {"blocked", "cancelled"}:
                store.resume(run_id)
                snapshot = store.snapshot(run_id)
            return store, snapshot
        except Exception:
            store.close()
            raise

    def _health_for_terminal(
        self,
        terminal_state: str,
        stages: list[dict[str, Any]],
        maintenance: Mapping[str, Any],
    ) -> dict[str, Any]:
        if terminal_state in {"prepared", "awaiting_approval", "no_action"}:
            return {
                "status": "pass",
                "blocking_stage": None,
                "last_success": _now_iso(self.now),
                "age_seconds": 0,
                "safe_restart": "No action required.",
            }
        blocking = next(
            (
                stage["id"]
                for stage in stages
                if stage.get("status")
                in {"failed", "blocked", "leased_elsewhere", "pending", "cancelled"}
            ),
            None,
        )
        return {
            "status": "alert",
            "blocking_stage": blocking or (
                "maintenance_link"
                if maintenance.get("status") != "linked"
                else None
            ),
            "last_success": None,
            "age_seconds": None,
            "safe_restart": "Repair the blocking stage and use the exact safe restart action in this receipt.",
        }

    def run(
        self,
        inputs: Mapping[str, Any] | None = None,
        *,
        run_id: str | None = None,
        resume: bool = False,
        manual_clear: bool = False,
        now: float | None = None,
        **values: Any,
    ) -> dict[str, Any]:
        if "scheduler_evidence" in values or "enabled_evidence" in values:
            raise WeeklyIntelligenceError("self_issued_scheduler_evidence_rejected")
        if now is not None:
            self.now = float(now)
        self._prepare_state()
        _, input_digests, input_fp, stage_fps, data = self._make_inputs(
            inputs,
            **values,
        )
        maintenance = data["maintenance"]
        if manual_clear:
            _manual_clear_circuit(self.state_dir, self.config)
        circuit = _read_circuit(self.state_dir, self.config)
        if circuit.get("open") and not manual_clear:
            blocked_stages = [
                _build_stage_record(
                    stage,
                    stage_fps[stage["id"]],
                    status="blocked",
                    failure_code="circuit_open",
                    retry_class="non_transient",
                )
                for stage in stage_graph(self.config)
            ]
            return self._write_terminal_receipt(
                run_id=self._new_run_id(run_id, input_fp, noop=True),
                owner_id=self.owner_id,
                input_digests=input_digests,
                input_fp=input_fp,
                stage_fps=stage_fps,
                maintenance=maintenance,
                stages=blocked_stages,
                terminal_state="blocked",
                reason_code="circuit_open",
                report_path=None,
                circuit=_circuit_summary(circuit),
                safe_restart=_safe_restart_for("blocked", "circuit_open", maintenance),
                health_stage="circuit",
            )

        prior_noop = None if resume else _prior_reusable_receipt(
            self.state_dir,
            input_fp,
        )
        if prior_noop is not None and maintenance.get("status") == "linked":
            noop_stages = []
            prior_stages = {
                stage.get("id"): stage
                for stage in prior_noop.get("stages", [])
                if isinstance(stage, dict)
            }
            for stage in stage_graph(self.config):
                old = prior_stages.get(stage["id"], {})
                noop_stages.append(
                    _build_stage_record(
                        stage,
                        stage_fps[stage["id"]],
                        status="reused",
                        output_digest=old.get("output_digest"),
                        artifact_path=old.get("artifact_path"),
                    )
                )
            return self._write_terminal_receipt(
                run_id=self._new_run_id(run_id, input_fp, noop=True),
                owner_id=self.owner_id,
                input_digests=input_digests,
                input_fp=input_fp,
                stage_fps=stage_fps,
                maintenance=maintenance,
                stages=noop_stages,
                terminal_state="no_action",
                reason_code="no_action",
                report_path=None,
                circuit=_circuit_summary(circuit),
                safe_restart="No action required; semantic inputs are unchanged.",
                health_stage=None,
            )

        actual_run_id = self._new_run_id(run_id, input_fp, noop=False)
        try:
            store, _ = self._store_and_run(actual_run_id, resume=resume)
        except Exception as exc:
            code = _safe_code(
                getattr(exc, "code", "workflow_store_failed"),
                "workflow_store_failed",
            )
            circuit, _ = _record_circuit_failure(
                self.state_dir,
                self.config,
                input_fp=input_fp,
                code=code,
                retry_class="non_transient",
            )
            return self._write_terminal_receipt(
                run_id=actual_run_id,
                owner_id=self.owner_id,
                input_digests=input_digests,
                input_fp=input_fp,
                stage_fps=stage_fps,
                maintenance=maintenance,
                stages=[
                    _build_stage_record(
                        stage,
                        stage_fps[stage["id"]],
                        status="blocked",
                        failure_code=code,
                        retry_class="non_transient",
                    )
                    for stage in stage_graph(self.config)
                ],
                terminal_state="failed",
                reason_code=code,
                report_path=None,
                circuit=_circuit_summary(circuit),
                safe_restart=_safe_restart_for("failed", code, maintenance),
                health_stage=code,
            )
        checkpoint_stages = _previous_stage_map(self.state_dir, actual_run_id)
        previous_stages = _previous_stage_map(self.state_dir)
        stage_records: list[dict[str, Any]] = []
        failure_code: str | None = None
        failure_retry = "none"
        lease_lost = False
        try:
            for stage in stage_graph(self.config):
                stage_id = str(stage["id"])
                snapshot = store.snapshot(actual_run_id)
                current = next(
                    (
                        child
                        for child in snapshot["children"]
                        if child["child_id"] == stage_id
                    ),
                    None,
                )
                if current is None:
                    stage_records.append(
                        _build_stage_record(
                            stage,
                            stage_fps[stage_id],
                            status="pending",
                        )
                    )
                    continue
                if current["status"] == "completed":
                    prior = checkpoint_stages.get(stage_id, {})
                    artifact = prior.get(
                        "artifact_path",
                        f"artifacts/{actual_run_id}/{stage_id}.json",
                    )
                    if prior.get("input_fingerprint") != stage_fps[stage_id] or not _stage_artifact_valid(self.state_dir, prior):
                        failure_code = "checkpoint_evidence_invalid"
                        failure_retry = "non_transient"
                        stage_records.append(
                            _build_stage_record(
                                stage,
                                stage_fps[stage_id],
                                status="blocked",
                                failure_code=failure_code,
                                retry_class=failure_retry,
                            )
                        )
                        break
                    stage_records.append(
                        _build_stage_record(
                            stage,
                            stage_fps[stage_id],
                            status="reused",
                            output_digest=prior.get("output_digest"),
                            artifact_path=artifact,
                        )
                    )
                    continue
                if current["status"] in {"failed", "cancelled"} and not resume:
                    failure_code = current.get("failure") or "child_not_resumed"
                    failure_retry = "non_transient"
                    stage_records.append(
                        _build_stage_record(
                            stage,
                            stage_fps[stage_id],
                            status=current["status"],
                            failure_code=failure_code,
                            retry_class=failure_retry,
                        )
                    )
                    break
                lease_owner = _safe_id(
                    f"{self.owner_id}-{actual_run_id}-{stage_id}",
                    "lease",
                )
                if not store.claim_child(
                    actual_run_id,
                    stage_id,
                    lease_owner,
                    lease_seconds=int(self.config["state"]["lease_seconds"]),
                    now=self.now,
                ):
                    lease_lost = True
                    stage_records.append(
                        _build_stage_record(
                            stage,
                            stage_fps[stage_id],
                            status="leased_elsewhere",
                            failure_code="lease_not_acquired",
                            retry_class="none",
                        )
                    )
                    break
                prior = previous_stages.get(stage_id)
                result = None
                try:
                    if (
                        prior
                        and prior.get("status") in {"completed", "reused"}
                        and prior.get("input_fingerprint") == stage_fps[stage_id]
                        and stage.get("model_heavy")
                        and _stage_artifact_valid(self.state_dir, prior)
                    ):
                        output_digest = prior.get("output_digest") or digest({
                            "stage": stage_id,
                            "input": stage_fps[stage_id],
                        })
                        artifact_path = prior.get(
                            "artifact_path",
                            f"artifacts/{actual_run_id}/{stage_id}.json",
                        )
                        stage_status = "reused"
                    else:
                        context = {
                            "campaign_id": TASK_ID,
                            "run_id": actual_run_id,
                            "owner_id": self.owner_id,
                            "stage": stage_id,
                            "stage_input_fingerprint": stage_fps[stage_id],
                            "input_fingerprint": input_fp,
                            "inputs": data["raw"],
                            "maintenance": maintenance,
                            "provider_egress": "deny",
                            "analysis_budget": self.config["analysis_budget"],
                        }
                        result = _invoke_adapter(
                            _adapter_for(self.adapters, stage_id),
                            stage_id,
                            context,
                        )
                        output_digest, artifact_path = _sanitize_adapter_result(
                            stage_id,
                            actual_run_id,
                            stage_fps[stage_id],
                            result,
                        )
                        stage_status = "completed"
                    if stage_id == "report_receipt":
                        artifact_path = f"reports/{actual_run_id}.md"
                        provisional_terminal = (
                            "prepared"
                            if maintenance.get("status") == "linked"
                            else "blocked"
                        )
                        provisional_reason = (
                            "automatic_promotion_pending"
                            if provisional_terminal == "prepared"
                            else str(maintenance.get("status") or "maintenance_alert")
                        )
                        report_file = self.state_dir / artifact_path
                        if not report_file.exists() and not report_file.is_symlink():
                            _write_atomic_text(
                                report_file,
                                _render_report(
                                    config=self.config,
                                    input_fp=input_fp,
                                    terminal_state=provisional_terminal,
                                    maintenance_status=str(maintenance.get("status")),
                                    stages=[
                                        *stage_records,
                                        _build_stage_record(
                                            stage,
                                            stage_fps[stage_id],
                                            status=stage_status,
                                            output_digest=output_digest,
                                            artifact_path=artifact_path,
                                        ),
                                    ],
                                    safe_restart=_safe_restart_for(
                                        provisional_terminal,
                                        provisional_reason,
                                        maintenance,
                                    ),
                                    observed_at=self.now,
                                ),
                            )
                        if not _owner_artifact_exists(self.state_dir, artifact_path):
                            raise WeeklyIntelligenceError("report_write_failed")
                    else:
                        artifact_path = self._persist_stage_artifact(
                            run_id=actual_run_id,
                            stage_id=stage_id,
                            stage_input_fingerprint=stage_fps[stage_id],
                            output_digest=output_digest,
                            requested_path=(
                                artifact_path
                                if result is not None
                                and isinstance(result, Mapping)
                                and result.get("artifact_path") is not None
                                else None
                            ) if stage_status == "completed" else artifact_path,
                        )
                    # Receipts bind persisted bytes, including real domain artifacts.
                    persisted_digest = file_digest(self.state_dir / artifact_path)
                    if stage_status == "completed" and isinstance(result, Mapping) and result.get("artifact_path") is not None and persisted_digest != output_digest:
                        raise WeeklyIntelligenceError("stage_artifact_digest_mismatch")
                    output_digest = persisted_digest
                    store.checkpoint(
                        actual_run_id,
                        stage_id,
                        lease_owner,
                        artifact_path,
                    )
                    store.finish_child(actual_run_id, stage_id, lease_owner)
                    stage_records.append(
                        _build_stage_record(
                            stage,
                            stage_fps[stage_id],
                            status=stage_status,
                            output_digest=output_digest,
                            artifact_path=artifact_path,
                        )
                    )
                except StageFailure as exc:
                    failure_code = exc.code
                    failure_retry = exc.retry_class
                    failed_artifact = result if isinstance(result, Mapping) else {}
                    artifact_verified = _stage_artifact_valid(self.state_dir, failed_artifact)
                    try:
                        store.finish_child(
                            actual_run_id,
                            stage_id,
                            lease_owner,
                            failed=True,
                            failure=failure_code,
                        )
                    except Exception:
                        pass
                    stage_records.append(
                        _build_stage_record(
                            stage,
                            stage_fps[stage_id],
                            status="failed",
                            artifact_path=failed_artifact.get("artifact_path") if artifact_verified else None,
                            output_digest=failed_artifact.get("output_digest") if artifact_verified else None,
                            failure_code=failure_code,
                            retry_class=failure_retry,
                        )
                    )
                    break
                except Exception as exc:
                    failure_code = _safe_code(
                        getattr(exc, "code", "stage_failed"),
                        "stage_failed",
                    )
                    failure_retry = (
                        "transient"
                        if isinstance(exc, (TimeoutError, ConnectionError))
                        else "non_transient"
                    )
                    try:
                        store.finish_child(
                            actual_run_id,
                            stage_id,
                            lease_owner,
                            failed=True,
                            failure=failure_code,
                        )
                    except Exception:
                        pass
                    stage_records.append(
                        _build_stage_record(
                            stage,
                            stage_fps[stage_id],
                            status="failed",
                            failure_code=failure_code,
                            retry_class=failure_retry,
                        )
                    )
                    break

            # Children not visited remain pending and stay represented in the
            # receipt. Resume reclaims failed/cancelled children while completed
            # checkpoints are never re-run.
            existing_ids = {stage["id"] for stage in stage_records}
            final_snapshot = store.snapshot(actual_run_id)
            for stage in stage_graph(self.config):
                if stage["id"] not in existing_ids:
                    child = next(
                        (
                            item
                            for item in final_snapshot["children"]
                            if item["child_id"] == stage["id"]
                        ),
                        {},
                    )
                    status = child.get("status", "pending")
                    if status not in STAGE_STATUSES:
                        status = "pending"
                    stage_records.append(
                        _build_stage_record(
                            stage,
                            stage_fps[stage["id"]],
                            status=status,
                            failure_code=child.get("failure"),
                        )
                    )
            stage_records.sort(
                key=lambda item: STAGE_IDS.index(item["id"])
            )

            if failure_code:
                circuit, _ = _record_circuit_failure(
                    self.state_dir,
                    self.config,
                    input_fp=input_fp,
                    code=failure_code,
                    retry_class=failure_retry,
                )
                terminal_state = (
                    "partial"
                    if any(
                        item["status"] in {"completed", "reused"}
                        for item in stage_records
                    )
                    else "failed"
                )
                reason_code = failure_code
            elif lease_lost:
                circuit = _read_circuit(self.state_dir, self.config)
                terminal_state, reason_code = "no_action", "duplicate_run"
            elif maintenance.get("status") != "linked":
                circuit, _ = _record_circuit_failure(
                    self.state_dir,
                    self.config,
                    input_fp=input_fp,
                    code=maintenance["status"],
                    retry_class="non_transient",
                )
                terminal_state, reason_code = "blocked", maintenance["status"]
            else:
                circuit = _reset_circuit_after_success(
                    self.state_dir,
                    self.config,
                )
                terminal_state, reason_code = (
                    "prepared",
                    "automatic_promotion_pending",
                )

            report_stage = next(
                (
                    item
                    for item in stage_records
                    if item["id"] == "report_receipt"
                    and item["status"] in {"completed", "reused"}
                ),
                None,
            )
            report_path = report_stage.get("artifact_path") if report_stage else None
            if report_stage and report_path:
                report_file = self.state_dir / report_path
                if not report_file.exists():
                    _write_atomic_text(
                        report_file,
                        _render_report(
                            config=self.config,
                            input_fp=input_fp,
                            terminal_state=terminal_state,
                            maintenance_status=maintenance["status"],
                            stages=stage_records,
                            safe_restart=_safe_restart_for(
                                terminal_state,
                                reason_code,
                                maintenance,
                            ),
                            observed_at=self.now,
                        ),
                    )
                elif report_file.is_symlink():
                    raise WeeklyIntelligenceError("report_symlink")
            health = self._health_for_terminal(
                terminal_state,
                stage_records,
                maintenance,
            )
            if reason_code == "duplicate_run":
                health = {
                    "status": "alert",
                    "blocking_stage": "concurrent_campaign",
                    "last_success": None,
                    "age_seconds": None,
                    "safe_restart": "No action required; the lease-owning campaign remains authoritative.",
                }
            scheduler = {
                "status": scheduler_contract_status(
                    self.config,
                ),
                "contract_id": self.config["scheduler"]["contract_id"],
                "approval_required": True,
            }
            receipt = {
                "schema_version": 1,
                "task_id": TASK_ID,
                "run_id": actual_run_id,
                "owner_id": self.owner_id,
                "observed_at": _now_iso(self.now),
                "input_fingerprint": input_fp,
                "inputs": input_digests,
                "stages": stage_records,
                "maintenance": {
                    key: maintenance.get(key)
                    for key in (
                        "status",
                        "receipt_digest",
                        "age_seconds",
                        "safe_restart",
                    )
                },
                "scheduler": scheduler,
                "circuit": _circuit_summary(
                    circuit,
                    transient=failure_retry == "transient",
                ),
                "health": health,
                "terminal_state": terminal_state,
                "reason_code": reason_code,
                "report_path": report_path,
                "safe_restart": _safe_restart_for(
                    terminal_state,
                    reason_code,
                    maintenance,
                ),
                "publication": {
                    "status": "not_published",
                    "promotion_approved": False,
                },
                "receipt_persisted": True,
            }
            if terminal_state in {"prepared", "awaiting_approval"} and report_path is None:
                receipt["terminal_state"] = "partial"
                receipt["reason_code"] = "report_not_written"
                receipt["safe_restart"] = _safe_restart_for(
                    "partial",
                    "report_not_written",
                    maintenance,
                )
            return self._persist_receipt(receipt)
        finally:
            store.close()

    def _persist_receipt(self, receipt: dict[str, Any]) -> dict[str, Any]:
        validate_receipt(receipt)
        target = _receipt_path(self.state_dir, str(receipt["run_id"]))
        _write_atomic_json(target, receipt)
        return receipt

    def _write_terminal_receipt(
        self,
        *,
        run_id: str,
        owner_id: str,
        input_digests: Mapping[str, str],
        input_fp: str,
        stage_fps: Mapping[str, str],
        maintenance: Mapping[str, Any],
        stages: list[dict[str, Any]],
        terminal_state: str,
        reason_code: str,
        report_path: str | None,
        circuit: Mapping[str, Any],
        safe_restart: str,
        health_stage: str | None,
    ) -> dict[str, Any]:
        health = {
            "status": "pass" if terminal_state == "no_action" else "alert",
            "blocking_stage": health_stage,
            "last_success": _now_iso(self.now) if terminal_state == "no_action" else None,
            "age_seconds": 0 if terminal_state == "no_action" else None,
            "safe_restart": safe_restart,
        }
        receipt = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "run_id": _safe_id(run_id, "weekly"),
            "owner_id": owner_id,
            "observed_at": _now_iso(self.now),
            "input_fingerprint": input_fp,
            "inputs": dict(input_digests),
            "stages": stages,
            "maintenance": {
                key: maintenance.get(key)
                for key in (
                    "status",
                    "receipt_digest",
                    "age_seconds",
                    "safe_restart",
                )
            },
            "scheduler": {
                "status": scheduler_contract_status(
                    self.config,
                ),
                "contract_id": self.config["scheduler"]["contract_id"],
                "approval_required": True,
            },
            "circuit": dict(circuit),
            "health": health,
            "terminal_state": terminal_state,
            "reason_code": _safe_code(reason_code, "campaign_failed"),
            "report_path": report_path,
            "safe_restart": safe_restart,
            "publication": {
                "status": "not_published",
                "promotion_approved": False,
            },
            "receipt_persisted": True,
        }
        return self._persist_receipt(receipt)


def run_campaign(
    inputs: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Convenience API used by tests and local callers."""
    config_path = kwargs.pop("config_path", DEFAULT_CONFIG)
    state_dir = kwargs.pop("state_dir", None)
    owner_id = kwargs.pop("owner_id", None)
    adapters = kwargs.pop("adapters", None)
    local_adapter_config = kwargs.pop("local_adapter_config", None)
    now = kwargs.pop("now", None)
    coordinator = WeeklyIntelligenceCoordinator(
        config_path=config_path,
        state_dir=state_dir,
        owner_id=owner_id,
        adapters=adapters,
        now=now,
    )
    if local_adapter_config is not None:
        if adapters is not None:
            raise WeeklyIntelligenceError("local_adapter_override_forbidden")
        supplied = dict(inputs or {})
        semantic_keys = {"source_manifest", "source_delta", "model_config", "prompt_config", "eval_config"}
        if semantic_keys.intersection(supplied) or any(kwargs.get(key) is not None for key in semantic_keys):
            raise WeeklyIntelligenceError("local_adapter_input_override_forbidden")
        spec = importlib.util.spec_from_file_location("weekly_local_adapters", ROOT / "scripts" / "weekly_local_adapters.py")
        if spec is None or spec.loader is None:
            raise WeeklyIntelligenceError("local_adapters_unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            coordinator.adapters = module.LocalPreparationAdapters(
                Path(local_adapter_config),
                coordinator.state_dir,
                as_of=_now_iso(coordinator.now),
            )
            supplied.update(coordinator.adapters.campaign_inputs())
        except module.LocalAdapterError as exc:
            raise WeeklyIntelligenceError(exc.code) from exc
        inputs = supplied
    return coordinator.run(inputs, **kwargs)


WeeklyCampaign = WeeklyIntelligenceCoordinator
CampaignCoordinator = WeeklyIntelligenceCoordinator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--state-dir", default=None)
    parser.add_argument("--owner-id", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--manual-clear", action="store_true")
    parser.add_argument("--source-manifest", default=None)
    parser.add_argument("--source-delta", default=None)
    parser.add_argument("--model-config", default=None)
    parser.add_argument("--prompt-config", default=None)
    parser.add_argument("--eval-config", default=None)
    parser.add_argument("--maintenance-receipt", default=None)
    parser.add_argument("--local-adapter-config", type=Path, help="Owner-local exported inputs; no live provider or source operations")
    parser.add_argument(
        "--input-json",
        default=None,
        help="Owner-selected JSON object containing campaign inputs",
    )
    parser.add_argument("--now", type=float, default=None)
    args = parser.parse_args(argv)
    try:
        inputs = _read_owner_json(Path(args.input_json)) if args.input_json else None
        if inputs is not None and not isinstance(inputs, dict):
            raise WeeklyIntelligenceError("input_not_object")
        receipt = run_campaign(
            inputs,
            config_path=args.config,
            state_dir=args.state_dir,
            owner_id=args.owner_id,
            run_id=args.run_id,
            resume=args.resume,
            manual_clear=args.manual_clear,
            source_manifest=args.source_manifest,
            source_delta=args.source_delta,
            model_config=args.model_config,
            prompt_config=args.prompt_config,
            eval_config=args.eval_config,
            maintenance_receipt=args.maintenance_receipt,
            local_adapter_config=args.local_adapter_config,
            now=args.now,
        )
        print(canonical_json(receipt))
        return 0 if receipt["terminal_state"] in {
            "no_action",
            "prepared",
            "awaiting_approval",
        } else 1
    except WeeklyIntelligenceError as exc:
        print(
            canonical_json({
                "task_id": TASK_ID,
                "terminal_state": "failed",
                "reason_code": exc.code,
            }),
            file=sys.stderr,
        )
        return 2
    except Exception:
        print(
            canonical_json({
                "task_id": TASK_ID,
                "terminal_state": "failed",
                "reason_code": "campaign_failed",
            }),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
