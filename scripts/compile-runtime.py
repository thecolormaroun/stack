#!/usr/bin/env python3
"""Compile validated catalog capabilities into deterministic runtime stages."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_LINK = re.compile(r"\[[^\]]*\]\(([^)#]+)(?:#[^)]+)?\)")
FENCE_START = re.compile(r"^[ \t]*(`{3,}|~{3,})")
OVERLAY_SPEC = importlib.util.spec_from_file_location("validate_private_overlay", Path(__file__).with_name("validate-private-overlay.py"))
assert OVERLAY_SPEC and OVERLAY_SPEC.loader
OVERLAY = importlib.util.module_from_spec(OVERLAY_SPEC)
OVERLAY_SPEC.loader.exec_module(OVERLAY)


class RuntimeError(ValueError):
    """A catalog runtime cannot be safely compiled."""


def canonical_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"{path}: invalid JSON") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"{path}: expected an object")
    return value


def repository_relative(root: Path, value: str, *, label: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise RuntimeError(f"{label}: must be repository-relative")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise RuntimeError(f"{label}: escapes repository root") from error
    return resolved


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_commit(root: Path) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def git_output(root: Path, *args: str) -> str | None:
    try:
        return subprocess.check_output(["git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def fixture_root(root: Path) -> bool:
    return git_output(root, "rev-parse", "--is-inside-work-tree") is None


def source_tree_digest(root: Path) -> str:
    listing = git_output(root, "ls-files", "-s")
    if listing is not None:
        return hashlib.sha256(listing.encode("utf-8")).hexdigest()
    records: list[str] = []
    # Fixture roots have no Git index. Limit their source fingerprint to the
    # repository input namespaces so an earlier staging directory cannot alter
    # a later stage's attestation.
    for path in sorted(root.rglob("*")):
        if not path.relative_to(root).parts or path.relative_to(root).parts[0] not in {"skills", "registry", "config"}:
            continue
        if path.is_file() and not path.is_symlink():
            records.append(f"{path.relative_to(root).as_posix()}:{digest_file(path)}")
    return hashlib.sha256("\n".join(records).encode("utf-8")).hexdigest()


def reject_symlinks(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise RuntimeError(f"{label}: symlinks are not allowed: {path}")
    if path.is_dir():
        for entry in path.rglob("*"):
            if entry.is_symlink():
                raise RuntimeError(f"{label}: symlinks are not allowed: {entry}")


def staged_tree_digest(stage: Path) -> str:
    records: list[str] = []
    for path in sorted(stage.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"staged public tree: symlinks are not allowed: {path}")
        if path.is_file() and path.name not in {"runtime-manifest.json", "stage-attestation.json"}:
            records.append(f"{path.relative_to(stage).as_posix()}:{digest_file(path)}")
    return hashlib.sha256("\n".join(records).encode("utf-8")).hexdigest()


def scan_public_tree(stage: Path) -> None:
    reject_symlinks(stage, label="staged public tree")
    for path in sorted(stage.rglob("*")):
        if path.is_file():
            if path.name in {"runtime-manifest.json", "stage-attestation.json"}:
                scan_public_artifact(path)
                continue
            try:
                OVERLAY.scan_public_runtime_payload(path)
            except UnicodeDecodeError:
                payload = path.read_bytes()
                forbidden = [
                    *(marker.encode("utf-8") for marker in OVERLAY.PRIVATE_MARKERS),
                    b"file://",
                    b"/Users/",
                    b"/home/",
                ]
                if any(marker in payload for marker in forbidden):
                    raise RuntimeError(
                        f"public runtime payload validation failed: {path} contains private identifying data"
                    )
            except OVERLAY.OverlayError as error:
                raise RuntimeError(f"public runtime payload validation failed: {error}") from error


def compilation_identity(root: Path, requested_commit: str | None) -> tuple[str, str]:
    actual_commit = source_commit(root)
    dirty = git_output(root, "status", "--porcelain")
    if not fixture_root(root):
        if dirty:
            raise RuntimeError("refusing to stage a dirty source tree")
        if requested_commit is not None and requested_commit != actual_commit:
            raise RuntimeError("source_commit override must match the checked-out commit")
    elif requested_commit is not None and not re.fullmatch(r"[A-Za-z0-9._-]+", requested_commit):
        raise RuntimeError("fixture source_commit override is invalid")
    return requested_commit or actual_commit, source_tree_digest(root)


def targets_from(path: Path) -> list[dict[str, Any]]:
    value = read_json(path)
    targets = value.get("targets")
    if value.get("schema_version") != 1 or not isinstance(targets, list):
        raise RuntimeError(f"{path}: expected schema_version 1 with targets list")
    names: set[str] = set()
    for target in targets:
        if not isinstance(target, dict) or not all(isinstance(target.get(key), str) and target[key] for key in ("name", "runtime", "destination")):
            raise RuntimeError(f"{path}: every target requires name, runtime, and destination")
        if target["name"] in names:
            raise RuntimeError(f"{path}: duplicate target {target['name']}")
        names.add(target["name"])
    return sorted(targets, key=lambda item: item["name"])


def declared_catalog_digest(path: Path) -> str | None:
    value = read_json(path)
    digest = value.get("catalog_digest")
    if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise RuntimeError(f"{path}: catalog_digest must be a SHA-256 hex digest")
    return digest


def exclusion(capability: dict[str, Any], runtime: str) -> str | None:
    lifecycle = capability.get("lifecycle")
    compatibility_adapter = lifecycle == "deprecated" and capability.get("role") in {"alias", "adapter"} and capability.get("visibility") == "compatibility" and isinstance(capability.get("alias_of"), str)
    if lifecycle != "active" and not compatibility_adapter:
        return f"lifecycle-{lifecycle}" if isinstance(lifecycle, str) else "invalid-lifecycle"
    if capability.get("artifact_type") == "private-overlay" or "overlay_id" in capability.get("source", {}):
        return "private-incompatible"
    runtimes = capability.get("runtimes")
    if not isinstance(runtimes, dict) or runtime not in runtimes.get("supported", []) or runtime not in runtimes.get("publish_targets", []):
        return "unsupported-runtime"
    return None


def transform_markdown_links(text: str, transform) -> str:
    """Transform Markdown links while leaving fenced examples untouched."""
    output: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        marker = FENCE_START.match(line)
        if fence is not None:
            output.append(line)
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                fence = None
            continue
        if marker:
            fence = marker.group(1)
            output.append(line)
            continue
        output.append(REFERENCE_LINK.sub(transform, line))
    return "".join(output)


def validate_reference(skill_path: Path, root: Path) -> None:
    text = skill_path.read_text(encoding="utf-8")
    references: list[str] = []
    transform_markdown_links(text, lambda match: references.append(match.group(1).strip()) or match.group(0))
    for reference in references:
        if "://" in reference or reference.startswith(("/", "#")):
            continue
        candidate = (skill_path.parent / reference).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError as error:
            raise RuntimeError(f"reference {reference!r} in {skill_path} escapes repository root") from error
        if not candidate.exists():
            raise RuntimeError(f"reference {reference!r} in {skill_path} does not exist")


def validate_included(root: Path, capabilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names = {item.get("canonical_name") for item in capabilities}
    adapter_names = {item.get("canonical_name") for item in capabilities if item.get("lifecycle") == "deprecated" and item.get("role") in {"alias", "adapter"}}
    entries: list[dict[str, Any]] = []
    alias_owners: dict[str, str] = {}
    for capability in capabilities:
        name = capability.get("canonical_name")
        source = capability.get("source")
        if not isinstance(name, str) or not isinstance(source, dict) or not isinstance(source.get("skill_path"), str):
            raise RuntimeError("included capability requires canonical_name and source.skill_path")
        raw_skill_path = root / Path(source["skill_path"])
        reject_symlinks(raw_skill_path.parent, label=f"{name} capability input")
        skill_path = repository_relative(root, source["skill_path"], label=f"{name} source path")
        reject_symlinks(skill_path.parent, label=f"{name} capability input")
        if not skill_path.is_file():
            raise RuntimeError(f"{name} source path does not exist: {source['skill_path']}")
        dependencies = capability.get("dependencies", [])
        if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
            raise RuntimeError(f"{name} dependencies must be a list of capability names")
        missing = sorted(set(dependencies) - names)
        if missing:
            raise RuntimeError(f"{name} dependency closure is incomplete: {', '.join(missing)}")
        aliases = [alias for alias in capability.get("compatibility_aliases", []) if alias not in adapter_names]
        if not isinstance(aliases, list) or len(aliases) != len(set(aliases)) or not all(
            isinstance(alias, str) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", alias)
            for alias in aliases
        ):
            raise RuntimeError(f"{name} compatibility_aliases are invalid")
        for alias in aliases:
            if alias in names or alias in alias_owners:
                raise RuntimeError(f"{name} compatibility alias collides with {alias}")
            alias_owners[alias] = name
        entries.append({"canonical_name": name, "source_path": source["skill_path"], "compatibility_aliases": sorted(aliases), "lifecycle": capability.get("lifecycle"), "alias_of": capability.get("alias_of")})
    return sorted(entries, key=lambda item: item["canonical_name"])


def bundled_exports(root: Path) -> tuple[Path, list[str]] | None:
    """Validate the repository-owned Stack-Codex bundle before copying it."""
    upstreams_path = root / "registry/upstreams.json"
    # Small isolated compiler fixtures may intentionally exercise only the
    # catalog contract. A real Stack checkout always declares this bundle.
    if not upstreams_path.is_file():
        return None
    upstreams = read_json(upstreams_path)
    provider = next((item for item in upstreams.get("providers", []) if isinstance(item, dict) and item.get("id") == "stack-codex"), None)
    if provider is None or provider.get("install") != "repository-bundle":
        raise RuntimeError("Stack-Codex repository bundle is not declared")
    bundle_path = provider.get("bundle_path")
    exports = provider.get("exports")
    if not isinstance(bundle_path, str) or not isinstance(exports, list) or not all(isinstance(item, str) for item in exports):
        raise RuntimeError("Stack-Codex repository bundle metadata is invalid")
    bundle = repository_relative(root, bundle_path, label="Stack-Codex bundle path")
    reject_symlinks(bundle, label="Stack-Codex bundle")
    if not bundle.is_dir():
        raise RuntimeError("Stack-Codex repository bundle is missing")
    missing = [name for name in exports if not (bundle / "skills" / name / "SKILL.md").is_file()]
    if missing:
        raise RuntimeError("Stack-Codex bundle is missing declared exports: " + ", ".join(missing))
    return bundle, sorted(exports)


def copy_bundle(stage: Path, bundle: Path, exports: list[str], local_names: set[str], shadowed: dict[str, str]) -> None:
    unknown_shadowing = sorted(set(shadowed) - set(exports))
    if unknown_shadowing:
        raise RuntimeError("command adapter shadows undeclared Stack-Codex exports: " + ", ".join(unknown_shadowing))
    collisions = sorted(local_names & (set(exports) - set(shadowed)))
    if collisions:
        raise RuntimeError("Stack-Codex bundled export collides with local capability: " + ", ".join(collisions))
    for name in exports:
        if name in shadowed:
            continue
        shutil.copytree(bundle / "skills" / name, stage / "skills" / name)
    for directory in ("commands", "agents", "references", "config", ".codex-plugin"):
        source = bundle / directory
        if source.exists():
            destination = stage / directory
            if destination.exists():
                raise RuntimeError(f"Stack-Codex bundle path collides with staged output: {directory}")
            shutil.copytree(source, destination)
    for filename in ("README.md",):
        source = bundle / filename
        if source.is_file():
            shutil.copy2(source, stage / filename)


def external_package_exports(root: Path, package_cache: Path | None) -> list[tuple[str, str, Path]]:
    upstreams_path = root / "registry/upstreams.json"
    if not upstreams_path.is_file():
        return []
    providers = read_json(upstreams_path).get("providers", [])
    pinned = [provider for provider in providers if isinstance(provider, dict) and provider.get("install") == "pinned-git-checkout"]
    if not pinned:
        return []
    if package_cache is None:
        raise RuntimeError("pinned external package exports require a verified package cache")
    resolved: list[tuple[str, str, Path]] = []
    for provider in pinned:
        provider_id, exports, export_paths = provider.get("id"), provider.get("exports"), provider.get("export_paths")
        if not isinstance(provider_id, str) or not isinstance(exports, list) or not all(isinstance(item, str) for item in exports) or not isinstance(export_paths, dict) or set(export_paths) != set(exports):
            raise RuntimeError("external package metadata is invalid")
        checkout = package_cache / provider_id
        if not checkout.is_dir():
            raise RuntimeError(f"verified package cache is missing {provider_id}")
        source = provider.get("canonical_source")
        pin = provider.get("pin", {}).get("value") if isinstance(provider.get("pin"), dict) else None
        try:
            origin = subprocess.check_output(["git", "-C", str(checkout), "remote", "get-url", "origin"], text=True, stderr=subprocess.DEVNULL).strip()
            head = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
            dirty = subprocess.check_output(["git", "-C", str(checkout), "status", "--porcelain"], text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError) as error:
            raise RuntimeError(f"{provider_id} package cache is not a verifiable Git checkout") from error
        if not isinstance(source, str) or origin.rstrip("/") != source.rstrip("/"):
            raise RuntimeError(f"{provider_id} package cache origin does not match registry")
        if not isinstance(pin, str) or head != pin:
            raise RuntimeError(f"{provider_id} package cache HEAD does not match registry pin")
        if dirty:
            raise RuntimeError(f"{provider_id} package cache is dirty")
        for export in exports:
            relative = export_paths[export]
            if not isinstance(relative, str):
                raise RuntimeError(f"{provider_id} export {export} has an invalid declared path")
            skill = repository_relative(checkout, relative, label=f"{provider_id} export {export} path")
            reject_symlinks(skill.parent, label=f"{provider_id} export {export}")
            reject_symlinks(skill, label=f"{provider_id} export {export}")
            if not skill.is_file() or skill.name != "SKILL.md":
                raise RuntimeError(f"{provider_id} export {export} does not resolve to its declared SKILL.md")
            resolved.append((provider_id, export, skill.parent))
    return sorted(resolved)


def runtime_skill_name(command: dict[str, Any], runtime: str) -> str:
    invocation = command.get("runtimes", {}).get(runtime)
    if not isinstance(invocation, str) or not invocation:
        raise RuntimeError(f"command {command.get('id', '<unknown>')} has no {runtime} runtime name")
    name = invocation.removeprefix("/").replace(" ", "-")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise RuntimeError(f"command {command.get('id', '<unknown>')} has an invalid {runtime} runtime name")
    return name


def approval_behavior(trust_class: str) -> str:
    if trust_class == "external-mutation":
        return "Require explicit user approval before any external mutation, publication, deployment, or release action."
    if trust_class == "local-mutation":
        return "Work only inside the requested workspace and require approval before destructive or irreversible changes."
    if trust_class == "read-only":
        return "Remain read-only unless the user separately authorizes a mutation-capable follow-up."
    raise RuntimeError(f"unsupported command trust class {trust_class!r}")


def command_adapter_text(command: dict[str, Any], runtime: str, name: str) -> str:
    command_id = command.get("id")
    owner = command.get("owner")
    delegates = command.get("delegates", [])
    aliases = command.get("aliases", [])
    trust_class = command.get("trust_class")
    inputs, outputs = command.get("inputs"), command.get("outputs")
    if not isinstance(command_id, str) or not isinstance(owner, dict) or not all(isinstance(owner.get(key), str) for key in ("kind", "id")):
        raise RuntimeError("command adapter requires a canonical id and owner")
    if not isinstance(delegates, list) or not all(isinstance(item, dict) and isinstance(item.get("provider"), str) and isinstance(item.get("command"), str) for item in delegates):
        raise RuntimeError(f"command {command_id} has invalid delegates")
    if not isinstance(inputs, list) or not all(isinstance(item, str) for item in inputs) or not isinstance(outputs, list) or not all(isinstance(item, str) for item in outputs):
        raise RuntimeError(f"command {command_id} has invalid input/output contract")
    if not isinstance(aliases, list) or not all(isinstance(item, dict) and isinstance(item.get("name"), str) for item in aliases):
        raise RuntimeError(f"command {command_id} has invalid aliases")
    delegate_lines = [f"- `{item['provider']}:{item['command']}`" for item in delegates] or ["- None; invoke the declared owner directly."]
    alias_lines = [f"- `{item['name']}` ({item.get('kind', 'alias')}; canonical warning: {str(bool(item.get('canonical_warning'))).lower()})" for item in aliases] or ["- None"]
    invocation = command["runtimes"][runtime]
    return "\n".join([
        "---", f"name: {name}", f"description: Canonical runtime adapter for {command_id}.", "---", "",
        f"# {command_id}", "", f"Runtime invocation: `{invocation}`", f"Canonical command: `{command_id}`",
        f"Owner: `{owner['kind']}:{owner['id']}`", f"Trust class: `{trust_class}`", "",
        "Apply `registry/commands.json` and the staged routing contract. Do not duplicate upstream workflow logic.",
        "Invoke the declared owner and, when the route requires it, the declared delegate:", "", *delegate_lines, "",
        "Inputs: " + ", ".join(f"`{item}`" for item in inputs),
        "Outputs: " + ", ".join(f"`{item}`" for item in outputs), "",
        "Approval behavior: " + approval_behavior(trust_class), "", "Declared aliases:", "", *alias_lines, "",
    ])


def materialize_command_adapters(root: Path, stage: Path, runtime: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    commands_path = root / "registry/commands.json"
    if not commands_path.is_file():
        return [], []
    commands = read_json(commands_path).get("commands")
    if not isinstance(commands, list):
        raise RuntimeError("command registry lacks commands")
    primary_names: dict[str, str] = {}
    for command in commands:
        if not isinstance(command, dict) or command.get("visibility") != "primary":
            continue
        name = runtime_skill_name(command, runtime)
        if name in primary_names:
            raise RuntimeError(f"runtime command adapter collision: {name}")
        primary_names[name] = command["id"]
    adapters: list[dict[str, Any]] = []
    alias_resolutions: list[dict[str, str]] = []
    for command in commands:
        if not isinstance(command, dict) or command.get("visibility") != "primary":
            continue
        name = runtime_skill_name(command, runtime)
        destination = stage / "skills" / name
        if destination.exists():
            raise RuntimeError(f"runtime command adapter collides with staged skill: {name}")
        destination.mkdir(parents=True)
        (destination / "SKILL.md").write_text(command_adapter_text(command, runtime, name), encoding="utf-8")
        adapter = {"canonical_id": command["id"], "runtime_name": command["runtimes"][runtime], "skill_name": name, "path": f"skills/{name}/SKILL.md", "owner": command["owner"], "delegates": command.get("delegates", []), "trust_class": command["trust_class"], "inputs": command["inputs"], "outputs": command["outputs"], "approval_behavior": approval_behavior(command["trust_class"])}
        adapters.append(adapter)
        for alias in command.get("aliases", []):
            alias_name = alias["name"].removeprefix("/").replace(" ", "-")
            if alias_name == name:
                alias_resolutions.append({"alias": alias_name, "canonical_id": command["id"], "resolution": "primary-route"})
                continue
            alias_path = stage / "skills" / alias_name
            if alias_path.exists():
                alias_resolutions.append({"alias": alias_name, "canonical_id": command["id"], "resolution": "declared-export"})
                continue
            alias_path.mkdir(parents=True)
            warning = "This is a compatibility alias. Prefer the canonical route.\n\n" if alias.get("canonical_warning") else ""
            (alias_path / "SKILL.md").write_text(f"---\nname: {alias_name}\ndescription: Alias for {command['id']}.\n---\n\n# {alias_name}\n\n{warning}Apply `{name}` and its canonical `{command['id']}` registry contract.\n", encoding="utf-8")
            alias_resolutions.append({"alias": alias_name, "canonical_id": command["id"], "resolution": "generated-alias"})
    return sorted(adapters, key=lambda item: item["canonical_id"]), sorted(alias_resolutions, key=lambda item: (item["alias"], item["canonical_id"]))


def source_file_map(source: Path, destination: Path, mapping: dict[Path, Path]) -> None:
    for path in source.rglob("*"):
        if path.is_file():
            mapping[path.resolve()] = destination / path.relative_to(source)


def copy_shared_tree(source: Path, destination: Path, mapping: dict[Path, Path], *, label: str) -> None:
    reject_symlinks(source, label=label)
    shutil.copytree(source, destination)
    source_file_map(source, destination, mapping)


def rewrite_relative_links(stage: Path, mapping: dict[Path, Path]) -> None:
    """Keep copied Markdown links valid after canonical capability flattening."""
    def replacement(source: Path, destination: Path, match: re.Match[str]) -> str:
        raw = match.group(1).strip()
        if "://" in raw or raw.startswith(("/", "#")):
            return match.group(0)
        target_part, marker, anchor = raw.partition("#")
        target = (source.parent / target_part).resolve()
        staged_target = mapping.get(target)
        if staged_target is None:
            # Some imported skills use a logical cross-skill reference (for
            # example `reference/foo.md`) instead of a repository-relative
            # path. Resolve only a unique staged source suffix; ambiguity is
            # rejected by the normal staged-link validator below.
            suffix_matches = [staged for origin, staged in mapping.items() if origin.as_posix().endswith(target_part)]
            if len(suffix_matches) == 1:
                staged_target = suffix_matches[0]
        if staged_target is None:
            return match.group(0)
        relative = os.path.relpath(staged_target, destination.parent).replace(os.sep, "/")
        return match.group(0).replace(raw, relative + (marker + anchor if marker else ""))

    for staged_file in sorted(path for path in stage.rglob("*.md") if path.is_file()):
        original = next((origin for origin, staged in mapping.items() if staged == staged_file), None)
        if original is None:
            continue
        text = staged_file.read_text(encoding="utf-8")
        updated = transform_markdown_links(
            text,
            lambda match: replacement(original, staged_file, match),
        )
        staged_file.write_text(updated, encoding="utf-8")


def validate_staged_links(stage: Path) -> None:
    for path in sorted(stage.rglob("*.md")):
        relative_parts = path.relative_to(stage).parts
        # Templates and examples describe files that will exist in a generated
        # project or report, not dependencies of the installed skill package.
        if "templates" in relative_parts or "examples" in relative_parts:
            continue
        validate_reference(path, stage)


def scan_public_artifact(path: Path) -> None:
    try:
        OVERLAY.scan_public_artifact(path)
    except OVERLAY.OverlayError as error:
        raise RuntimeError(f"public artifact validation failed: {error}") from error


def compile_private_overlays(overlay_path: Path, targets: list[dict[str, Any]], output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    os.chmod(output_root, 0o700)
    for target in targets:
        target_root = output_root / target["name"]
        target_root.mkdir(mode=0o700, exist_ok=True)
        os.chmod(target_root, 0o700)
        try:
            OVERLAY.compile_overlay(overlay_path, target["name"], target_root / "private")
        except OVERLAY.OverlayError as error:
            raise RuntimeError(f"private overlay validation failed for {target['name']}: {error}") from error


def compile_runtimes(root: Path, catalog_path: Path, targets_path: Path, staging_root: Path, *, source_commit: str | None = None, private_overlay: Path | None = None, private_output_root: Path | None = None, package_cache: Path | None = None) -> dict[str, Path]:
    root = root.resolve()
    catalog_path = catalog_path.resolve()
    reject_symlinks(catalog_path, label="catalog input")
    reject_symlinks(targets_path.resolve(), label="runtime target input")
    catalog = read_json(catalog_path)
    capabilities = catalog.get("capabilities")
    if catalog.get("schema_version") != 1 or not isinstance(capabilities, list):
        raise RuntimeError(f"{catalog_path}: expected schema_version 1 catalog with capabilities")
    scan_public_artifact(catalog_path)
    registry_digest = digest_file(catalog_path)
    targets = targets_from(targets_path.resolve())
    expected_digest = declared_catalog_digest(targets_path.resolve())
    if targets and expected_digest is None:
        raise RuntimeError("non-empty runtime targets must pin catalog_digest")
    if expected_digest is not None and expected_digest != registry_digest:
        raise RuntimeError("catalog digest does not match runtime targets")
    output: dict[str, Path] = {}
    # With no publication targets there is nothing to attest. Keep this useful
    # smoke check available in a working tree without weakening real builds.
    if not targets:
        return output
    commit, tree_digest = compilation_identity(root, source_commit)
    bundle_spec = bundled_exports(root)
    package_exports = external_package_exports(root, package_cache)
    commands_path = root / "registry/commands.json"
    commands = read_json(commands_path).get("commands", []) if commands_path.is_file() else []
    for target in targets:
        included_raw: list[dict[str, Any]] = []
        excluded: list[dict[str, str]] = []
        for capability in capabilities:
            if not isinstance(capability, dict):
                raise RuntimeError("catalog capabilities must be objects")
            name = capability.get("canonical_name")
            if not isinstance(name, str):
                raise RuntimeError("catalog capability missing canonical_name")
            reason = exclusion(capability, target["runtime"])
            if reason is None:
                included_raw.append(capability)
            else:
                excluded.append({"canonical_name": name, "reason": reason})
        included = validate_included(root, included_raw)
        stage = staging_root.resolve() / target["name"] / registry_digest
        if stage.exists():
            reject_symlinks(stage, label="existing staged public tree")
            shutil.rmtree(stage)
        stage.mkdir(parents=True)
        mapping: dict[Path, Path] = {}
        for entry in included:
            source = repository_relative(root, entry["source_path"], label=f"{entry['canonical_name']} source path")
            destination = stage / "skills" / entry["canonical_name"]
            shutil.copytree(source.parent, destination)
            source_file_map(source.parent, destination, mapping)
            for alias in entry["compatibility_aliases"]:
                shutil.copytree(source.parent, stage / "skills" / alias)
        bundle_exports: list[str] = []
        shadowed_bundle_exports: list[dict[str, str]] = []
        if bundle_spec is not None:
            bundle, bundle_exports = bundle_spec
            declared_shadowing = {
                runtime_skill_name(command, target["runtime"]): command["id"]
                for command in commands if isinstance(command, dict) and command.get("id") in {"stack.review", "stack.ship"}
            }
            shadowed = {name: command_id for name, command_id in declared_shadowing.items() if name in bundle_exports}
            copy_bundle(stage, bundle, bundle_exports, {entry["canonical_name"] for entry in included}, shadowed)
            shadowed_bundle_exports = [{"shadowed_bundle_export": name, "canonical_command": command_id} for name, command_id in sorted(shadowed.items())]
            source_file_map(bundle, stage, mapping)
        external_manifest: list[dict[str, str]] = []
        for provider, export, source in package_exports:
            if (stage / "skills" / export).exists():
                raise RuntimeError(f"external package export collides with staged skill: {export}")
            destination = stage / "skills" / export
            shutil.copytree(source, destination)
            source_file_map(source, destination, mapping)
            external_manifest.append({"provider": provider, "export": export})
        command_adapters, command_aliases = materialize_command_adapters(root, stage, target["runtime"])
        docs = root / "docs"
        if docs.is_dir():
            copy_shared_tree(docs, stage / "docs", mapping, label="shared docs input")
        if (root / "README.md").is_file():
            reject_symlinks(root / "README.md", label="shared README input")
            shutil.copy2(root / "README.md", stage / "README.md")
            mapping[(root / "README.md").resolve()] = stage / "README.md"
        for shared in ("registry", "templates"):
            source = root / shared
            if source.is_dir():
                copy_shared_tree(source, stage / shared, mapping, label=f"shared {shared} input")
        verification_artifacts = root / "artifacts" / "private-overlay-verification"
        if verification_artifacts.is_dir():
            destination = stage / "artifacts" / "private-overlay-verification"
            destination.parent.mkdir(parents=True, exist_ok=True)
            copy_shared_tree(verification_artifacts, destination, mapping, label="private-overlay verification input")
        rewrite_relative_links(stage, mapping)
        validate_staged_links(stage)
        aliases = [
            {"alias": alias, "canonical_target": entry["canonical_name"]}
            for entry in included
            for alias in entry["compatibility_aliases"]
        ]
        manifest = {
            "schema_version": 1,
            "target": target["name"],
            "runtime": target["runtime"],
            "source_commit": commit,
            "registry_digest": registry_digest,
            "included": included,
            "bundled_exports": bundle_exports,
            "shadowed_bundle_exports": shadowed_bundle_exports,
            "external_package_exports": external_manifest,
            "command_adapters": command_adapters,
            "command_aliases": command_aliases,
            "compatibility_adapters": sorted(entry["canonical_name"] for entry in included_raw if entry.get("lifecycle") == "deprecated"),
            "compatibility_aliases": sorted(aliases, key=lambda item: item["alias"]),
            "excluded": sorted(excluded, key=lambda item: item["canonical_name"]),
            "validation": "passed",
        }
        (stage / "runtime-manifest.json").write_text(canonical_json(manifest), encoding="utf-8")
        runtime_manifest_digest = digest_file(stage / "runtime-manifest.json")
        attestation = {
            "schema_version": 1,
            "catalog_digest": registry_digest,
            "runtime_manifest_digest": runtime_manifest_digest,
            "staged_tree_digest": staged_tree_digest(stage),
            "source_commit": commit,
            "source_tree_digest": tree_digest,
        }
        (stage / "stage-attestation.json").write_text(canonical_json(attestation), encoding="utf-8")
        scan_public_tree(stage)
        output[target["name"]] = stage
    if private_overlay is not None:
        if private_output_root is None:
            raise RuntimeError("private overlay compilation requires a separate private output root")
        compile_private_overlays(private_overlay, targets, private_output_root)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--targets", type=Path)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--source-commit")
    parser.add_argument("--private-overlay", type=Path)
    parser.add_argument("--private-output-root", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        stages = compile_runtimes(root, args.catalog or root / "registry/capabilities.json", args.targets or root / "config/runtime-targets.json", args.staging_root, source_commit=args.source_commit, private_overlay=args.private_overlay, private_output_root=args.private_output_root)
        print(canonical_json({"staged": {name: str(path) for name, path in stages.items()}}).rstrip())
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
