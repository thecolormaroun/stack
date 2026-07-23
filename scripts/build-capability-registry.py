#!/usr/bin/env python3
"""Build Stack's generated capability catalog from capability-local manifests.

The public catalog intentionally contains no timestamps, machine paths, or runtime
compiler metadata so a rebuild is byte-for-byte reproducible.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
LIFECYCLES = {"candidate", "active", "deprecated", "archived", "external"}
ARTIFACT_TYPES = {"skill", "reference-pack", "router", "upstream-package", "private-overlay"}
AUDIT_STATUSES = {"pending", "reviewed"}
FAMILIES = {"core", "product", "planning", "design", "engineering", "orchestration", "review", "qa", "delivery", "knowledge", "platform"}
ROLES = {"router", "workflow", "leaf", "adapter", "reference-pack", "package", "alias"}
VISIBILITIES = {"primary", "extended", "internal", "compatibility", "reference-only", "external"}
TRUST_CLASSES = {"read-only", "local-mutation", "external-mutation"}
VALIDATION_CLASSES = {"structural", "representative-route", "high-risk"}
MANIFEST_KEYS = {"schema_version", "canonical_name", "purpose", "domain", "family", "role", "visibility", "commands", "ownership", "context", "trust_class", "validation_class", "artifact_type", "lifecycle", "audit_status", "source", "provenance", "overlaps", "compatibility_aliases", "alias_of", "validation", "runtimes", "disposition"}
OBJECT_KEYS = {
    "source": {"skill_path", "overlay_id"},
    "provenance": {"posture", "source_identity", "license"},
    "validation": {"status", "evidence"},
    "runtimes": {"supported", "publish_targets"},
    "disposition": {"status", "evidence_gap", "next_review_trigger"},
    "ownership": {"provider", "package", "source_path"},
    "context": {"inputs", "outputs"},
}
ROOT = Path(__file__).resolve().parents[1]


class RegistryError(ValueError):
    """An actionable capability registry contract violation."""


def canonical_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RegistryError(f"{path}: invalid JSON: {error.msg}") from error
    if not isinstance(value, dict):
        raise RegistryError(f"{path}: manifest must be a JSON object")
    return value


def require_string(value: dict[str, Any], field: str, path: Path) -> str:
    candidate = value.get(field)
    if not isinstance(candidate, str) or not candidate.strip():
        raise RegistryError(f"{path}: {field} must be a non-empty string")
    return candidate


def require_object(value: dict[str, Any], field: str, path: Path) -> dict[str, Any]:
    candidate = value.get(field)
    if not isinstance(candidate, dict):
        raise RegistryError(f"{path}: {field} must be an object")
    return candidate


def require_string_list(value: dict[str, Any], field: str, path: Path) -> list[str]:
    candidate = value.get(field)
    if not isinstance(candidate, list) or not all(isinstance(item, str) and item for item in candidate):
        raise RegistryError(f"{path}: {field} must be a list of non-empty strings")
    return candidate


def require_closed_keys(value: dict[str, Any], allowed: set[str], location: str, path: Path) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise RegistryError(f"{path}: {location} has unsupported field(s): {', '.join(unknown)}")


def reject_symlinks(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise RegistryError(f"{label}: symlinks are not allowed: {path}")
    if path.is_dir():
        for entry in path.rglob("*"):
            if entry.is_symlink():
                raise RegistryError(f"{label}: symlinks are not allowed: {entry}")


def validate_manifest(manifest: dict[str, Any], path: Path, root: Path) -> None:
    require_closed_keys(manifest, MANIFEST_KEYS, "manifest", path)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise RegistryError(f"{path}: schema_version must be {SCHEMA_VERSION}")

    name = require_string(manifest, "canonical_name", path)
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise RegistryError(f"{path}: canonical_name must be lowercase kebab-case")
    require_string(manifest, "purpose", path)

    domain = require_string(manifest, "domain", path)
    family = require_string(manifest, "family", path)
    if domain not in FAMILIES or family not in FAMILIES or domain != family:
        raise RegistryError(f"{path}: domain and family must be the same approved family")
    if require_string(manifest, "role", path) not in ROLES:
        raise RegistryError(f"{path}: role is invalid")
    if require_string(manifest, "visibility", path) not in VISIBILITIES:
        raise RegistryError(f"{path}: visibility is invalid")
    require_string_list(manifest, "commands", path)
    ownership = require_object(manifest, "ownership", path)
    require_closed_keys(ownership, OBJECT_KEYS["ownership"], "ownership", path)
    for field in OBJECT_KEYS["ownership"]:
        require_string(ownership, field, path)
    context = require_object(manifest, "context", path)
    require_closed_keys(context, OBJECT_KEYS["context"], "context", path)
    require_string_list(context, "inputs", path)
    require_string_list(context, "outputs", path)
    if require_string(manifest, "trust_class", path) not in TRUST_CLASSES:
        raise RegistryError(f"{path}: trust_class is invalid")
    if require_string(manifest, "validation_class", path) not in VALIDATION_CLASSES:
        raise RegistryError(f"{path}: validation_class is invalid")
    artifact_type = require_string(manifest, "artifact_type", path)
    if artifact_type not in ARTIFACT_TYPES:
        raise RegistryError(f"{path}: artifact_type must be one of {sorted(ARTIFACT_TYPES)}")
    lifecycle = require_string(manifest, "lifecycle", path)
    if lifecycle not in LIFECYCLES:
        raise RegistryError(f"{path}: lifecycle must be one of {sorted(LIFECYCLES)}")
    audit_status = require_string(manifest, "audit_status", path)
    if audit_status not in AUDIT_STATUSES:
        raise RegistryError(f"{path}: audit_status must be one of {sorted(AUDIT_STATUSES)}")

    source = require_object(manifest, "source", path)
    require_closed_keys(source, OBJECT_KEYS["source"], "source", path)
    if artifact_type == "private-overlay":
        if set(source) != {"overlay_id"}:
            raise RegistryError(f"{path}: private-overlay source must contain only overlay_id")
        overlay_id = require_string(source, "overlay_id", path)
        if not re.fullmatch(r"private-overlay:[a-z0-9][a-z0-9-]*", overlay_id):
            raise RegistryError(f"{path}: source.overlay_id must be an opaque private-overlay identifier")
    else:
        if set(source) != {"skill_path"}:
            raise RegistryError(f"{path}: non-private source must contain only skill_path")
        source_path = require_string(source, "skill_path", path)
        if source_path.startswith("/") or ".." in Path(source_path).parts:
            raise RegistryError(f"{path}: source.skill_path must be a repository-relative path")
        expected_source = path.parent.relative_to(root).as_posix() + "/SKILL.md"
        if source_path != expected_source:
            raise RegistryError(f"{path}: source.skill_path must equal {expected_source}")

    provenance = require_object(manifest, "provenance", path)
    require_closed_keys(provenance, OBJECT_KEYS["provenance"], "provenance", path)
    posture = require_string(provenance, "posture", path)
    if posture not in {"repository-local", "imported-upstream", "private-overlay"}:
        raise RegistryError(f"{path}: provenance.posture is invalid")
    require_string(provenance, "source_identity", path)
    require_string(provenance, "license", path)

    require_string_list(manifest, "overlaps", path)
    aliases = manifest.get("compatibility_aliases", [])
    if not isinstance(aliases, list) or len(aliases) != len(set(aliases)) or len(aliases) > 10 or not all(
        isinstance(alias, str) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", alias)
        for alias in aliases
    ):
        raise RegistryError(f"{path}: compatibility_aliases must be at most 10 unique kebab-case names")
    if aliases and lifecycle not in {"active", "candidate"}:
        raise RegistryError(f"{path}: only active or blocked candidate entries may declare compatibility_aliases")
    if name in aliases:
        raise RegistryError(f"{path}: compatibility alias cannot equal canonical_name")
    alias_of = manifest.get("alias_of")
    if alias_of is not None and (not isinstance(alias_of, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", alias_of)):
        raise RegistryError(f"{path}: alias_of must be a kebab-case canonical name")
    if lifecycle == "deprecated" and (manifest["role"] != "alias" or not alias_of):
        raise RegistryError(f"{path}: deprecated entries must be aliases with alias_of")
    validation = require_object(manifest, "validation", path)
    require_closed_keys(validation, OBJECT_KEYS["validation"], "validation", path)
    if validation.get("status") not in {"pending", "validated", "blocked"}:
        raise RegistryError(f"{path}: validation.status is invalid")
    require_string_list(validation, "evidence", path)
    runtimes = require_object(manifest, "runtimes", path)
    require_closed_keys(runtimes, OBJECT_KEYS["runtimes"], "runtimes", path)
    require_string_list(runtimes, "supported", path)
    require_string_list(runtimes, "publish_targets", path)
    disposition = require_object(manifest, "disposition", path)
    require_closed_keys(disposition, OBJECT_KEYS["disposition"], "disposition", path)
    if disposition.get("status") not in {"keep", "merge", "demote", "move", "archive", "hold-pending-evidence"}:
        raise RegistryError(f"{path}: disposition.status is invalid")

    if lifecycle == "active":
        for required in ("purpose", "artifact_type"):
            require_string(manifest, required, path)
        for required in ("posture", "source_identity", "license"):
            require_string(provenance, required, path)
        if not runtimes["publish_targets"]:
            raise RegistryError(f"{path}: active entries require runtimes.publish_targets")
        if audit_status != "reviewed" or validation["status"] != "validated":
            raise RegistryError(f"{path}: active entries require reviewed audit status and validated evidence")

    if lifecycle == "candidate" and disposition["status"] != "hold-pending-evidence":
        raise RegistryError(f"{path}: candidate entries must hold pending evidence")


def manifest_paths(root: Path) -> list[Path]:
    return sorted((root / "skills").glob("**/capability.json"))


def callable_skill_paths(root: Path) -> list[Path]:
    return sorted((root / "skills").glob("**/SKILL.md"))


def declared_command_ids(root: Path) -> set[str]:
    path = root / "registry" / "commands.json"
    if not path.exists():
        # Unit fixtures exercise manifest validation without a whole repository.
        return {"stack", "stack.explore", "stack.plan", "stack.design", "stack.build", "stack.orchestrate", "stack.review", "stack.qa", "stack.ship", "stack.learn", "stack.maintain", "stack.run"}
    value = read_json(path)
    commands = value.get("commands")
    if not isinstance(commands, list):
        raise RegistryError(f"{path}: commands must be a list")
    ids = {item.get("id") for item in commands if isinstance(item, dict) and isinstance(item.get("id"), str)}
    if len(ids) != len(commands):
        raise RegistryError(f"{path}: commands must have unique string ids")
    return ids


def declared_package_ids(root: Path) -> set[str]:
    packages: set[str] = {"stack"}
    if not (root / "packages").exists():
        return packages
    for path in sorted((root / "packages").glob("*/package.json")):
        value = read_json(path)
        provider = value.get("provider")
        if not isinstance(provider, str) or not provider:
            raise RegistryError(f"{path}: package provider must be a non-empty string")
        packages.add(provider)
    return packages


def build_catalog(root: Path) -> dict[str, Any]:
    manifests = manifest_paths(root)
    callable_paths = callable_skill_paths(root)
    expected_manifest_paths = {path.parent / "capability.json" for path in callable_paths}
    actual_manifest_paths = set(manifests)
    missing = sorted(expected_manifest_paths - actual_manifest_paths)
    if missing:
        relative = ", ".join(path.relative_to(root).as_posix() for path in missing)
        raise RegistryError(f"unregistered callable capability artifacts: {relative}")

    capabilities: list[dict[str, Any]] = []
    names: dict[str, Path] = {}
    identities: dict[str, Path] = {}
    aliases: dict[str, Path] = {}
    command_ids = declared_command_ids(root)
    package_ids = declared_package_ids(root)
    for path in manifests:
        reject_symlinks(path.parent, label="capability manifest input")
        manifest = read_json(path)
        validate_manifest(manifest, path, root)
        unresolved_commands = sorted(set(manifest["commands"]) - command_ids)
        if unresolved_commands:
            raise RegistryError(f"{path}: unresolved command reference(s): {', '.join(unresolved_commands)}")
        if manifest["ownership"]["package"] not in package_ids:
            raise RegistryError(f"{path}: unresolved package ownership {manifest['ownership']['package']!r}")
        name = manifest["canonical_name"]
        identity = manifest["provenance"]["source_identity"]
        if name in names:
            raise RegistryError(f"duplicate canonical_name {name!r}: {names[name]} and {path}")
        if identity in identities:
            raise RegistryError(f"duplicate source_identity {identity!r}: {identities[identity]} and {path}")
        names[name] = path
        identities[identity] = path
        for alias in manifest.get("compatibility_aliases", []):
            if alias in aliases:
                raise RegistryError(f"duplicate compatibility alias {alias!r}: {aliases[alias]} and {path}")
            aliases[alias] = path
        capabilities.append(manifest)

    for alias, alias_path in aliases.items():
        if alias in names:
            deprecated_source = read_json(names[alias])
            alias_owner = read_json(alias_path)
            if not (
                deprecated_source.get("lifecycle") == "deprecated"
                and deprecated_source.get("role") == "alias"
                and deprecated_source.get("alias_of") == alias_owner.get("canonical_name")
            ):
                raise RegistryError(f"compatibility alias {alias!r} collides with canonical capability at {names[alias]} (declared by {alias_path})")
    for manifest in capabilities:
        alias_of = manifest.get("alias_of")
        if alias_of:
            target = names.get(alias_of)
            if target is None:
                raise RegistryError(f"{alias_of!r} is not a canonical target for {manifest['canonical_name']!r}")
            if manifest["canonical_name"] not in read_json(target).get("compatibility_aliases", []):
                raise RegistryError(f"{manifest['canonical_name']!r} must be declared as a compatibility alias by {alias_of!r}")

    capabilities.sort(key=lambda item: item["canonical_name"])
    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_kind": "stack-capability-catalog",
        "capabilities": capabilities,
        "summary": {
            "capability_count": len(capabilities),
            "callable_entrypoint_count": len(callable_paths),
        },
    }


def write_catalog(root: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(canonical_json(build_catalog(root)), encoding="utf-8")


def catalog_matches(root: Path, output: Path) -> bool:
    return output.is_file() and output.read_text(encoding="utf-8") == canonical_json(build_catalog(root))


def frontmatter_value(skill_path: Path, key: str) -> str | None:
    lines = skill_path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        return None
    for line in lines[1:]:
        if line == "---":
            break
        match = re.fullmatch(rf"{re.escape(key)}:\s*(.*)", line)
        if match:
            return match.group(1).strip().strip("'\"")
    return None


def seed_manifest(root: Path, skill_path: Path) -> dict[str, Any]:
    relative_skill = skill_path.relative_to(root).as_posix()
    text = skill_path.read_text(encoding="utf-8")
    upstream_name = re.search(r"^[-*]\s+Upstream name:\s+`?([^`\n]+)`?", text, re.MULTILINE)
    imported = upstream_name is not None
    source_directory = skill_path.parent.relative_to(root / "skills")
    canonical_name = (
        source_directory.as_posix().replace("/", "-")
        if len(source_directory.parts) > 1
        else frontmatter_value(skill_path, "name") or skill_path.parent.name
    )
    canonical_name = re.sub(r"[^a-z0-9]+", "-", canonical_name.lower()).strip("-")
    purpose = frontmatter_value(skill_path, "description") or f"Seeded capability for {canonical_name}."
    return {
        "schema_version": SCHEMA_VERSION,
        "canonical_name": canonical_name,
        "purpose": purpose,
        "domain": "platform",
        "family": "platform",
        "role": "leaf",
        "visibility": "extended",
        "commands": ["stack.maintain"],
        "ownership": {"provider": "stack", "package": "stack", "source_path": relative_skill},
        "context": {"inputs": ["request"], "outputs": ["capability-result"]},
        "trust_class": "read-only",
        "validation_class": "structural",
        "artifact_type": "skill",
        "lifecycle": "candidate",
        "audit_status": "pending",
        "source": {"skill_path": relative_skill},
        "provenance": {
            "posture": "imported-upstream" if imported else "repository-local",
            "source_identity": (
                f"upstream:{relative_skill.removesuffix('/SKILL.md')}" if imported else f"stack:{relative_skill.removesuffix('/SKILL.md')}"
            ),
            "license": "unknown",
        },
        "overlaps": [],
        "validation": {"status": "pending", "evidence": []},
        "runtimes": {"supported": [], "publish_targets": []},
        "disposition": {
            "status": "hold-pending-evidence",
            "evidence_gap": "Seeded from the existing tree; estate audit has not reviewed this capability.",
            "next_review_trigger": "Complete the U2 capability estate audit.",
        },
    }


def seed_missing_manifests(root: Path) -> int:
    created = 0
    for skill_path in callable_skill_paths(root):
        path = skill_path.parent / "capability.json"
        if not path.exists():
            path.write_text(canonical_json(seed_manifest(root, skill_path)), encoding="utf-8")
            created += 1
    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Stack repository root")
    parser.add_argument("--output", type=Path, help="Generated catalog path")
    parser.add_argument("--check", action="store_true", help="Fail when the generated catalog has drifted")
    parser.add_argument("--seed-missing-manifests", action="store_true", help="Create only missing candidate manifests")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = (args.output or root / "registry" / "capabilities.json").resolve()
    try:
        if args.seed_missing_manifests:
            print(f"created {seed_missing_manifests(root)} capability manifests")
        if args.check:
            if not catalog_matches(root, output):
                raise RegistryError(f"aggregate catalog drift: rebuild {output.relative_to(root)}")
            print(f"catalog is current: {output.relative_to(root)}")
        elif not args.seed_missing_manifests:
            write_catalog(root, output)
            print(f"wrote {output.relative_to(root)}")
    except RegistryError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
