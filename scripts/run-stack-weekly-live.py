#!/usr/bin/env python3
"""Run Stack's approved local weekly bookmark and design-intelligence loop.

The live lane reads Field Theory, imports missing x-bookmarks without
embeddings, and then runs the review-only weekly coordinator. It never enables
Direct X/OAuth, provider egress, skill promotion, or runtime publication.
"""

from __future__ import annotations

import json
import os
import pwd
import stat
import subprocess
import sys
import importlib.util
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ACCOUNT_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
LIVE_ROOT = ACCOUNT_HOME / ".local" / "state" / "stack" / "weekly-intelligence" / "live"
FIELD_THEORY_DB = ACCOUNT_HOME / ".ft-bookmarks" / "bookmarks.db"
GBRAIN_SOURCE_ROOT = ACCOUNT_HOME / ".gbrain" / "source-roots" / "x-bookmarks-native"
GBRAIN_CLI = ACCOUNT_HOME / ".bun" / "bin" / "gbrain"
FIXED_PATH = f"{ACCOUNT_HOME}/.bun/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

WEEKLY_SPEC = importlib.util.spec_from_file_location(
    "stack_weekly_live_contract",
    ROOT / "scripts" / "run-stack-weekly-intelligence.py",
)
if WEEKLY_SPEC is None or WEEKLY_SPEC.loader is None:
    raise RuntimeError("weekly_contract_unavailable")
WEEKLY = importlib.util.module_from_spec(WEEKLY_SPEC)
WEEKLY_SPEC.loader.exec_module(WEEKLY)
WEEKLY.DEFAULT_AUTOMATION_ROOT = ACCOUNT_HOME / ".codex" / "automations"


class LiveLoopError(RuntimeError):
    pass


def _allowed_system_alias(path: Path) -> bool:
    expected = {
        Path("/tmp"): Path("/private/tmp"),
        Path("/var"): Path("/private/var"),
        Path("/etc"): Path("/private/etc"),
    }.get(path)
    return expected is not None and Path(os.path.realpath(path)) == expected


def _reject_symlink_ancestors(path: Path, *, allow_missing_leaf: bool = False, allow_leaf_symlink: bool = False) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current = current / component
        try:
            details = current.lstat()
        except FileNotFoundError:
            if allow_missing_leaf and current == path:
                return
            raise LiveLoopError("owner_local_path_unavailable") from None
        except OSError:
            raise LiveLoopError("owner_local_path_unavailable") from None
        if stat.S_ISLNK(details.st_mode):
            if current == path and allow_leaf_symlink:
                continue
            if not _allowed_system_alias(current):
                raise LiveLoopError("owner_local_symlink_detected")


def _inside_account_home(path: Path) -> bool:
    try:
        path.relative_to(ACCOUNT_HOME.resolve(strict=True))
        return True
    except (OSError, ValueError):
        return False


def _private_path(
    path: Path,
    *,
    directory: bool = False,
    private: bool = True,
    executable: bool = False,
    allow_leaf_symlink: bool = False,
) -> Path:
    lexical = Path(os.path.abspath(str(path.expanduser())))
    _reject_symlink_ancestors(lexical, allow_leaf_symlink=allow_leaf_symlink)
    resolved = lexical.resolve(strict=True)
    details = resolved.lstat()
    if not _inside_account_home(resolved) or details.st_uid != os.getuid():
        raise LiveLoopError("owner_local_path_invalid")
    if directory:
        mode = stat.S_IMODE(details.st_mode)
        if not stat.S_ISDIR(details.st_mode) or mode & 0o022 or private and mode != 0o700:
            raise LiveLoopError("owner_local_directory_invalid")
    else:
        mode = stat.S_IMODE(details.st_mode)
        if not stat.S_ISREG(details.st_mode) or mode & 0o022:
            raise LiveLoopError("owner_local_file_invalid")
        if executable:
            if mode & 0o100 == 0:
                raise LiveLoopError("owner_local_executable_invalid")
        elif private and mode != 0o600:
            raise LiveLoopError("owner_local_file_invalid")
    return resolved


def _private_output(path: Path) -> Path:
    lexical = Path(os.path.abspath(str(path.expanduser())))
    _reject_symlink_ancestors(lexical, allow_missing_leaf=True)
    if not _inside_account_home(lexical.resolve(strict=False)):
        raise LiveLoopError("owner_local_path_invalid")
    _private_path(lexical.parent, directory=True)
    if lexical.exists() or lexical.is_symlink():
        _private_path(lexical)
    return lexical


def _environment() -> dict[str, str]:
    return {
        "PATH": FIXED_PATH,
        "HOME": str(ACCOUNT_HOME),
        "TMPDIR": str(LIVE_ROOT / "tmp"),
        "GBRAIN_SOURCE": "x-bookmarks",
    }


def _run(argv: list[str], *, timeout: int = 180, receipt_path: Path | None = None) -> dict[str, Any]:
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            env=_environment(),
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LiveLoopError("local_command_unavailable") from exc
    if result.returncode != 0:
        raise LiveLoopError("local_command_failed")
    try:
        if receipt_path is not None:
            value = json.loads(_private_path(receipt_path).read_text(encoding="utf-8"))
        else:
            value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise LiveLoopError("local_command_receipt_invalid") from exc
    if not isinstance(value, dict):
        raise LiveLoopError("local_command_receipt_invalid")
    return value


def _latest_maintenance_receipt() -> Path:
    receipts = ACCOUNT_HOME / ".local" / "state" / "stack" / "maintenance" / "receipts"
    _private_path(receipts, directory=True)
    candidates = [path for path in receipts.glob("*.json") if path.is_file() and not path.is_symlink()]
    if not candidates:
        raise LiveLoopError("maintenance_receipt_missing")
    return _private_path(max(candidates, key=lambda path: path.stat().st_mtime))


def _preflight() -> Path:
    config = WEEKLY.load_config()
    if WEEKLY.scheduler_contract_status(config) != "approved_and_persisted":
        raise LiveLoopError("scheduler_contract_not_persisted")
    receipt = _latest_maintenance_receipt()
    maintenance = WEEKLY.read_latest_maintenance_receipt(receipt, config=config)
    if maintenance.get("status") != "linked":
        raise LiveLoopError("maintenance_receipt_not_linked")
    return receipt


def run() -> dict[str, Any]:
    maintenance_receipt = _preflight()
    live_root = _private_path(LIVE_ROOT, directory=True)
    _private_path(FIELD_THEORY_DB)
    _private_path(GBRAIN_SOURCE_ROOT, directory=True, private=False)
    _private_path(GBRAIN_CLI, private=False, executable=True, allow_leaf_symlink=True)
    _private_path(live_root / "tmp", directory=True)
    _private_path(live_root / "gbrain-import", directory=True)
    _private_path(live_root / "coordinator", directory=True)
    ledger = _private_path(live_root / "bookmarks-ledger.sqlite3")
    adapter_config = _private_path(live_root / "local-adapter-config.json")
    snapshot = _private_output(live_root / "source-snapshot-current.json")
    previous = ["--zero-delta-against", str(snapshot)] if snapshot.exists() else []

    reconcile = _run([
        sys.executable,
        str(ROOT / "scripts" / "reconcile-bookmark-sources.py"),
        "--sources", str(ROOT / "config" / "bookmark-sources.json"),
        "--policy", str(ROOT / "config" / "bookmark-fetch-policy.json"),
        "--ledger", str(ledger),
        "--out", str(snapshot),
        "--apply",
        "--approval-contract", "u15-source-sync-approved-v1",
        *previous,
    ], receipt_path=snapshot)
    _private_path(snapshot)

    import_receipt_path = _private_output(live_root / "gbrain-import-weekly.json")
    imported = _run([
        sys.executable,
        str(ROOT / "scripts" / "import-bookmark-deltas.py"),
        "--snapshot", str(snapshot),
        "--markdown-dir", str(live_root / "gbrain-import"),
        "--ledger", str(ledger),
        "--existing-source-root", str(GBRAIN_SOURCE_ROOT),
        "--out", str(import_receipt_path),
        "--apply",
        "--approval-contract", "x-bookmarks-import-approved-v1",
    ], receipt_path=import_receipt_path)
    if imported.get("status") not in {"indexed", "no_action"}:
        raise LiveLoopError("gbrain_import_not_indexed")

    campaign = _run([
        sys.executable,
        str(ROOT / "scripts" / "run-stack-weekly-intelligence.py"),
        "--local-adapter-config", str(adapter_config),
        "--state-dir", str(live_root / "coordinator"),
        "--maintenance-receipt", str(maintenance_receipt),
    ], timeout=300)
    return {
        "schema_version": 1,
        "task_id": "stack-weekly-live",
        "source_observation_count": len(reconcile.get("observations", [])),
        "source_zero_delta_state": (reconcile.get("zero_delta") or {}).get("state"),
        "import_status": imported.get("status"),
        "import_accepted_count": imported.get("accepted_count"),
        "campaign_run_id": campaign.get("run_id"),
        "campaign_terminal_state": campaign.get("terminal_state"),
        "campaign_reason_code": campaign.get("reason_code"),
        "scheduler_status": (campaign.get("scheduler") or {}).get("status"),
    }


def main() -> int:
    try:
        print(json.dumps(run(), sort_keys=True, separators=(",", ":")))
        return 0
    except LiveLoopError as exc:
        print(json.dumps({"task_id": "stack-weekly-live", "status": "failed", "reason_code": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    except Exception:
        print(json.dumps({"task_id": "stack-weekly-live", "status": "failed", "reason_code": "unexpected_failure"}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
