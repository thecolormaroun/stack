#!/usr/bin/env python3
"""Materialize a Stack maintenance proposal from an exact audit receipt.

The command writes only to an explicit owner-only output directory. It clones
the receipt's exact observed commits, updates only existing curated imports,
and emits a content-addressed proposal manifest for stack-maintenance.py.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
TIMEOUT_SECONDS = 300
SHA1 = re.compile(r"^[a-f0-9]{40}$")
SAFE_PATH = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._/-]+$")
SOURCE_PATH_LINE = re.compile(r"^- Upstream path: `([^`]+)`$", re.MULTILINE)
SOURCE_COMMIT_LINE = re.compile(r"^- Inspected commit: `([a-f0-9]{40})`$", re.MULTILINE)


class ProposalError(ValueError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def compact_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(value: Any) -> str:
    return digest_bytes(compact_json(value))


def validate_upstream_license(checkout: Path, provider: Mapping[str, Any]) -> str:
    """Return license text only when its bytes match the reviewed provider digest."""
    license_path = checkout / "LICENSE"
    expected = provider.get("license_sha256")
    if (
        not isinstance(expected, str)
        or re.fullmatch(r"[a-f0-9]{64}", expected) is None
        or license_path.is_symlink()
        or not license_path.is_file()
    ):
        raise ProposalError("upstream_license_unapproved")
    try:
        license_bytes = license_path.read_bytes()
        license_text = license_bytes.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise ProposalError("upstream_license_unapproved") from error
    if digest_bytes(license_bytes) != expected:
        raise ProposalError("upstream_license_changed")
    return license_text


def assert_no_symlink_components(path: Path, root: Path) -> None:
    """Reject a symlink at the target or any lexical component below root."""
    candidate = Path(os.path.abspath(path))
    boundary = Path(os.path.abspath(root))
    if candidate != boundary and boundary not in candidate.parents:
        raise ProposalError("mapped_skill_invalid")
    current = candidate
    while True:
        if current.is_symlink():
            raise ProposalError("mapped_skill_invalid")
        if current == boundary:
            return
        current = current.parent


def validated_source_files(source_root: Path, checkout_root: Path | None = None) -> list[Path]:
    """Return regular import files only after rejecting every symlink entry."""
    assert_no_symlink_components(source_root, checkout_root or source_root)
    entries = sorted(source_root.rglob("*"))
    if any(path.is_symlink() for path in entries):
        raise ProposalError("mapped_skill_invalid")
    files = [path for path in entries if path.is_file()]
    if not files:
        raise ProposalError("mapped_skill_invalid")
    return files


def read_object(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProposalError(code) from error
    if not isinstance(value, dict):
        raise ProposalError(code)
    return value


def safe_relative(value: str) -> Path:
    if not isinstance(value, str) or not value or SAFE_PATH.fullmatch(value) is None:
        raise ProposalError("import_path_invalid")
    path = Path(value)
    if any(part.startswith(".") for part in path.parts):
        raise ProposalError("import_path_invalid")
    return path


def run(command: list[str], *, cwd: Path, code: str, strip: bool = True) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=TIMEOUT_SECONDS,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ProposalError(code) from error
    if result.returncode:
        raise ProposalError(code)
    return result.stdout.strip() if strip else result.stdout


def ensure_owner_output(path: Path, root: Path) -> None:
    path = path.resolve()
    root = root.resolve()
    if path == root or root in path.parents or path == Path(path.anchor) or path == Path.home().resolve():
        raise ProposalError("output_directory_unsafe")
    if path.is_symlink():
        raise ProposalError("output_directory_unsafe")
    if not path.exists():
        path.mkdir(parents=True, mode=0o700)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ProposalError("output_permissions_unsafe")
    if any(path.iterdir()):
        raise ProposalError("output_directory_not_empty")


def load_observations(receipt_path: Path, *, root: Path) -> tuple[str, str, dict[str, str]]:
    info = receipt_path.stat()
    if receipt_path.is_symlink() or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ProposalError("receipt_permissions_unsafe")
    receipt = read_object(receipt_path, "receipt_invalid")
    if receipt.get("schema_version") != 1 or receipt.get("task_id") != "stack-maintenance":
        raise ProposalError("receipt_identity_invalid")
    source_audit = receipt.get("checks", {}).get("source_audit", {})
    checkout = source_audit.get("checkout", {}) if isinstance(source_audit, Mapping) else {}
    observation = source_audit.get("upstream_observation", {}) if isinstance(source_audit, Mapping) else {}
    base_sha = checkout.get("base_sha") if isinstance(checkout, Mapping) else None
    if not isinstance(base_sha, str) or SHA1.fullmatch(base_sha) is None:
        raise ProposalError("receipt_base_invalid")
    current_base = run(["git", "rev-parse", "--verify", "origin/main^{commit}"], cwd=root, code="origin_main_missing")
    if current_base != base_sha:
        raise ProposalError("receipt_base_changed")
    rows = observation.get("observations") if isinstance(observation, Mapping) else None
    observation_digest = observation.get("digest") if isinstance(observation, Mapping) else None
    if not isinstance(rows, list) or not isinstance(observation_digest, str):
        raise ProposalError("receipt_observation_invalid")
    if digest(rows) != observation_digest:
        raise ProposalError("receipt_observation_digest_mismatch")
    observed: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping) or row.get("status") != "update_available":
            continue
        provider_id, head = row.get("provider_id"), row.get("observed_head")
        if not isinstance(provider_id, str) or not isinstance(head, str) or SHA1.fullmatch(head) is None:
            raise ProposalError("receipt_observation_invalid")
        observed[provider_id] = head
    if not observed:
        raise ProposalError("receipt_has_no_updates")
    return base_sha, observation_digest, observed


def clone_exact(source: str, commit: str, destination: Path) -> None:
    destination.mkdir(mode=0o700)
    run(["git", "init", "-q"], cwd=destination, code="upstream_clone_failed")
    run(["git", "remote", "add", "origin", source], cwd=destination, code="upstream_clone_failed")
    run(["git", "fetch", "--depth=1", "origin", commit], cwd=destination, code="upstream_fetch_failed")
    run(["git", "checkout", "--detach", "-q", "FETCH_HEAD"], cwd=destination, code="upstream_checkout_failed")
    if run(["git", "rev-parse", "HEAD"], cwd=destination, code="upstream_checkout_failed") != commit:
        raise ProposalError("upstream_commit_mismatch")
    if run(["git", "remote", "get-url", "origin"], cwd=destination, code="upstream_origin_missing") != source:
        raise ProposalError("upstream_origin_mismatch")


def split_skill(path: Path) -> tuple[list[str], str, str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ProposalError("upstream_frontmatter_missing")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise ProposalError("upstream_frontmatter_invalid") from error
    frontmatter = lines[1:end]
    name_rows = [index for index, line in enumerate(frontmatter) if line.startswith("name:")]
    if len(name_rows) != 1:
        raise ProposalError("upstream_name_invalid")
    upstream_name = frontmatter[name_rows[0]].split(":", 1)[1].strip().strip("'\"")
    if not upstream_name or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", upstream_name):
        raise ProposalError("upstream_name_invalid")
    return frontmatter, upstream_name, "\n".join(lines[end + 1 :]).strip() + "\n"


def materialized_skill(source: Path, *, target_name: str, display_name: str, commit: str, metadata_path: str) -> bytes:
    frontmatter, upstream_name, body = split_skill(source)
    expected = target_name.split("-", 1)[1] if target_name.startswith(("matt-", "david-")) else target_name
    if upstream_name != expected:
        raise ProposalError("import_name_mismatch")
    name_index = next(index for index, line in enumerate(frontmatter) if line.startswith("name:"))
    frontmatter[name_index] = f"name: {target_name}"
    invocation = f"${target_name}"
    wrapper = "\n".join(
        [
            "---",
            *frontmatter,
            "---",
            "",
            "## Stack Import",
            "",
            f"- Invoke this curated import as `{invocation}`.",
            f"- Upstream name: `{upstream_name}`.",
            f"- Upstream author: {display_name}.",
            f"- Exact upstream commit: `{commit}`.",
            f"- Source metadata and license notice: [{metadata_path}]({metadata_path}).",
            "- New skills, deletions, and license changes remain review-gated.",
            "",
            body,
        ]
    )
    return wrapper.encode("utf-8")


def source_metadata_markdown(*, target_name: str, upstream_name: str, source: str, source_path: str, commit: str, license_text: str, retained_files: list[str], retained_pin: str) -> bytes:
    rows = [
            "# Source Metadata",
            "",
            f"- Imported skill: `${target_name}`",
            f"- Upstream skill name: `{upstream_name}`",
            f"- Upstream repo: {source.removesuffix('.git')}",
            f"- Upstream path: `{source_path}`",
            f"- Inspected commit: `{commit}`",
            "- License: MIT",
    ]
    if retained_files:
        rows.extend(
            [
                f"- Retained removed files: `{', '.join(retained_files)}`",
                f"- Retained files inspected commit: `{retained_pin}`",
            ]
        )
    rows.extend(
        [
            "",
            "## License Notice",
            "",
            "```text",
            license_text.rstrip(),
            "```",
            "",
        ]
    )
    value = "\n".join(rows)
    return value.encode("utf-8")


def source_metadata_json(*, source: str, source_path: str, commit: str, files: list[str], retained_files: list[str], retained_pin: str) -> bytes:
    return canonical_json(
        {
            "source_repo": source.removesuffix(".git"),
            "upstream_skill_path": source_path,
            "license": {"spdx_id": "MIT", "source_file": "LICENSE"},
            "latest_commit": {"sha": commit},
            "files": files,
            "retained_files": [
                {"path": path, "inspected_commit": retained_pin}
                for path in retained_files
            ],
        }
    ).encode("utf-8")


def discover_targets(
    stage: Path,
    rule: Mapping[str, Any],
    expected_pin: str,
    retained_targets: Mapping[tuple[Path, Path], str],
) -> list[tuple[Path, Path, str]]:
    mapping = rule.get("mapping")
    targets: list[tuple[Path, Path, str]] = []
    if mapping == "explicit-source-json":
        rows = rule.get("targets")
        if not isinstance(rows, list):
            raise ProposalError("import_rule_invalid")
        for row in rows:
            if not isinstance(row, Mapping):
                raise ProposalError("import_rule_invalid")
            targets.append((
                safe_relative(str(row.get("source", ""))),
                safe_relative(str(row.get("target", ""))),
                expected_pin,
            ))
        return targets
    if mapping != "existing-source-markdown":
        raise ProposalError("import_rule_invalid")
    target_root = safe_relative(str(rule.get("target_root", "")))
    prefix = rule.get("target_prefix")
    metadata_path = safe_relative(str(rule.get("source_metadata", "")))
    if not isinstance(prefix, str) or not prefix:
        raise ProposalError("import_rule_invalid")
    for target in sorted((stage / target_root).iterdir()):
        if not target.is_dir() or not target.name.startswith(prefix):
            raise ProposalError("import_target_invalid")
        metadata = (target / metadata_path).read_text(encoding="utf-8")
        source_match = SOURCE_PATH_LINE.search(metadata)
        commit_match = SOURCE_COMMIT_LINE.search(metadata)
        if source_match is None or commit_match is None:
            raise ProposalError("import_metadata_invalid")
        source_relative = safe_relative(source_match.group(1))
        target_relative = target.relative_to(stage)
        inspected_pin = commit_match.group(1)
        allowed_pins = {expected_pin}
        retained_pin = retained_targets.get((source_relative, target_relative))
        if retained_pin is not None:
            allowed_pins.add(retained_pin)
        if inspected_pin not in allowed_pins:
            raise ProposalError("import_metadata_invalid")
        targets.append((source_relative, target_relative, inspected_pin))
    if not targets:
        raise ProposalError("import_targets_missing")
    return targets


def materialize_provider(stage: Path, checkout: Path, provider: dict[str, Any], rule: Mapping[str, Any], commit: str) -> dict[str, bytes]:
    if rule.get("license") != "MIT":
        raise ProposalError("upstream_license_unapproved")
    license_text = validate_upstream_license(checkout, provider)
    outputs: dict[str, bytes] = {}
    metadata_relative = safe_relative(str(rule.get("source_metadata", "")))
    retained_target_rows = rule.get("retained_targets", [])
    retained_file_rows = rule.get("retained_files", [])
    if not isinstance(retained_target_rows, list) or not isinstance(retained_file_rows, list):
        raise ProposalError("import_rule_invalid")
    retained_targets = {
        (safe_relative(str(row.get("source", ""))), safe_relative(str(row.get("target", "")))): row.get("pin")
        for row in retained_target_rows
        if isinstance(row, Mapping)
    }
    if len(retained_targets) != len(retained_target_rows) or not all(
        isinstance(pin, str) and SHA1.fullmatch(pin) is not None
        for pin in retained_targets.values()
    ):
        raise ProposalError("import_rule_invalid")
    retained_files = {safe_relative(str(path)) for path in retained_file_rows}
    for source_relative, target_relative, inspected_pin in discover_targets(
        stage,
        rule,
        str(provider["pin"]["value"]),
        retained_targets,
    ):
        source_root = checkout / source_relative
        target_root = stage / target_relative
        if not source_root.is_dir():
            retained_pin = retained_targets.get((source_relative, target_relative))
            if retained_pin is None or inspected_pin != retained_pin or not target_root.is_dir():
                raise ProposalError("mapped_skill_missing")
            continue
        if not target_root.is_dir():
            raise ProposalError("mapped_skill_missing")
        target_name = target_root.name
        source_files = validated_source_files(source_root, checkout)
        generated: set[Path] = {Path("capability.json"), metadata_relative}
        upstream_names: list[str] = []
        for source_file in source_files:
            relative = source_file.relative_to(source_root)
            if relative in {Path("capability.json"), metadata_relative}:
                continue
            destination = target_relative / relative
            generated.add(relative)
            if relative == Path("SKILL.md"):
                content = materialized_skill(
                    source_file,
                    target_name=target_name,
                    display_name=str(rule.get("display_name")),
                    commit=commit,
                    metadata_path=metadata_relative.as_posix(),
                )
                _frontmatter, upstream_name, _body = split_skill(source_file)
                upstream_names.append(upstream_name)
            else:
                content = source_file.read_bytes()
            outputs[destination.as_posix()] = content
        if upstream_names != [source_relative.name]:
            raise ProposalError("import_name_mismatch")
        current = {
            path.relative_to(target_root)
            for path in target_root.rglob("*")
            if path.is_file()
        }
        removed_files = sorted(current - generated)
        if any(path not in retained_files for path in removed_files):
            raise ProposalError("upstream_deletion_requires_approval")
        metadata_target = target_relative / metadata_relative
        upstream_file_names = [path.relative_to(checkout).as_posix() for path in source_files]
        if rule.get("mapping") == "existing-source-markdown":
            outputs[metadata_target.as_posix()] = source_metadata_markdown(
                target_name=target_name,
                upstream_name=source_relative.name,
                source=str(provider["canonical_source"]),
                source_path=source_relative.as_posix(),
                commit=commit,
                license_text=license_text,
                retained_files=[path.as_posix() for path in removed_files],
                retained_pin=str(provider["pin"]["value"]),
            )
        else:
            outputs[metadata_target.as_posix()] = source_metadata_json(
                source=str(provider["canonical_source"]),
                source_path=source_relative.as_posix(),
                commit=commit,
                files=upstream_file_names,
                retained_files=[path.as_posix() for path in removed_files],
                retained_pin=str(provider["pin"]["value"]),
            )
    return outputs


def load_maintenance_module(root: Path):
    path = root / "scripts" / "stack-maintenance.py"
    spec = importlib.util.spec_from_file_location("stack_maintenance_materializer", path)
    if spec is None or spec.loader is None:
        raise ProposalError("maintenance_module_missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def materialize(root: Path, receipt: Path, output: Path) -> Path:
    root, output = root.resolve(), output.resolve()
    ensure_owner_output(output, root)
    base_sha, observation_digest, observed = load_observations(receipt, root=root)
    work = output / ".work"
    upstreams = output / ".upstreams"
    payload = output / "payload"
    work.mkdir(mode=0o700)
    upstreams.mkdir(mode=0o700)
    payload.mkdir(mode=0o700)
    try:
        run(["git", "clone", "--no-local", "--no-checkout", str(root), str(work)], cwd=output, code="proposal_clone_failed")
        run(["git", "checkout", "--detach", "-q", base_sha], cwd=work, code="proposal_checkout_failed")
        rules_document = read_object(work / "registry" / "maintenance-imports.json", "import_rules_invalid")
        if rules_document.get("schema_version") != 1 or not isinstance(rules_document.get("providers"), list):
            raise ProposalError("import_rules_invalid")
        rules = {row.get("id"): row for row in rules_document["providers"] if isinstance(row, Mapping)}
        registry_path = work / "registry" / "upstreams.json"
        lock_path = work / "upstreams.lock.json"
        registry, lock = read_object(registry_path, "registry_invalid"), read_object(lock_path, "lock_invalid")
        providers = {row.get("id"): row for row in registry.get("providers", []) if isinstance(row, dict)}
        if not set(observed).issubset(providers):
            raise ProposalError("observed_provider_unknown")
        provenance: list[dict[str, str]] = []
        all_outputs: dict[str, bytes] = {}
        for provider_id, commit in sorted(observed.items()):
            provider = providers[provider_id]
            if provider.get("pin", {}).get("type") != "git-commit":
                raise ProposalError("observed_provider_invalid")
            old_pin = provider["pin"]["value"]
            if old_pin == commit:
                raise ProposalError("observed_provider_not_changed")
            provider_outputs: dict[str, bytes] = {}
            checkout = upstreams / provider_id
            clone_exact(str(provider["canonical_source"]), commit, checkout)
            if provider.get("install") == "pinned-import":
                rule = rules.get(provider_id)
                if not isinstance(rule, Mapping):
                    raise ProposalError("import_rule_missing")
                provider_outputs = materialize_provider(work, checkout, provider, rule, commit)
                for relative, content in provider_outputs.items():
                    destination = work / safe_relative(relative)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(content)
                provider["license"] = str(rule["license"])
            elif provider.get("install") == "pinned-git-checkout":
                validate_upstream_license(checkout, provider)
                export_paths = provider.get("export_paths")
                if not isinstance(export_paths, Mapping) or not export_paths:
                    raise ProposalError("provider_exports_invalid")
                for export_name, raw_path in sorted(export_paths.items()):
                    relative = safe_relative(str(raw_path))
                    source_file = checkout / relative
                    assert_no_symlink_components(source_file, checkout)
                    if not isinstance(export_name, str) or source_file.is_symlink() or not source_file.is_file():
                        raise ProposalError("provider_export_missing")
                    provider_outputs[f"upstream:{relative.as_posix()}"] = source_file.read_bytes()
            else:
                raise ProposalError("provider_install_invalid")
            provider["pin"]["value"] = commit
            provider["last_known_good"] = {
                "pin": commit,
                "metadata_digest": digest(
                    {
                        "provider": provider_id,
                        "pin": commit,
                        "files": {path: digest_bytes(content) for path, content in sorted(provider_outputs.items())},
                    }
                ),
            }
            lock["providers"][provider_id] = commit
            all_outputs.update(provider_outputs)
            provenance.append(
                {
                    "id": provider_id,
                    "source": str(provider["canonical_source"]),
                    "pin": commit,
                    "license": str(provider["license"]),
                    "content_digest": provider["last_known_good"]["metadata_digest"],
                }
            )
        registry_path.write_text(canonical_json(registry), encoding="utf-8")
        lock_path.write_text(canonical_json(lock), encoding="utf-8")
        run([sys.executable, "scripts/build-capability-registry.py"], cwd=work, code="catalog_generation_failed")
        run([sys.executable, "scripts/sync-upstreams.py"], cwd=work, code="upstream_metadata_failed")
        status = run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=work,
            code="proposal_status_failed",
            strip=False,
        )
        changed_paths: list[str] = []
        for line in status.splitlines():
            if len(line) < 4 or " -> " in line[3:] or "D" in line[:2]:
                raise ProposalError("proposal_deletion_or_rename_requires_approval")
            changed_paths.append(safe_relative(line[3:]).as_posix())
        if not changed_paths:
            raise ProposalError("proposal_has_no_changes")
        maintenance = load_maintenance_module(work)
        policy = maintenance.load_policy(work / "config" / "stack-maintenance.json")
        allowlist = policy.get("diff_allowlist", [])
        if any(not maintenance._allowlisted_path(Path(path), allowlist) for path in changed_paths):
            raise ProposalError("proposal_path_not_allowlisted")
        files: list[dict[str, str]] = []
        for relative in sorted(changed_paths):
            content = (work / relative).read_bytes()
            if maintenance._private_data_in_bytes(content):
                raise ProposalError("proposal_private_data")
            destination = payload / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            files.append({"path": relative, "source": f"payload/{relative}", "sha256": digest_bytes(content)})
        manifest = {
            "schema_version": 2,
            "generator": "scripts/materialize-maintenance-proposal.py",
            "base_sha": base_sha,
            "audit_receipt_sha256": digest_bytes(receipt.read_bytes()),
            "observation_digest": observation_digest,
            "providers": provenance,
            "files": files,
        }
        manifest_path = output / "manifest.json"
        manifest_path.write_text(canonical_json(manifest), encoding="utf-8")
        os.chmod(manifest_path, 0o600)
        return manifest_path
    finally:
        for temporary in (work, upstreams):
            if temporary.exists() and output in temporary.parents:
                shutil.rmtree(temporary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        manifest = materialize(args.root, args.receipt, args.output_dir)
    except (OSError, UnicodeError, ProposalError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps({"status": "materialized", "manifest": str(manifest)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
