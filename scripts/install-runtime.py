#!/usr/bin/env python3
"""Atomically switch compiled runtime stages and retain rollback evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OVERLAY_SPEC = importlib.util.spec_from_file_location("validate_private_overlay", Path(__file__).with_name("validate-private-overlay.py"))
assert OVERLAY_SPEC and OVERLAY_SPEC.loader
OVERLAY = importlib.util.module_from_spec(OVERLAY_SPEC)
OVERLAY_SPEC.loader.exec_module(OVERLAY)


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


def validate_stage(stage: Path, target: dict[str, Any], expected_catalog_digest: str | None) -> dict[str, Any]:
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
    return manifest


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


def prepare_receipts(_root: Path, receipts_dir: Path) -> None:
    receipts_dir = receipts_dir.resolve()
    receipts_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(receipts_dir, 0o700)
    details = receipts_dir.stat()
    if details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) != 0o700:
        raise InstallError("receipts directory must be owner-only (0700)")


def write_owner_file(path: Path, value: dict[str, Any]) -> None:
    path.write_text(canonical_json(value), encoding="utf-8")
    os.chmod(path, 0o600)


def run_verifier(target: dict[str, Any], destination: Path) -> dict[str, Any]:
    command = target.get("post_switch_verifier")
    if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
        raise InstallError(f"target {target['name']} requires a non-empty post_switch_verifier command list")
    if not destination.is_symlink() or not destination.resolve().is_dir():
        raise InstallError(f"installed destination is not a resolvable runtime pointer for {target['name']}")
    result = subprocess.run(command, cwd=destination, capture_output=True, text=True, timeout=30, check=False)
    if result.returncode:
        raise InstallError(f"post-switch verifier failed for {target['name']}")
    return {"target": target["name"], "status": "passed", "exit_code": result.returncode}


def atomic_link(destination: Path, target: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.new")
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    temporary.symlink_to(target)
    os.replace(temporary, destination)


def install_runtimes(root: Path, targets_path: Path, stages: dict[str, Path], receipts_dir: Path, *, fail_after: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    targets_path = targets_path.resolve()
    targets = targets_from(targets_path)
    expected_catalog_digest = declared_catalog_digest(targets_path)
    if not targets:
        return {"schema_version": 1, "status": "no-targets", "targets": []}
    if expected_catalog_digest is None:
        raise InstallError("non-empty runtime targets must pin catalog_digest")
    for target in targets:
        command = target.get("post_switch_verifier")
        if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
            raise InstallError(f"target {target['name']} requires a non-empty post_switch_verifier command list")
    prepare_receipts(root, receipts_dir)
    manifests: dict[str, dict[str, Any]] = {}
    for target in targets:
        stage = stages.get(target["name"])
        if stage is None:
            raise InstallError(f"missing staged target {target['name']}")
        manifests[target["name"]] = validate_stage(stage, target, expected_catalog_digest)
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
    receipt: dict[str, Any] = {"schema_version": 1, "registry_digest": next(iter(digests)), "source_commits": sorted({manifest.get("source_commit") for manifest in manifests.values()}), "prior_targets": {name: value is not None for name, value in prior.items()}, "targets": [target["name"] for target in targets]}
    rollback_state: dict[str, Any] = {"schema_version": 1, "prior_targets": prior}
    switched: list[str] = []
    try:
        for target in targets:
            name = target["name"]
            atomic_link(destinations[name], stages[name].resolve())
            switched.append(name)
            if fail_after == name:
                raise InstallError(f"simulated switch failure after {name}")
        verifier_results = [run_verifier(target, destinations[target["name"]]) for target in targets]
        receipt["verifier_results"] = verifier_results
        receipt["verified_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        receipt["status"] = "published"
        write_owner_file(receipts_dir / "rollback-state.json", rollback_state)
        write_owner_file(receipts_dir / "latest.json", receipt)
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
        write_owner_file(receipts_dir / "rollback-state.json", rollback_state)
        write_owner_file(receipts_dir / "latest.json", receipt)
        raise InstallError(str(error)) from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Deployment root for relative target destinations")
    parser.add_argument("--targets", type=Path)
    parser.add_argument("--stage", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--receipts-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    stages: dict[str, Path] = {}
    try:
        for value in args.stage:
            name, raw_path = value.split("=", 1)
            stages[name] = Path(raw_path)
        receipt = install_runtimes(args.root, args.targets or args.root / "config/runtime-targets.json", stages, args.receipts_dir)
        print(canonical_json(receipt).rstrip())
    except (InstallError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
