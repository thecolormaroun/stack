#!/usr/bin/env python3
"""Verify declared immutable upstreams before any caller extracts or stages them.

This command intentionally performs no clone, extraction, staging, or runtime swap.
Callers may proceed only after its zero exit status.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "registry" / "upstreams.json"
LOCK = ROOT / "upstreams.lock.json"


def load() -> tuple[dict, dict]:
    return json.loads(REGISTRY.read_text()), json.loads(LOCK.read_text())


def package_content_digest(directory: Path) -> str:
    if not directory.is_dir():
        raise ValueError("bundle is missing")
    files = sorted(path for path in directory.rglob("*") if path.is_file())
    if not files:
        raise ValueError("bundle is empty")
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def check_metadata(registry: dict, lock: dict) -> list[str]:
    errors: list[str] = []
    for provider in registry["providers"]:
        pin = provider["pin"]
        if pin["type"] not in {"git-commit", "sha256"}:
            errors.append(f"{provider['id']}: mutable pin type")
        if lock["providers"].get(provider["id"]) != pin["value"]:
            errors.append(f"{provider['id']}: lock does not match declared pin")
        if provider["last_known_good"]["pin"] != pin["value"]:
            errors.append(f"{provider['id']}: last-known-good pin does not match declared pin")
        if not provider["license"].strip():
            errors.append(f"{provider['id']}: missing license posture")
        if provider["install"] == "repository-bundle":
            if pin["type"] != "sha256":
                errors.append(f"{provider['id']}: repository bundle requires a sha256 pin")
            bundle_path = provider.get("bundle_path")
            if not bundle_path:
                errors.append(f"{provider['id']}: repository bundle path is missing")
                continue
            try:
                actual_digest = package_content_digest(ROOT / bundle_path)
            except ValueError as error:
                errors.append(f"{provider['id']}: {error}")
            else:
                if actual_digest != pin["value"]:
                    errors.append(f"{provider['id']}: package content digest mismatch")
            package_manifest = ROOT / "packages" / provider["id"] / "package.json"
            if not package_manifest.is_file():
                errors.append(f"{provider['id']}: package manifest is missing")
            else:
                manifest = json.loads(package_manifest.read_text())
                if manifest.get("content_sha256") != pin["value"]:
                    errors.append(f"{provider['id']}: package manifest digest does not match declared pin")
    return errors


def git(directory: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(directory), *args], text=True, capture_output=True, check=False)
    if result.returncode:
        raise ValueError(result.stderr.strip() or "git verification failed")
    return result.stdout.strip()


def check_checkout(provider: dict, checkout: Path) -> list[str]:
    if not checkout.is_dir():
        return [f"{provider['id']}: checkout is missing"]
    try:
        origin = git(checkout, "remote", "get-url", "origin")
        head = git(checkout, "rev-parse", "HEAD")
    except ValueError as error:
        return [f"{provider['id']}: {error}"]
    errors = []
    if origin != provider["canonical_source"]:
        errors.append(f"{provider['id']}: unexpected origin")
    if head != provider["pin"]["value"]:
        errors.append(f"{provider['id']}: checkout pin mismatch")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed upstream metadata and checkout verifier")
    parser.add_argument("--check-checkout", nargs=2, metavar=("PROVIDER", "DIRECTORY"), help="verify one already-acquired checkout; never stages it")
    args = parser.parse_args()
    registry, lock = load()
    errors = check_metadata(registry, lock)
    if args.check_checkout:
        provider_id, directory = args.check_checkout
        provider = next((item for item in registry["providers"] if item["id"] == provider_id), None)
        if provider is None:
            errors.append(f"{provider_id}: unknown provider")
        elif provider["install"] != "pinned-git-checkout":
            errors.append(f"{provider_id}: is not a checkout package")
        else:
            errors.extend(check_checkout(provider, Path(directory)))
    if errors:
        print("UPSTREAM HEALTH FAILED: active outputs must remain last-known-good", file=sys.stderr)
        print("\n".join(sorted(errors)), file=sys.stderr)
        return 1
    print("upstream metadata verified; extraction and staging may proceed in the caller")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
