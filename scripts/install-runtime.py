#!/usr/bin/env python3
"""Compile from verified Stack origin/main, atomically install, and retain rollback evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_ORIGIN_URL = "https://github.com/thecolormaroun/stack.git"
TRUSTED_RUNTIME_RECEIPTS_ROOT = Path(os.path.abspath(str(Path.home() / ".local/state/stack/runtime-receipts")))
VERIFIER_TIMEOUT_SECONDS = 30.0
OVERLAY_SPEC = importlib.util.spec_from_file_location("validate_private_overlay", Path(__file__).with_name("validate-private-overlay.py"))
assert OVERLAY_SPEC and OVERLAY_SPEC.loader
OVERLAY = importlib.util.module_from_spec(OVERLAY_SPEC)
OVERLAY_SPEC.loader.exec_module(OVERLAY)
COMPILER_SPEC = importlib.util.spec_from_file_location("compile_runtime_for_installer", Path(__file__).with_name("compile-runtime.py"))
assert COMPILER_SPEC and COMPILER_SPEC.loader
COMPILER = importlib.util.module_from_spec(COMPILER_SPEC)
COMPILER_SPEC.loader.exec_module(COMPILER)


class InstallError(ValueError):
    """A multi-target runtime publication could not be completed."""


def canonical_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InstallError(f"{path}: invalid JSON") from error
    if not isinstance(value, dict):
        raise InstallError(f"{path}: expected object")
    return value


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def staged_tree_digest(stage: Path) -> str:
    records: list[str] = []
    for path in sorted(stage.rglob("*")):
        if path.is_symlink():
            raise InstallError(f"staged tree contains a symlink: {path}")
        if path.is_file() and path.name not in {"runtime-manifest.json", "stage-attestation.json"}:
            records.append(f"{path.relative_to(stage).as_posix()}:{digest_file(path)}")
    return hashlib.sha256("\n".join(records).encode("utf-8")).hexdigest()


def scan_public_stage(stage: Path) -> None:
    for path in sorted(stage.rglob("*")):
        if path.is_symlink():
            raise InstallError(f"staged tree contains a symlink: {path}")
        if path.is_file():
            try:
                if path.name in {"runtime-manifest.json", "stage-attestation.json"}:
                    OVERLAY.scan_public_artifact(path)
                else:
                    OVERLAY.scan_public_runtime_payload(path)
            except OVERLAY.OverlayError as error:
                raise InstallError(f"staged public tree failed leak scan: {error}") from error


def validate_merged_source(source_repository: Path, expected_source_commit: str) -> Path:
    source = source_repository.expanduser().resolve()
    if (
        not isinstance(expected_source_commit, str)
        or re.fullmatch(r"[a-f0-9]{40}", expected_source_commit) is None
    ):
        raise InstallError("expected source commit must be a full 40-character Git commit")
    if source_repository.is_symlink() or not source.is_dir():
        raise InstallError("source repository must be a real directory")

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(source), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise InstallError("source repository lacks verified origin/main merge provenance")
        return result.stdout.strip()

    if git("remote", "get-url", "origin") != CANONICAL_ORIGIN_URL:
        raise InstallError("source repository origin is not the approved canonical Stack remote")
    fetch = subprocess.run(
        [
            "git", "-C", str(source), "fetch", "--quiet", "--no-tags", "--prune",
            "origin", "+refs/heads/main:refs/remotes/origin/main",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if fetch.returncode:
        raise InstallError("unable to refresh the approved canonical Stack origin/main")

    top_level = Path(git("rev-parse", "--show-toplevel")).resolve()
    head = git("rev-parse", "--verify", "HEAD^{commit}")
    origin_main = git("rev-parse", "--verify", "refs/remotes/origin/main^{commit}")
    dirty = git("status", "--porcelain=v1", "--untracked-files=all")
    if top_level != source or head != expected_source_commit or origin_main != expected_source_commit or dirty:
        raise InstallError("source repository must be clean at the exact verified origin/main merge commit")
    return source


def validate_stage(
    stage: Path,
    target: dict[str, Any],
    expected_catalog_digest: str | None,
    expected_source_commit: str | None = None,
    expected_source_tree_digest: str | None = None,
) -> dict[str, Any]:
    if stage.is_symlink() or not stage.is_dir():
        raise InstallError(f"stage for {target['name']} must be a real directory")
    scan_public_stage(stage)
    manifest = read_json(stage / "runtime-manifest.json")
    attestation = read_json(stage / "stage-attestation.json")
    if manifest.get("target") != target["name"] or manifest.get("runtime") not in {None, target["runtime"]}:
        raise InstallError(f"staged manifest does not match target {target['name']}")
    digest = manifest.get("registry_digest")
    if not isinstance(digest, str):
        raise InstallError(f"staged manifest has no registry digest for {target['name']}")
    if expected_catalog_digest is not None and digest != expected_catalog_digest:
        raise InstallError("staged manifest does not match configured catalog digest")
    required = {"schema_version", "catalog_digest", "runtime_manifest_digest", "staged_tree_digest", "source_commit", "source_tree_digest"}
    if set(attestation) != required or attestation.get("schema_version") != 1:
        raise InstallError(f"stage attestation is invalid for {target['name']}")
    if attestation["catalog_digest"] != digest or attestation["runtime_manifest_digest"] != digest_file(stage / "runtime-manifest.json") or attestation["staged_tree_digest"] != staged_tree_digest(stage) or attestation["source_commit"] != manifest.get("source_commit"):
        raise InstallError(f"stage attestation does not verify for {target['name']}")
    if expected_source_commit is not None and attestation["source_commit"] != expected_source_commit:
        raise InstallError(f"staged source commit does not match the expected merge commit for {target['name']}")
    if expected_source_tree_digest is not None and attestation["source_tree_digest"] != expected_source_tree_digest:
        raise InstallError(f"staged source tree does not match the verified source repository for {target['name']}")
    return manifest


def seal_stage(stage: Path) -> None:
    if stage.is_symlink() or not stage.is_dir():
        raise InstallError("compiled runtime stage must be a real directory")
    for path in sorted(stage.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_symlink():
            raise InstallError("compiled runtime stage contains a symlink")
        mode = stat.S_IMODE(path.stat().st_mode)
        if path.is_dir():
            path.chmod(0o500)
        elif path.is_file():
            path.chmod(0o500 if mode & 0o111 else 0o400)
    stage.chmod(0o500)


def validate_sealed_stage(stage: Path) -> None:
    for path in [stage, *stage.rglob("*")]:
        info = path.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o222:
            raise InstallError("compiled runtime stage is not owner-sealed")


def targets_from(path: Path) -> list[dict[str, Any]]:
    value = read_json(path)
    targets = value.get("targets")
    if value.get("schema_version") != 1 or not isinstance(targets, list):
        raise InstallError(f"{path}: expected schema_version 1 with targets list")
    names: set[str] = set()
    for target in targets:
        if not isinstance(target, dict) or not all(isinstance(target.get(key), str) and target[key] for key in ("name", "runtime", "destination")):
            raise InstallError(f"{path}: every target requires name, runtime, and destination")
        if target["name"] in names:
            raise InstallError(f"{path}: duplicate target {target['name']}")
        names.add(target["name"])
    return sorted(targets, key=lambda target: target["name"])


def declared_catalog_digest(path: Path) -> str | None:
    digest = read_json(path).get("catalog_digest")
    if digest is not None and (not isinstance(digest, str) or len(digest) != 64):
        raise InstallError(f"{path}: catalog_digest must be a SHA-256 hex digest")
    return digest


def trusted_receipts_path(receipts_dir: Path) -> Path:
    lexical = Path(os.path.abspath(str(receipts_dir.expanduser())))
    if lexical != TRUSTED_RUNTIME_RECEIPTS_ROOT:
        raise InstallError("runtime receipts must use the configured trusted receipt root")
    current = Path(lexical.anchor)
    for component in lexical.parts[1:]:
        current = current / component
        try:
            details = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise InstallError("trusted runtime receipt path is unavailable") from error
        if stat.S_ISLNK(details.st_mode):
            raise InstallError("trusted runtime receipt path must not contain symlinks")
    return lexical


def prepare_receipts(_root: Path, receipts_dir: Path) -> None:
    receipts_dir = trusted_receipts_path(receipts_dir)
    receipts_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(receipts_dir, 0o700)
    details = receipts_dir.stat()
    if details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) != 0o700:
        raise InstallError("receipts directory must be owner-only (0700)")


def write_owner_file(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink():
        raise InstallError("runtime receipt pointer may not be a symlink")
    path.write_text(canonical_json(value), encoding="utf-8")
    os.chmod(path, 0o600)


def write_immutable_owner_file(path: Path, value: dict[str, Any]) -> None:
    data = canonical_json(value).encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as error:
        raise InstallError("immutable runtime receipt already exists") from error
    except OSError as error:
        raise InstallError("unable to write immutable runtime receipt") from error


def transaction_directory(receipts_dir: Path, transaction_id: str) -> Path:
    transactions = receipts_dir / "transactions"
    if transactions.is_symlink():
        raise InstallError("runtime receipt transactions path may not be a symlink")
    transactions.mkdir(mode=0o700, exist_ok=True)
    details = transactions.lstat()
    if not stat.S_ISDIR(details.st_mode) or details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) != 0o700:
        raise InstallError("runtime receipt transactions directory must be owner-only")
    directory = transactions / transaction_id
    try:
        directory.mkdir(mode=0o700)
    except OSError as error:
        raise InstallError("unable to create immutable runtime receipt transaction") from error
    return directory


def persist_transaction_receipts(
    receipts_dir: Path,
    receipt: dict[str, Any],
    rollback_state: dict[str, Any],
) -> None:
    transaction_id = receipt["transaction_id"]
    directory = transaction_directory(receipts_dir, transaction_id)
    # Compatibility aliases are mutable status pointers only. Promotion proof
    # must use the immutable pair above.
    write_owner_file(receipts_dir / "rollback-state.json", rollback_state)
    write_owner_file(receipts_dir / "latest.json", receipt)
    write_immutable_owner_file(directory / "rollback.json", rollback_state)
    write_immutable_owner_file(directory / "install.json", receipt)


def terminate_process_group(process_group: int) -> None:
    try:
        os.killpg(process_group, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.monotonic() + 0.25
    while time.monotonic() < deadline:
        try:
            os.killpg(process_group, 0)
        except (ProcessLookupError, PermissionError):
            return
        time.sleep(0.01)
    try:
        os.killpg(process_group, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_verifier(target: dict[str, Any], stage: Path) -> dict[str, Any]:
    command = target.get("post_switch_verifier")
    if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
        raise InstallError(f"target {target['name']} requires a non-empty post_switch_verifier command list")
    with tempfile.TemporaryDirectory(prefix=f"stack-runtime-verifier-{target['name']}-") as temporary:
        verification_stage = Path(temporary) / "runtime"
        shutil.copytree(stage, verification_stage)
        process = subprocess.Popen(
            command,
            cwd=verification_stage,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        process_group = os.getpgid(process.pid)
        try:
            return_code = process.wait(timeout=VERIFIER_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as error:
            terminate_process_group(process_group)
            if process.poll() is None:
                process.kill()
            process.wait()
            raise InstallError(f"post-switch verifier timed out for {target['name']}") from error
        finally:
            terminate_process_group(process_group)
        if return_code:
            raise InstallError(f"post-switch verifier failed for {target['name']}")
    return {"target": target["name"], "status": "passed", "exit_code": return_code}


def atomic_link(destination: Path, target: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.new")
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    temporary.symlink_to(target)
    os.replace(temporary, destination)


def _switch_compiled_runtimes(
    root: Path,
    targets_path: Path,
    stages: dict[str, Path],
    receipts_dir: Path,
    *,
    source_repository: Path,
    expected_source_commit: str,
    fail_after: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    source_repository = validate_merged_source(source_repository, expected_source_commit)
    targets_path = targets_path.resolve()
    canonical_targets = source_repository / "config/runtime-targets.json"
    canonical_catalog = source_repository / "registry/capabilities.json"
    if targets_path != canonical_targets.resolve() or canonical_targets.is_symlink():
        raise InstallError("runtime targets must come from the verified source repository")
    targets = targets_from(targets_path)
    expected_catalog_digest = declared_catalog_digest(targets_path)
    if not targets:
        return {"schema_version": 1, "status": "no-targets", "targets": []}
    if canonical_catalog.is_symlink() or not canonical_catalog.is_file():
        raise InstallError("verified source repository lacks the canonical capability catalog")
    if expected_catalog_digest is None:
        raise InstallError("non-empty runtime targets must pin catalog_digest")
    if expected_catalog_digest != digest_file(canonical_catalog):
        raise InstallError("runtime targets do not pin the verified source catalog")
    expected_source_tree_digest = COMPILER.source_tree_digest(source_repository)
    for target in targets:
        command = target.get("post_switch_verifier")
        if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
            raise InstallError(f"target {target['name']} requires a non-empty post_switch_verifier command list")
    prepare_receipts(root, receipts_dir)
    manifests: dict[str, dict[str, Any]] = {}
    stage_artifact_digests: dict[str, tuple[str, str]] = {}
    for target in targets:
        stage = stages.get(target["name"])
        if stage is None:
            raise InstallError(f"missing staged target {target['name']}")
        seal_stage(stage)
        validate_sealed_stage(stage)
        manifests[target["name"]] = validate_stage(
            stage,
            target,
            expected_catalog_digest,
            expected_source_commit,
            expected_source_tree_digest,
        )
        stage_artifact_digests[target["name"]] = (
            digest_file(stage / "runtime-manifest.json"),
            digest_file(stage / "stage-attestation.json"),
        )
    digests = {manifest.get("registry_digest") for manifest in manifests.values()}
    if len(digests) != 1 or not isinstance(next(iter(digests)), str):
        raise InstallError("staged manifests must share one registry digest")
    prior: dict[str, str | None] = {}
    destinations: dict[str, Path] = {}
    for target in targets:
        raw_destination = Path(target["destination"])
        if raw_destination.is_absolute() or ".." in raw_destination.parts:
            raise InstallError(f"target {target['name']} destination must be relative to the deployment root; absolute paths are not allowed")
        destination = root / raw_destination
        destinations[target["name"]] = destination
        prior[target["name"]] = str(destination.resolve()) if destination.is_symlink() else None
    transaction_id = f"install-{uuid.uuid4().hex}"
    receipt: dict[str, Any] = {"schema_version": 1, "transaction_id": transaction_id, "registry_digest": next(iter(digests)), "source_commits": sorted({manifest.get("source_commit") for manifest in manifests.values()}), "prior_targets": {name: value is not None for name, value in prior.items()}, "targets": [target["name"] for target in targets]}
    rollback_state: dict[str, Any] = {"schema_version": 1, "transaction_id": transaction_id, "prior_targets": prior}
    switched: list[str] = []
    try:
        verifier_results = [run_verifier(target, stages[target["name"]]) for target in targets]
        resolved_stages = [stages[target["name"]].resolve() for target in targets]
        common_stage_root = (
            resolved_stages[0].parent
            if len(resolved_stages) == 1
            else Path(os.path.commonpath([str(path) for path in resolved_stages]))
        )
        if common_stage_root in {Path("/"), Path.home().resolve()}:
            raise InstallError("compiled stages do not share an owner-private transaction root")
        publication_root = common_stage_root / f"published-{uuid.uuid4().hex}"
        publication_root.mkdir(mode=0o700)
        published_stages: dict[str, Path] = {}
        for target in targets:
            name = target["name"]
            validate_sealed_stage(stages[name])
            validate_stage(
                stages[name],
                target,
                expected_catalog_digest,
                expected_source_commit,
                expected_source_tree_digest,
            )
            published = publication_root / name
            shutil.copytree(stages[name], published)
            seal_stage(published)
            validate_sealed_stage(published)
            validate_stage(
                published,
                target,
                expected_catalog_digest,
                expected_source_commit,
                expected_source_tree_digest,
            )
            published_stages[name] = published
        for target in targets:
            name = target["name"]
            validate_sealed_stage(published_stages[name])
            validate_stage(
                published_stages[name],
                target,
                expected_catalog_digest,
                expected_source_commit,
                expected_source_tree_digest,
            )
            if stage_artifact_digests[name] != (
                digest_file(published_stages[name] / "runtime-manifest.json"),
                digest_file(published_stages[name] / "stage-attestation.json"),
            ):
                raise InstallError(f"compiled runtime stage changed before switch for {name}")
            atomic_link(destinations[name], published_stages[name].resolve())
            switched.append(name)
            installed = destinations[name].resolve()
            validate_sealed_stage(installed)
            validate_stage(
                installed,
                target,
                expected_catalog_digest,
                expected_source_commit,
                expected_source_tree_digest,
            )
            if fail_after == name:
                raise InstallError(f"simulated switch failure after {name}")
        for target in targets:
            name = target["name"]
            installed = destinations[name].resolve()
            validate_sealed_stage(installed)
            validate_stage(
                installed,
                target,
                expected_catalog_digest,
                expected_source_commit,
                expected_source_tree_digest,
            )
            if stage_artifact_digests[name] != (
                digest_file(installed / "runtime-manifest.json"),
                digest_file(installed / "stage-attestation.json"),
            ):
                raise InstallError(f"installed runtime stage changed during verification for {name}")
        receipt["verifier_results"] = verifier_results
        receipt["verified_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        receipt["status"] = "published"
        persist_transaction_receipts(receipts_dir, receipt, rollback_state)
        return receipt
    except (OSError, InstallError) as error:
        for name in reversed(switched):
            previous = prior[name]
            if previous is None:
                if destinations[name].exists() or destinations[name].is_symlink():
                    destinations[name].unlink()
            else:
                atomic_link(destinations[name], Path(previous))
        receipt["status"] = "failed"
        receipt["error"] = str(error)
        receipt["restored_targets"] = switched
        failed_transaction_id = f"install-{uuid.uuid4().hex}"
        receipt["transaction_id"] = failed_transaction_id
        rollback_state["transaction_id"] = failed_transaction_id
        persist_transaction_receipts(receipts_dir, receipt, rollback_state)
        raise InstallError(str(error)) from error


def compile_and_install_runtimes(
    source_repository: Path,
    deployment_root: Path,
    staging_root: Path,
    receipts_dir: Path,
    package_cache: Path,
    *,
    expected_source_commit: str,
) -> dict[str, Any]:
    source = validate_merged_source(source_repository, expected_source_commit)
    protected_staging = staging_root.expanduser().resolve()
    if staging_root.is_symlink():
        raise InstallError("runtime staging root must be a real directory")
    protected_staging.mkdir(parents=True, mode=0o700, exist_ok=True)
    staging_info = protected_staging.stat()
    if not stat.S_ISDIR(staging_info.st_mode) or staging_info.st_uid != os.getuid():
        raise InstallError("runtime staging root must be an owner directory")
    protected_staging.chmod(0o700)
    transactions = protected_staging / "transactions"
    transactions.mkdir(mode=0o700, exist_ok=True)
    if transactions.is_symlink() or transactions.stat().st_uid != os.getuid():
        raise InstallError("runtime staging transactions must be owner-local")
    transactions.chmod(0o700)
    transaction_staging = transactions / f"compile-{uuid.uuid4().hex}"
    transaction_staging.mkdir(mode=0o700)

    with tempfile.TemporaryDirectory(prefix="stack-runtime-source-") as temporary:
        temporary_root = Path(temporary)
        temporary_root.chmod(0o700)
        snapshot = temporary_root / "source"
        clone = subprocess.run(
            ["git", "clone", "--quiet", "--no-checkout", "--no-local", str(source), str(snapshot)],
            capture_output=True,
            text=True,
            check=False,
        )
        if clone.returncode:
            raise InstallError("unable to create immutable source snapshot")
        checkout = subprocess.run(
            ["git", "-C", str(snapshot), "checkout", "--quiet", "--detach", expected_source_commit],
            capture_output=True,
            text=True,
            check=False,
        )
        if checkout.returncode:
            raise InstallError("unable to check out the verified source snapshot")
        snapshot_head = subprocess.run(
            ["git", "-C", str(snapshot), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        snapshot_status = subprocess.run(
            ["git", "-C", str(snapshot), "status", "--porcelain=v1", "--untracked-files=all"],
            capture_output=True,
            text=True,
            check=False,
        )
        if (
            snapshot_head.returncode
            or snapshot_status.returncode
            or snapshot_head.stdout.strip() != expected_source_commit
            or snapshot_status.stdout.strip()
        ):
            raise InstallError("immutable source snapshot does not match the verified commit")
        stages = COMPILER.compile_runtimes(
            snapshot,
            snapshot / "registry/capabilities.json",
            snapshot / "config/runtime-targets.json",
            transaction_staging,
            source_commit=expected_source_commit,
            package_cache=package_cache,
        )
    return _switch_compiled_runtimes(
        deployment_root,
        source / "config/runtime-targets.json",
        stages,
        receipts_dir,
        source_repository=source,
        expected_source_commit=expected_source_commit,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Deployment root for relative target destinations")
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--receipts-dir", type=Path, required=True)
    parser.add_argument("--source-repository", type=Path, required=True, help="clean Stack checkout whose HEAD equals origin/main")
    parser.add_argument("--expected-source-commit", required=True, help="full merged commit required for every staged runtime")
    args = parser.parse_args(argv)
    try:
        receipt = compile_and_install_runtimes(
            args.source_repository,
            args.root,
            args.staging_root,
            args.receipts_dir,
            args.root.resolve() / ".stack-packages",
            expected_source_commit=args.expected_source_commit,
        )
        print(canonical_json(receipt).rstrip())
    except (InstallError, COMPILER.RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
