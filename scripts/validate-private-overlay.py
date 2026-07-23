#!/usr/bin/env python3
"""Validate and compile a local-only Stack private overlay.

The input overlay and its output directory are owner-only local state.  This
script never writes public runtime artifacts; callers must separately scan any
artifact that is intended to leave the private boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import shutil
import tempfile
from urllib.parse import parse_qsl, urlsplit
from pathlib import Path
from typing import Any


class OverlayError(ValueError):
    """An actionable private-overlay contract violation."""


PRIVATE_MARKERS = ("PRIVATE_PAYLOAD_SENTINEL", "PRIVATE_TITLE_SENTINEL", "PRIVATE_URL_SENTINEL", "PRIVATE_EXCERPT_SENTINEL")
URL_PATTERN = re.compile(r"(?:https?|file)://", re.IGNORECASE)
LOCAL_PATH_PATTERN = re.compile(r"(?:^|[\s\"'])/(?:Users|home|private|var|tmp)/")
RUNTIME_HOME_PATH_PATTERN = re.compile(r"(?:^|[\s\"'])/(?:Users|home)/[^/\s\"']+")
OVERLAY_ID_PATTERN = re.compile(r"^private-overlay:[a-z0-9][a-z0-9-]*$")
POLICY_ID_PATTERN = re.compile(r"^private-policy:[a-z0-9][a-z0-9-]*$")
TARGET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
TARGET_IDENTITY_PATTERN = re.compile(r"^local-target:[a-z0-9][a-z0-9-]*$")
OWNER_IDENTITY_PATTERN = re.compile(r"^local-owner:[a-z0-9][a-z0-9-]*$")
SECRET_QUERY_KEYS = {"access_token", "api_key", "apikey", "auth", "key", "password", "secret", "sig", "signature", "token"}


def canonical_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OverlayError(f"{path}: cannot read JSON") from error
    if not isinstance(value, dict):
        raise OverlayError(f"{path}: overlay must be a JSON object")
    return value


def require_owner_only(path: Path, expected_mode: int) -> None:
    try:
        details = path.stat()
    except OSError as error:
        raise OverlayError(f"{path}: missing owner-only local state") from error
    mode = stat.S_IMODE(details.st_mode)
    if details.st_uid != os.getuid() or mode != expected_mode:
        raise OverlayError(f"{path}: must be owned by the current user with mode {expected_mode:04o}")


def reject_symlinks(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise OverlayError(f"{label}: symlinks are not allowed: {path}")
    if path.is_dir():
        for entry in path.rglob("*"):
            if entry.is_symlink():
                raise OverlayError(f"{label}: symlinks are not allowed: {entry}")


def revoke_output(output_directory: Path) -> None:
    """Remove a stale private output before reporting exclusion or validation failure."""
    if not (output_directory.exists() or output_directory.is_symlink()):
        return
    if output_directory.is_symlink() or output_directory.is_file():
        output_directory.unlink()
        return
    retired = output_directory.with_name(f".{output_directory.name}.revoked")
    if retired.exists() or retired.is_symlink():
        if retired.is_dir() and not retired.is_symlink():
            shutil.rmtree(retired)
        else:
            retired.unlink()
    os.replace(output_directory, retired)
    shutil.rmtree(retired)


def validate_overlay(overlay: dict[str, Any]) -> None:
    required = {"schema_version", "overlay_id", "public_link", "authorized_runtime_targets", "target_authorization", "owner_only", "retention", "payload"}
    unknown = set(overlay) - required
    missing = required - set(overlay)
    if unknown or missing or overlay.get("schema_version") != 1:
        raise OverlayError("overlay has unsupported fields, missing fields, or schema_version")
    if not isinstance(overlay["overlay_id"], str) or not OVERLAY_ID_PATTERN.fullmatch(overlay["overlay_id"]):
        raise OverlayError("overlay_id must be an opaque private-overlay identifier")
    link = overlay["public_link"]
    if not isinstance(link, dict) or set(link) != {"catalog_overlay_id", "policy_id"}:
        raise OverlayError("public_link must contain only catalog_overlay_id and policy_id")
    if link["catalog_overlay_id"] != overlay["overlay_id"] or not isinstance(link["policy_id"], str) or not POLICY_ID_PATTERN.fullmatch(link["policy_id"]):
        raise OverlayError("public_link must use matching opaque identifiers")
    targets = overlay["authorized_runtime_targets"]
    if not isinstance(targets, dict) or not targets or not all(
        isinstance(target, str) and TARGET_PATTERN.fullmatch(target)
        and isinstance(identity, str) and TARGET_IDENTITY_PATTERN.fullmatch(identity)
        for target, identity in targets.items()
    ):
        raise OverlayError("authorized_runtime_targets must bind named targets to local target identities")
    authorization = overlay["target_authorization"]
    if not isinstance(authorization, dict) or set(authorization) != {"manifest_path", "owner_identity"} or not isinstance(authorization["manifest_path"], str) or not authorization["manifest_path"] or not isinstance(authorization["owner_identity"], str) or not OWNER_IDENTITY_PATTERN.fullmatch(authorization["owner_identity"]):
        raise OverlayError("target_authorization must name an owner-local target manifest and owner identity")
    if overlay["owner_only"] != {"overlay_directory_mode": "0700", "file_mode": "0600"}:
        raise OverlayError("owner_only must require directory mode 0700 and file mode 0600")
    if overlay["retention"] != {"payload_retention": "owner-managed-local-only", "delete_on_authorization_removal": True, "delete_on_payload_removal": True, "delete_on_validation_failure": True}:
        raise OverlayError("retention must require local-only deletion on authorization, payload removal, or validation failure")
    payload = overlay["payload"]
    if not isinstance(payload, dict) or set(payload) != {"path"} or not isinstance(payload["path"], str) or not payload["path"]:
        raise OverlayError("payload must contain only a local path")


def validate_target_manifest(path: Path, authorization: dict[str, Any], target: str, expected_identity: str) -> None:
    """Verify the target against the owner-local manifest, never caller input alone."""
    reject_symlinks(path.parent, label="target authorization manifest")
    reject_symlinks(path, label="target authorization manifest")
    require_owner_only(path.parent, 0o700)
    require_owner_only(path, 0o600)
    manifest = read_json(path)
    if set(manifest) != {"schema_version", "owner_identity", "targets"} or manifest.get("schema_version") != 1:
        raise OverlayError("target authorization manifest has unsupported fields or schema_version")
    if manifest.get("owner_identity") != authorization["owner_identity"]:
        raise OverlayError("target authorization manifest owner identity does not match overlay")
    manifest_targets = manifest.get("targets")
    if not isinstance(manifest_targets, dict) or not all(
        isinstance(name, str) and TARGET_PATTERN.fullmatch(name)
        and isinstance(identity, str) and TARGET_IDENTITY_PATTERN.fullmatch(identity)
        for name, identity in manifest_targets.items()
    ):
        raise OverlayError("target authorization manifest has invalid target identities")
    if manifest_targets.get(target) != expected_identity:
        raise OverlayError("target is not authorized by the trusted local target manifest")


def scan_public_value(value: object, location: str = "public artifact") -> None:
    """Fail closed if public output contains path, URL, or private fixture data."""
    if isinstance(value, dict):
        for key, child in value.items():
            scan_public_value(key, location)
            scan_public_value(child, location)
    elif isinstance(value, list):
        for child in value:
            scan_public_value(child, location)
    elif isinstance(value, str):
        if any(marker in value for marker in PRIVATE_MARKERS) or URL_PATTERN.search(value) or LOCAL_PATH_PATTERN.search(value):
            raise OverlayError(f"{location}: private payload or identifying metadata is forbidden in public output")


def scan_public_artifact(path: Path) -> None:
    try:
        scan_public_value(json.loads(path.read_text(encoding="utf-8")), str(path))
    except json.JSONDecodeError:
        scan_public_value(path.read_text(encoding="utf-8"), str(path))


def scan_public_runtime_payload(path: Path) -> None:
    """Scan a public skill payload while permitting ordinary provenance links."""
    # Runtime payloads may contain reviewed binary assets. Decode permissively
    # so embedded ASCII sentinels, paths, and URLs are still scanned without
    # treating an image as malformed text.
    text = path.read_bytes().decode("utf-8", errors="ignore")
    if any(marker in text for marker in PRIVATE_MARKERS) or RUNTIME_HOME_PATH_PATTERN.search(text):
        raise OverlayError(f"{path}: private payload or identifying metadata is forbidden in public output")
    for file_url in re.findall(r"file://[^\s<>\"')]+", text, re.IGNORECASE):
        normalized_file_url = file_url.rstrip("`.,;").lower()
        if (
            normalized_file_url != "file://"
            and "$" not in normalized_file_url
            and not normalized_file_url.startswith(("file:///absolute/path/", "file:///path/to/"))
        ):
            raise OverlayError(f"{path}: local file URL is forbidden in public output")
    for raw_url in re.findall(r"https?://[^\s<>\"')]+", text, re.IGNORECASE):
        parsed = urlsplit(raw_url)
        if parsed.username or parsed.password:
            raise OverlayError(f"{path}: credentialed URL is forbidden in public output")
        if any(key.lower() in SECRET_QUERY_KEYS for key, _value in parse_qsl(parsed.query, keep_blank_values=True)):
            raise OverlayError(f"{path}: secret-bearing URL is forbidden in public output")


def compile_overlay(overlay_path: Path, target: str, output_directory: Path) -> dict[str, str]:
    """Emit a private manifest only for an authorized target; otherwise exclude it."""
    staging_directory: Path | None = None
    try:
        reject_symlinks(overlay_path.parent, label="private overlay input")
        require_owner_only(overlay_path.parent, 0o700)
        require_owner_only(overlay_path, 0o600)
        overlay = read_json(overlay_path)
        validate_overlay(overlay)
        if not isinstance(target, str) or not TARGET_PATTERN.fullmatch(target):
            raise OverlayError("target must be a named local runtime target")
        expected_identity = overlay["authorized_runtime_targets"].get(target)
        if expected_identity is None:
            revoke_output(output_directory)
            return {"status": "excluded", "reason": "target_not_authorized"}
        validate_target_manifest(Path(overlay["target_authorization"]["manifest_path"]), overlay["target_authorization"], target, expected_identity)

        payload_path = Path(overlay["payload"]["path"])
        reject_symlinks(payload_path.parent, label="private payload input")
        reject_symlinks(payload_path, label="private payload input")
        require_owner_only(payload_path.parent, 0o700)
        require_owner_only(payload_path, 0o600)
        reject_symlinks(output_directory.parent, label="private output parent")
        require_owner_only(output_directory.parent, 0o700)
        manifest = {"schema_version": 1, "overlay_id": overlay["overlay_id"], "target": target, "payload_path": str(payload_path)}
        digest = hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()
        receipt = {"schema_version": 1, "status": "compiled", "overlay_id": overlay["overlay_id"], "target": target, "private_manifest_digest": digest}
        staging_directory = Path(tempfile.mkdtemp(prefix=f".{output_directory.name}.staging-", dir=output_directory.parent))
        os.chmod(staging_directory, 0o700)
        manifest_path = staging_directory / "private-runtime-manifest.json"
        receipt_path = staging_directory / "private-runtime-receipt.json"
        manifest_path.write_text(canonical_json(manifest), encoding="utf-8")
        receipt_path.write_text(canonical_json(receipt), encoding="utf-8")
        os.chmod(manifest_path, 0o600)
        os.chmod(receipt_path, 0o600)
        revoke_output(output_directory)
        os.replace(staging_directory, output_directory)
        staging_directory = None
        return {"status": "compiled", "manifest": str(output_directory / manifest_path.name), "receipt": str(output_directory / receipt_path.name), "digest": digest}
    except OverlayError:
        if staging_directory is not None and staging_directory.exists():
            shutil.rmtree(staging_directory)
        revoke_output(output_directory)
        raise
    except OSError as error:
        if staging_directory is not None and staging_directory.exists():
            shutil.rmtree(staging_directory)
        revoke_output(output_directory)
        raise OverlayError("private overlay compilation failed") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scan-public-artifact", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    try:
        for artifact in args.scan_public_artifact:
            scan_public_artifact(artifact)
        result = compile_overlay(args.overlay, args.target, args.output)
        print(canonical_json({key: value for key, value in result.items() if key in {"status", "reason", "digest"}}), end="")
        return 0
    except OverlayError as error:
        print("error: private overlay validation failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
