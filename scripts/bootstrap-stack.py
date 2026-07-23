#!/usr/bin/env python3
"""Validate Stack bootstrap readiness; installation is always opt-in."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DOCTOR = load("stack_doctor", "stack-doctor.py")
COMPILER = load("compile_runtime", "compile-runtime.py")
INSTALLER = load("install_runtime", "install-runtime.py")


class BootstrapError(ValueError):
    pass


def checkout_external_packages(root: Path, deployment_root: Path) -> dict[str, str]:
    """Materialize only the pinned external checkouts in deployment-owned cache."""
    providers = COMPILER.read_json(root / "registry/upstreams.json").get("providers", [])
    cache = deployment_root.resolve() / ".stack-packages"
    cache.mkdir(parents=True, exist_ok=True)
    if cache.is_symlink():
        raise BootstrapError("deployment package cache must not be a symlink")
    installed: dict[str, str] = {}
    for provider in providers:
        if not isinstance(provider, dict) or provider.get("install") != "pinned-git-checkout":
            continue
        provider_id = provider.get("id"); source = provider.get("canonical_source")
        pin = provider.get("pin", {}).get("value") if isinstance(provider.get("pin"), dict) else None
        if not all(isinstance(value, str) and value for value in (provider_id, source, pin)):
            raise BootstrapError("external package metadata is invalid")
        destination = cache / provider_id
        if destination.is_symlink():
            raise BootstrapError(f"deployment package cache must not contain a symlink: {provider_id}")
        if destination.exists():
            if not destination.is_dir():
                raise BootstrapError(f"deployment package cache entry is not a checkout: {provider_id}")
        else:
            clone = subprocess.run(["git", "clone", "--no-checkout", source, str(destination)], text=True, capture_output=True, check=False)
            if clone.returncode:
                raise BootstrapError(f"unable to clone pinned package {provider_id}")
            checkout = subprocess.run(["git", "-C", str(destination), "checkout", "--detach", pin], text=True, capture_output=True, check=False)
            if checkout.returncode:
                raise BootstrapError(f"unable to verify pinned package {provider_id}")
        status = subprocess.run(["git", "-C", str(destination), "status", "--porcelain"], text=True, capture_output=True, check=False)
        current = subprocess.run(["git", "-C", str(destination), "rev-parse", "HEAD"], text=True, capture_output=True, check=False)
        origin = subprocess.run(["git", "-C", str(destination), "remote", "get-url", "origin"], text=True, capture_output=True, check=False)
        if (
            status.returncode
            or current.returncode
            or origin.returncode
            or status.stdout.strip()
            or current.stdout.strip() != pin
            or origin.stdout.strip() != source
        ):
            raise BootstrapError(f"deployment package cache is not the required origin and clean pin: {provider_id}")
        installed[provider_id] = pin
    return installed


def compile_readiness(root: Path, *, require_clean_source: bool = False) -> dict[str, object]:
    catalog_path, targets_path = root / "registry/capabilities.json", root / "config/runtime-targets.json"
    catalog = COMPILER.read_json(catalog_path)
    capabilities = catalog.get("capabilities")
    if not isinstance(capabilities, list):
        raise BootstrapError("capability catalog lacks capabilities")
    targets = COMPILER.targets_from(targets_path)
    expected = COMPILER.declared_catalog_digest(targets_path)
    digest = COMPILER.digest_file(catalog_path)
    if targets and expected != digest:
        raise BootstrapError("catalog digest does not match runtime targets")
    if targets and require_clean_source:
        COMPILER.compilation_identity(root, None)  # preserves dirty-source publication protection.
    for target in targets:
        included = [item for item in capabilities if isinstance(item, dict) and COMPILER.exclusion(item, target["runtime"]) is None]
        COMPILER.validate_included(root, included)
        verifier = target.get("post_switch_verifier")
        if not isinstance(verifier, list) or not verifier or not all(isinstance(item, str) and item for item in verifier):
            raise BootstrapError(f"target {target['name']} lacks a post-switch verifier")
        destination = Path(target["destination"])
        if destination.is_absolute() or ".." in destination.parts:
            raise BootstrapError(f"target {target['name']} has an unsafe destination")
    return {"targets": [target["name"] for target in targets], "catalog_digest": digest}


def bootstrap(
    root: Path = ROOT,
    *,
    install: bool = False,
    staging_root: Path | None = None,
    receipts_dir: Path | None = None,
    deployment_root: Path | None = None,
) -> dict[str, object]:
    report = DOCTOR.doctor(root)
    if report["status"] != "ok":
        raise BootstrapError("doctor checks failed: " + "; ".join(report["errors"]))
    readiness = compile_readiness(root, require_clean_source=install)
    result: dict[str, object] = {"schema_version": 1, "mode": "install" if install else "dry-run", "doctor": report["summary"], "compile_readiness": readiness, "install_readiness": "ready" if readiness["targets"] else "no-targets"}
    if not install:
        return result
    if staging_root is None or receipts_dir is None or deployment_root is None:
        raise BootstrapError("--install requires --staging-root, --receipts-dir, and --deployment-root")
    result["external_packages"] = checkout_external_packages(root, deployment_root)
    stages = COMPILER.compile_runtimes(root, root / "registry/capabilities.json", root / "config/runtime-targets.json", staging_root, package_cache=deployment_root.resolve() / ".stack-packages")
    result["install_receipt"] = INSTALLER.install_runtimes(
        deployment_root.resolve(),
        root / "config/runtime-targets.json",
        stages,
        receipts_dir,
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--install", action="store_true", help="Install pinned external packages and runtime stages into --deployment-root.")
    parser.add_argument("--staging-root", type=Path)
    parser.add_argument("--receipts-dir", type=Path)
    parser.add_argument(
        "--deployment-root",
        type=Path,
        help="Root under which relative runtime destinations are installed; required with --install.",
    )
    args = parser.parse_args(argv)
    try:
        print(json.dumps(bootstrap(
            args.root.resolve(),
            install=args.install,
            staging_root=args.staging_root,
            receipts_dir=args.receipts_dir,
            deployment_root=args.deployment_root,
        ), sort_keys=True))
    except (BootstrapError, COMPILER.RuntimeError, INSTALLER.InstallError, DOCTOR.DoctorError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
