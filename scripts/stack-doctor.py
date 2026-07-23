#!/usr/bin/env python3
"""Read-only health checks for Stack's public runtime contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PRIMARY_TARGETS = {"claude": ".claude/skills/stack", "codex": ".codex/skills/stack"}


class DoctorError(ValueError):
    """A public Stack contract is incomplete or inconsistent."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DoctorError(f"invalid JSON: {path.name}") from error
    if not isinstance(value, dict):
        raise DoctorError(f"expected object: {path.name}")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def directory_sha256(path: Path) -> str:
    if not path.is_dir():
        raise DoctorError("repository bundle is missing")
    files = sorted(candidate for candidate in path.rglob("*") if candidate.is_file())
    if not files:
        raise DoctorError("repository bundle is empty")
    digest = hashlib.sha256()
    for candidate in files:
        digest.update(candidate.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(candidate.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def source_state(root: Path) -> dict[str, Any]:
    try:
        commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True, stderr=subprocess.DEVNULL).strip())
    except (OSError, subprocess.CalledProcessError):
        return {"commit": "unavailable", "dirty": None}
    return {"commit": commit, "dirty": dirty}


def runtime_skill_name(command: dict[str, Any], runtime: str) -> str | None:
    invocation = command.get("runtimes", {}).get(runtime)
    if not isinstance(invocation, str) or not invocation:
        return None
    return invocation.removeprefix("/").replace(" ", "-")


def package_health(root: Path, providers: dict[str, dict[str, Any]]) -> list[str]:
    lock = read_json(root / "upstreams.lock.json").get("providers")
    if not isinstance(lock, dict):
        raise DoctorError("upstreams lock lacks providers")
    errors: list[str] = []
    for path in sorted((root / "packages").glob("*/package.json")):
        package = read_json(path)
        if package.get("schema_version") != 1 or package.get("registry") != "registry/upstreams.json":
            errors.append(f"package {path.parent.name} has invalid registry contract")
            continue
        ids = package.get("providers", [package.get("provider")])
        if not isinstance(ids, list) or not all(isinstance(value, str) and value in providers for value in ids):
            errors.append(f"package {path.parent.name} references an unknown provider")
            continue
        if package.get("copy_upstream_source") is not False:
            errors.append(f"package {path.parent.name} must not copy upstream source")
        for provider_id in ids:
            provider = providers[provider_id]
            pin = provider.get("pin", {}).get("value") if isinstance(provider.get("pin"), dict) else None
            if not isinstance(pin, str) or lock.get(provider_id) != pin or provider.get("last_known_good", {}).get("pin") != pin:
                errors.append(f"provider {provider_id} pin is not last-known-good")
                continue
            if provider.get("install") == "repository-bundle":
                bundle_path = provider.get("bundle_path")
                try:
                    actual_digest = directory_sha256(root / bundle_path) if isinstance(bundle_path, str) else None
                except DoctorError as error:
                    errors.append(f"provider {provider_id} {error}")
                else:
                    if actual_digest != pin:
                        errors.append(f"provider {provider_id} bundled content failed integrity verification")
                    elif provider_id == "stack-codex":
                        required = [*(f"skills/{name}/SKILL.md" for name in provider.get("exports", [])), "agents/explorer.toml", "agents/reviewer.toml", "agents/worker.toml", "references/agent-execution-policy.md", "references/frontend-libraries.md", "references/upstreams.md"]
                        if any(not (root / bundle_path / relative).is_file() for relative in required):
                            errors.append(f"provider {provider_id} bundle lacks expected resolvable exports")
        exports = package.get("exports")
        if exports is not None and (not isinstance(exports, list) or any(item not in providers[ids[0]].get("exports", []) for item in exports)):
            errors.append(f"package {path.parent.name} exports drift from provider metadata")
    return errors


def runtime_health(root: Path, deployment_root: Path | None) -> list[str]:
    targets_data = read_json(root / "config/runtime-targets.json")
    targets = targets_data.get("targets")
    if targets_data.get("schema_version") != 1 or not isinstance(targets, list):
        return ["runtime targets are invalid"]
    if not targets:
        return []
    by_name = {target.get("name"): target for target in targets if isinstance(target, dict)}
    if set(by_name) != set(PRIMARY_TARGETS) or len(by_name) != len(targets):
        return ["runtime targets lack strict Claude/Codex primary parity"]
    errors: list[str] = []
    for name, destination in PRIMARY_TARGETS.items():
        target = by_name[name]
        if target.get("runtime") != name or target.get("destination") != destination:
            errors.append(f"runtime target {name} is not a safe namespaced primary destination")
    if deployment_root is None:
        return errors
    commands = read_json(root / "registry/commands.json").get("commands", [])
    primary_commands = [item for item in commands if isinstance(item, dict) and item.get("visibility", "primary") == "primary"]
    providers = read_json(root / "registry/upstreams.json").get("providers", [])
    expected_bundle_exports = {
        export
        for provider in providers if isinstance(provider, dict) and provider.get("install") == "repository-bundle"
        for export in provider.get("exports", []) if isinstance(export, str)
    }
    expected_package_exports = {
        (provider.get("id"), export)
        for provider in providers if isinstance(provider, dict) and provider.get("install") == "pinned-git-checkout"
        for export in provider.get("exports", []) if isinstance(export, str)
    }
    for name, destination in PRIMARY_TARGETS.items():
        installed = deployment_root / destination
        if not installed.is_symlink() or not installed.resolve().is_dir():
            errors.append(f"runtime target {name} is not atomically installed")
            continue
        manifest_path = installed.resolve() / "runtime-manifest.json"
        try:
            manifest = read_json(manifest_path)
        except DoctorError:
            errors.append(f"runtime target {name} has no resolvable manifest")
            continue
        if manifest.get("target") != name or manifest.get("runtime") != name:
            errors.append(f"runtime target {name} manifest does not match target")
        bundle_exports = manifest.get("bundled_exports", [])
        shadowed_values = manifest.get("shadowed_bundle_exports", [])
        shadowed = {item.get("shadowed_bundle_export") for item in shadowed_values if isinstance(item, dict)}
        if shadowed_values != [
            {"shadowed_bundle_export": "stack-review", "canonical_command": "stack.review"},
            {"shadowed_bundle_export": "stack-ship", "canonical_command": "stack.ship"},
        ]:
            errors.append(f"runtime target {name} has invalid Stack-Codex collision resolution")
        if not isinstance(bundle_exports, list) or set(bundle_exports) != expected_bundle_exports or any(export not in shadowed and not (installed.resolve() / "skills" / export / "SKILL.md").is_file() for export in bundle_exports):
            errors.append(f"runtime target {name} lacks resolvable bundled exports")
        package_exports = manifest.get("external_package_exports", [])
        actual_package_exports = {
            (item.get("provider"), item.get("export"))
            for item in package_exports if isinstance(item, dict)
        } if isinstance(package_exports, list) else set()
        if actual_package_exports != expected_package_exports or any(not isinstance(item, dict) or not isinstance(item.get("export"), str) or not (installed.resolve() / "skills" / item["export"] / "SKILL.md").is_file() for item in package_exports):
            errors.append(f"runtime target {name} lacks resolvable external package exports")
        adapters = manifest.get("command_adapters")
        aliases = manifest.get("command_aliases")
        expected = {
            command["id"]: runtime_skill_name(command, name)
            for command in primary_commands
        }
        actual = {
            item.get("canonical_id"): item.get("skill_name")
            for item in adapters if isinstance(item, dict)
        } if isinstance(adapters, list) else {}
        if actual != expected or len(actual) != len(primary_commands):
            errors.append(f"runtime target {name} does not materialize every primary command adapter")
        elif any(not (installed.resolve() / "skills" / skill_name / "SKILL.md").is_file() for skill_name in actual.values() if isinstance(skill_name, str)):
            errors.append(f"runtime target {name} has an unresolvable primary command adapter")
        expected_aliases = {
            alias["name"].removeprefix("/").replace(" ", "-")
            for command in primary_commands for alias in command.get("aliases", [])
            if isinstance(alias, dict) and isinstance(alias.get("name"), str)
        }
        actual_aliases = {item.get("alias") for item in aliases if isinstance(item, dict)} if isinstance(aliases, list) else set()
        if actual_aliases != expected_aliases or any(not (installed.resolve() / "skills" / alias / "SKILL.md").is_file() for alias in expected_aliases):
            errors.append(f"runtime target {name} lacks a declared command alias")
    cache = deployment_root / ".stack-packages"
    for provider in ("compound-engineering", "gstack"):
        checkout = cache / provider
        if not checkout.is_dir():
            errors.append(f"deployment package cache is missing {provider}")
            continue
        try:
            actual = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
            dirty = subprocess.check_output(["git", "-C", str(checkout), "status", "--porcelain"], text=True, stderr=subprocess.DEVNULL).strip()
            pin = next(item["pin"]["value"] for item in read_json(root / "registry/upstreams.json")["providers"] if item.get("id") == provider)
            if actual != pin or dirty:
                errors.append(f"deployment package cache integrity failed for {provider}")
        except (OSError, subprocess.CalledProcessError, KeyError, StopIteration):
            errors.append(f"deployment package cache integrity failed for {provider}")
    return errors


def doctor(root: Path = ROOT, deployment_root: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    families_data = read_json(root / "registry/families.json")
    commands_data = read_json(root / "registry/commands.json")
    upstreams = read_json(root / "registry/upstreams.json")
    families = {item.get("id"): item for item in families_data.get("families", []) if isinstance(item, dict) and isinstance(item.get("id"), str)}
    commands = commands_data.get("commands")
    providers_list = upstreams.get("providers")
    if families_data.get("schema_version") != 1 or not families:
        raise DoctorError("family registry is incomplete")
    if commands_data.get("schema_version") != 1 or not isinstance(commands, list):
        raise DoctorError("command registry is incomplete")
    if upstreams.get("schema_version") != 1 or not isinstance(providers_list, list):
        raise DoctorError("upstream registry is incomplete")
    providers = {item.get("id"): item for item in providers_list if isinstance(item, dict) and isinstance(item.get("id"), str)}
    if len(providers) != len(providers_list):
        raise DoctorError("upstream provider identifiers are not unique")

    errors: list[str] = []
    aliases: set[str] = set()
    command_ids: set[str] = set()
    for command in commands:
        if not isinstance(command, dict) or not isinstance(command.get("id"), str) or not command["id"]:
            errors.append("command registry has an invalid command identifier")
            continue
        command_id = command["id"]
        if command_id in command_ids:
            errors.append(f"duplicate command {command_id}")
        command_ids.add(command_id)
        runtimes = command.get("runtimes")
        if not isinstance(runtimes, dict) or not all(isinstance(runtimes.get(runtime), str) and runtimes[runtime] for runtime in ("claude", "codex")):
            errors.append(f"command {command_id} lacks Claude/Codex primary parity or a tested fallback")
        for alias in command.get("aliases", []):
            if not isinstance(alias, dict) or not isinstance(alias.get("name"), str) or not alias["name"]:
                errors.append(f"command {command_id} has a malformed alias")
                continue
            name = alias["name"]
            if name in aliases:
                errors.append(f"duplicate alias {name}")
            aliases.add(name)
            if alias.get("kind") in {"legacy", "package-native"} and alias.get("canonical_warning") is not True:
                errors.append(f"stale alias {name} lacks a canonical warning")

    catalog_path = root / "registry/capabilities.json"
    active_count = 0
    if catalog_path.is_file():
        catalog = read_json(catalog_path)
        capabilities = catalog.get("capabilities")
        if not isinstance(capabilities, list):
            errors.append("capability catalog lacks capabilities")
        else:
            for capability in capabilities:
                if not isinstance(capability, dict) or capability.get("lifecycle") != "active":
                    continue
                active_count += 1
                family = capability.get("family", capability.get("domain"))
                role = capability.get("role")
                if not isinstance(family, str) or family == "unclassified" or family not in families:
                    errors.append(f"active capability {capability.get('canonical_name', '<unknown>')} is unclassified")
                elif not isinstance(role, str) or role not in families[family].get("allowed_roles", []):
                    errors.append(f"active capability {capability.get('canonical_name', '<unknown>')} has an invalid family role")
                runtimes = capability.get("runtimes")
                if not isinstance(runtimes, dict) or not runtimes.get("supported") or not runtimes.get("publish_targets"):
                    errors.append(f"active capability {capability.get('canonical_name', '<unknown>')} has no runtime publication")

    errors.extend(package_health(root, providers))
    errors.extend(runtime_health(root, deployment_root.resolve() if deployment_root is not None else None))
    report = {"schema_version": 1, "status": "ok" if not errors else "failed", "source": source_state(root), "summary": {"families": len(families), "commands": len(commands), "active_capabilities": active_count, "providers": len(providers)}, "errors": errors}
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--deployment-root", type=Path, help="Also verify installed runtime targets and deployment-owned package cache.")
    args = parser.parse_args(argv)
    try:
        report = doctor(args.root, args.deployment_root)
    except DoctorError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
