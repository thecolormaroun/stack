#!/usr/bin/env python3
"""Run Stack's approved local weekly bookmark and design-intelligence loop.

The live lane reads Field Theory, imports missing x-bookmarks without
embeddings, and then runs the deterministic weekly collection coordinator. This
entrypoint itself never enables Direct X/OAuth, provider egress, skill
promotion, or runtime publication; the approved Codex automation owns the
separate evaluated promotion tail.
"""

from __future__ import annotations

import sys

# The executable script must enter in isolated mode so ignored files in the
# persistent checkout cannot shadow stdlib imports before validation runs.
# Unit tests import this module under a non-__main__ name and exercise the same
# gate separately.
if __name__ == "__main__" and (not sys.flags.isolated or not sys.dont_write_bytecode):
    print(
        '{"reason_code":"isolated_no_bytecode_python_required","status":"failed","task_id":"stack-weekly-live"}',
        file=sys.stderr,
    )
    raise SystemExit(1)

import json
import configparser
import hashlib
import os
import pwd
import stat
import subprocess
import importlib.util
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ACCOUNT_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
AUTOMATION_CHECKOUT = ACCOUNT_HOME / ".local" / "share" / "stack" / "weekly-intelligence-source"
CANONICAL_ORIGIN = "https://github.com/thecolormaroun/stack.git"
GIT = Path("/usr/bin/git")
LIVE_ROOT = ACCOUNT_HOME / ".local" / "state" / "stack" / "weekly-intelligence" / "live"
FIELD_THEORY_DB = ACCOUNT_HOME / ".ft-bookmarks" / "bookmarks.db"
GBRAIN_SOURCE_ROOT = ACCOUNT_HOME / ".gbrain" / "source-roots" / "x-bookmarks-native"
GBRAIN_CLI = ACCOUNT_HOME / ".bun" / "bin" / "gbrain"
FIXED_PATH = f"{ACCOUNT_HOME}/.bun/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

WEEKLY: Any = None


class LiveLoopError(RuntimeError):
    pass


def _load_weekly_contract() -> Any:
    spec = importlib.util.spec_from_file_location(
        "stack_weekly_live_contract",
        ROOT / "scripts" / "run-stack-weekly-intelligence.py",
    )
    if spec is None or spec.loader is None:
        raise LiveLoopError("weekly_contract_unavailable")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise LiveLoopError("weekly_contract_unavailable") from exc
    module.DEFAULT_AUTOMATION_ROOT = ACCOUNT_HOME / ".codex" / "automations"
    return module


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


def _git(argv: list[str], *, timeout: int = 120) -> str:
    environment = _environment()
    environment.update({
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_DIR": str(ROOT / ".git"),
        "GIT_WORK_TREE": str(ROOT),
        "GIT_COMMON_DIR": str(ROOT / ".git"),
        "GIT_TERMINAL_PROMPT": "0",
    })
    try:
        result = subprocess.run(
            [str(GIT), "-C", str(ROOT), *argv],
            capture_output=True,
            text=True,
            env=environment,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LiveLoopError("execution_checkout_unavailable") from exc
    if result.returncode != 0:
        raise LiveLoopError("execution_checkout_invalid")
    return result.stdout.strip()


def _validate_git_config(git_dir: Path) -> None:
    """Reject local Git features that can execute code before status/fetch."""
    config_path = _private_path(git_dir / "config", private=False)
    parser = configparser.RawConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, configparser.Error) as exc:
        raise LiveLoopError("execution_checkout_git_config_invalid") from exc

    allowed_sections = {"core", 'remote "origin"', 'branch "main"'}
    if set(parser.sections()) != allowed_sections:
        raise LiveLoopError("execution_checkout_git_config_invalid")
    core = dict(parser.items("core"))
    required_core = {
        "repositoryformatversion": "0",
        "bare": "false",
        "logallrefupdates": "true",
    }
    if any(core.get(key) != value for key, value in required_core.items()):
        raise LiveLoopError("execution_checkout_git_config_invalid")
    if set(core) - {
        "repositoryformatversion", "filemode", "bare", "logallrefupdates",
        "ignorecase", "precomposeunicode",
    }:
        raise LiveLoopError("execution_checkout_git_config_invalid")
    if core.get("filemode") not in {"true", "false"} or any(
        core.get(key) not in {None, "true", "false"}
        for key in ("ignorecase", "precomposeunicode")
    ):
        raise LiveLoopError("execution_checkout_git_config_invalid")

    remote = dict(parser.items('remote "origin"'))
    if set(remote) not in ({"url", "fetch"}, {"url", "fetch", "tagopt"}):
        raise LiveLoopError("execution_checkout_git_config_invalid")
    if (
        remote.get("url") != CANONICAL_ORIGIN
        or remote.get("fetch") != "+refs/heads/main:refs/remotes/origin/main"
        or remote.get("tagopt") not in {None, "--no-tags"}
    ):
        raise LiveLoopError("execution_checkout_git_config_invalid")
    if dict(parser.items('branch "main"')) != {
        "remote": "origin",
        "merge": "refs/heads/main",
    }:
        raise LiveLoopError("execution_checkout_git_config_invalid")


def _validate_git_hooks(git_dir: Path) -> None:
    """Allow only inert clone-template samples in the repository hook path."""
    hooks = _private_path(git_dir / "hooks", directory=True, private=False)
    try:
        entries = list(hooks.iterdir())
    except OSError as exc:
        raise LiveLoopError("execution_checkout_hooks_invalid") from exc
    for entry in entries:
        try:
            details = entry.lstat()
        except OSError as exc:
            raise LiveLoopError("execution_checkout_hooks_invalid") from exc
        if (
            not entry.name.endswith(".sample")
            or stat.S_ISLNK(details.st_mode)
            or not stat.S_ISREG(details.st_mode)
        ):
            raise LiveLoopError("execution_checkout_hooks_invalid")
        _private_path(entry, private=False)


def _validate_execution_checkout() -> str:
    """Prove the unattended lane is the clean, freshly fetched automation clone."""
    expected = _private_path(AUTOMATION_CHECKOUT, directory=True)
    if ROOT != expected:
        # This check intentionally precedes every subprocess so invoking the
        # live lane from the saved/dirty project cannot reach any mutation.
        raise LiveLoopError("execution_checkout_wrong_root")
    _private_path(expected / ".git", directory=True, private=False)
    if (expected / ".git" / "commondir").exists() or (expected / ".git" / "commondir").is_symlink():
        raise LiveLoopError("execution_checkout_common_dir_invalid")
    _validate_git_config(expected / ".git")
    _validate_git_hooks(expected / ".git")
    if Path(_git(["rev-parse", "--show-toplevel"])).resolve(strict=True) != expected:
        raise LiveLoopError("execution_checkout_invalid")
    if _git(["remote", "get-url", "origin"]) != CANONICAL_ORIGIN:
        raise LiveLoopError("execution_checkout_origin_mismatch")
    if _git(["status", "--porcelain=v1", "--untracked-files=all"]):
        raise LiveLoopError("execution_checkout_dirty")
    if _git(["ls-files", "--others", "--ignored", "--exclude-standard", "-z"]):
        raise LiveLoopError("execution_checkout_ignored_files")
    tracked = [entry for entry in _git(["ls-files", "-v", "-z"]).split("\0") if entry]
    if not tracked or any(not entry.startswith("H ") for entry in tracked):
        # `h` marks assume-unchanged and `S` marks skip-worktree. Requiring the
        # ordinary cached tag for every tracked path prevents either flag from
        # hiding working-tree changes from the status checks above and below.
        raise LiveLoopError("execution_checkout_index_flags")

    # Refresh the exact remote-tracking ref before any private-source or state
    # operation. The automation prompt checks out this commit first; this
    # second fetch closes the stale-ref window and fails closed if main moved.
    _git([
        "fetch",
        "--no-tags",
        "origin",
        "+refs/heads/main:refs/remotes/origin/main",
    ])
    if _git(["status", "--porcelain=v1", "--untracked-files=all"]):
        raise LiveLoopError("execution_checkout_dirty")
    if _git(["rev-parse", "--abbrev-ref", "HEAD"]) != "HEAD":
        raise LiveLoopError("execution_checkout_not_detached")
    head = _git(["rev-parse", "--verify", "HEAD^{commit}"])
    origin_main = _git(["rev-parse", "--verify", "refs/remotes/origin/main^{commit}"])
    if head != origin_main:
        raise LiveLoopError("execution_checkout_stale")
    return head


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


def _campaign_receipt(campaign: dict[str, Any], coordinator_root: Path) -> tuple[str, str]:
    run_id = campaign.get("run_id")
    if (
        not isinstance(run_id, str)
        or WEEKLY.ID_RE.fullmatch(run_id) is None
        or campaign.get("receipt_persisted") is not True
    ):
        raise LiveLoopError("campaign_receipt_identity_invalid")
    receipts = _private_path(coordinator_root / "receipts", directory=True)
    matches: list[tuple[Path, bytes]] = []
    for candidate in receipts.glob(f"{run_id}*.json"):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        path = _private_path(candidate)
        try:
            raw = path.read_bytes()
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LiveLoopError("campaign_receipt_invalid") from exc
        if value == campaign:
            matches.append((path, raw))
    if not matches:
        raise LiveLoopError("campaign_receipt_missing")
    if len(matches) != 1:
        raise LiveLoopError("campaign_receipt_ambiguous")
    path, raw = matches[0]
    try:
        relative = path.relative_to(LIVE_ROOT.parent.resolve())
    except ValueError as exc:
        raise LiveLoopError("campaign_receipt_path_invalid") from exc
    return relative.as_posix(), hashlib.sha256(raw).hexdigest()


def _persist_live_binding(value: dict[str, Any], live_root: Path) -> tuple[str, str]:
    receipts = _private_path(live_root / "live-receipts", directory=True)
    run_id = value.get("campaign_run_id")
    if not isinstance(run_id, str) or WEEKLY.ID_RE.fullmatch(run_id) is None:
        raise LiveLoopError("live_binding_identity_invalid")
    destination = _private_output(receipts / f"{run_id}.json")
    raw = (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if destination.exists():
        if destination.read_bytes() != raw:
            raise LiveLoopError("live_binding_conflict")
    else:
        staged: Path | None = None
        try:
            descriptor, name = tempfile.mkstemp(prefix=f".{run_id}.", suffix=".tmp", dir=receipts)
            staged = Path(name)
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(staged, destination)
            except FileExistsError:
                if destination.read_bytes() != raw:
                    raise LiveLoopError("live_binding_conflict")
        except OSError as error:
            raise LiveLoopError("live_binding_write_failed") from error
        finally:
            if staged is not None:
                try:
                    staged.unlink(missing_ok=True)
                except OSError:
                    pass
    _private_path(destination)
    try:
        relative = destination.relative_to(live_root.parent.resolve())
    except ValueError as error:
        raise LiveLoopError("live_binding_path_invalid") from error
    return relative.as_posix(), hashlib.sha256(raw).hexdigest()


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
    global WEEKLY
    _validate_execution_checkout()
    # No checkout-local module is loaded until the repository itself passes
    # provenance, cleanliness, ignored-file, index-flag, and commit checks.
    WEEKLY = _load_weekly_contract()
    maintenance_receipt = _preflight()
    live_root = _private_path(LIVE_ROOT, directory=True)
    _private_path(FIELD_THEORY_DB)
    _private_path(GBRAIN_SOURCE_ROOT, directory=True, private=False)
    _private_path(GBRAIN_CLI, private=False, executable=True, allow_leaf_symlink=True)
    _private_path(live_root / "tmp", directory=True)
    _private_path(live_root / "gbrain-import", directory=True)
    _private_path(live_root / "coordinator", directory=True)
    _private_path(live_root / "live-receipts", directory=True)
    ledger = _private_path(live_root / "bookmarks-ledger.sqlite3")
    adapter_config = _private_path(live_root / "local-adapter-config.json")
    snapshot = _private_output(live_root / "source-snapshot-current.json")
    previous = ["--zero-delta-against", str(snapshot)] if snapshot.exists() else []

    reconcile = _run([
        sys.executable,
        "-I",
        "-B",
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
        "-I",
        "-B",
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
        "-I",
        "-B",
        str(ROOT / "scripts" / "run-stack-weekly-intelligence.py"),
        "--local-adapter-config", str(adapter_config),
        "--state-dir", str(live_root / "coordinator"),
        "--maintenance-receipt", str(maintenance_receipt),
    ], timeout=300)
    campaign_receipt_path, campaign_receipt_digest = _campaign_receipt(
        campaign,
        live_root / "coordinator",
    )
    summary = {
        "schema_version": 1,
        "task_id": "stack-weekly-live",
        "source_observation_count": len(reconcile.get("observations", [])),
        "source_zero_delta_state": (reconcile.get("zero_delta") or {}).get("state"),
        "import_status": imported.get("status"),
        "import_accepted_count": imported.get("accepted_count"),
        "campaign_run_id": campaign.get("run_id"),
        "campaign_terminal_state": campaign.get("terminal_state"),
        "campaign_reason_code": campaign.get("reason_code"),
        "campaign_receipt_relative_path": campaign_receipt_path,
        "campaign_receipt_digest": campaign_receipt_digest,
        "scheduler_status": (campaign.get("scheduler") or {}).get("status"),
    }
    binding = {
        "schema_version": 1,
        "task_id": "stack-weekly-live-binding",
        "campaign_run_id": campaign.get("run_id"),
        "campaign_receipt_relative_path": campaign_receipt_path,
        "campaign_receipt_digest": campaign_receipt_digest,
        "campaign_terminal_state": campaign.get("terminal_state"),
        "campaign_reason_code": campaign.get("reason_code"),
        "receipt_persisted": True,
    }
    live_receipt_path, live_receipt_digest = _persist_live_binding(binding, live_root)
    summary["live_binding_receipt_relative_path"] = live_receipt_path
    summary["live_binding_receipt_digest"] = live_receipt_digest
    return summary


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
