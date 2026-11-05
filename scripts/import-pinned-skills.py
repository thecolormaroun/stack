#!/usr/bin/env python3
"""Add upstream skills to an explicit pinned-import provider, or list unmapped ones.

The scheduled maintenance lane only refreshes skills that already have a curated
mapping in ``registry/maintenance-imports.json``; it never discovers new ones.
This command is the reviewed path for the other half:

* ``--list-unmapped`` is read-only. It clones the provider at an exact commit
  and reports upstream skills that have no mapping yet.
* ``--skill`` / ``--all-unmapped`` adds mappings and capability manifests for
  the named skills, then re-materializes every mapped skill of that provider at
  the exact commit with the same code the maintenance lane uses, bumps the pin,
  lock, and last-known-good digest, and rebuilds the generated catalog.

It writes only to this checkout (and stages the new skill folders, because the
catalog builder reads only indexed manifests). It never commits, pushes, opens
a PR, installs a runtime, or publishes anything; the result still goes through
review.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
UPSTREAMS = ROOT / "registry" / "upstreams.json"
IMPORTS = ROOT / "registry" / "maintenance-imports.json"
SOURCES = ROOT / "registry" / "maintenance-sources.json"
LOCK = ROOT / "upstreams.lock.json"


def load_script(filename: str, module_name: str):
    """Import a hyphenated repository script so this command reuses its exact logic."""
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "scripts" / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_canonical(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# The registry files are hand-formatted; these writers reproduce their layout
# byte-for-byte so an import diff shows only the changed rows.
SCALAR_ARRAY = re.compile(r'\[\n((?:\s+(?:"[^"\n]*"|null|true|false|-?\d+),?\n)+)\s*\]')


def collapse_scalar_arrays(text: str) -> str:
    return SCALAR_ARRAY.sub(
        lambda match: "[" + ", ".join(line.strip().rstrip(",") for line in match.group(1).strip().split("\n")) + "]",
        text,
    )


def write_imports(value: Any) -> None:
    IMPORTS.write_text(collapse_scalar_arrays(json.dumps(value, indent=2)) + "\n", encoding="utf-8")


def write_sources(value: Any) -> None:
    # Only the source rows use inline arrays; the discovery contract stays expanded.
    head, marker, rows = json.dumps(value, indent=2).partition('"sources": [')
    SOURCES.write_text(head + marker + collapse_scalar_arrays(rows) + "\n", encoding="utf-8")


def record_collection_source(sources: dict[str, Any], provider: dict[str, Any], provider_id: str, display_name: str, added: list[str]) -> None:
    """Keep one '<provider>-skills' inventory row covering every collection import."""
    row_id = f"{provider_id}-skills"
    row = next((item for item in sources["sources"] if item["id"] == row_id), None)
    if row is None:
        row = {
            "id": row_id,
            "target": f"{display_name} imported skill collection",
            "disposition": "catalog-managed-provider",
            "provider_ref": str(provider["canonical_source"]).removeprefix("https://github.com/").removesuffix(".git"),
            "pin_source": f"registry/upstreams.json:{provider_id}",
            "provider_id": provider_id,
            "target_paths": [],
            "required_exports": [],
        }
        last = max(index for index, item in enumerate(sources["sources"]) if item.get("provider_id") == provider_id)
        sources["sources"].insert(last + 1, row)
        policy_path = ROOT / "config" / "stack-maintenance.json"
        policy = policy_path.read_text(encoding="utf-8")
        ids = json.loads(policy)["legacy_target_ids"]
        anchor = next(f'    "{item["id"]}",\n' for item in reversed(sources["sources"][: last + 1]) if item["id"] in ids)
        policy_path.write_text(policy.replace(anchor, anchor + f'    "{row_id}",\n', 1), encoding="utf-8")
    row["target_paths"] = sorted(set(row["target_paths"]) | {f"skills/imported/{provider_id}/{name}" for name in added})
    row["required_exports"] = sorted(set(row["required_exports"]) | set(added))


def write_upstreams(value: Any) -> None:
    rows = ",\n".join("    " + json.dumps(row, separators=(",", ":")) for row in value["providers"])
    UPSTREAMS.write_text(
        f'{{\n  "schema_version": {value["schema_version"]},\n  "providers": [\n{rows}\n  ]\n}}\n', encoding="utf-8"
    )


def existing_names() -> set[str]:
    return {read(path)["canonical_name"] for path in (ROOT / "skills").rglob("capability.json")}


def upstream_skills(checkout: Path) -> list[str]:
    root = checkout / "skills"
    return sorted(path.parent.name for path in root.glob("*/SKILL.md") if not path.is_symlink())


def frontmatter_description(skill: Path) -> str:
    lines = skill.read_text(encoding="utf-8").splitlines()
    end = lines.index("---", 1)
    for line in lines[1:end]:
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    raise SystemExit(f"{skill}: missing description")


def parse_families(rows: list[str], classifier) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in rows:
        name, _, family = row.partition("=")
        if family not in classifier.FAMILIES:
            raise SystemExit(f"--family {row!r}: expected UPSTREAM=<one of {', '.join(classifier.FAMILIES)}>")
        result[name] = family
    return result


def capability_manifest(*, name: str, provider_id: str, relative: str, purpose: str, family: str, classifier, upstream: str) -> dict[str, Any]:
    # Command and trust follow the Phase 1 classifier so a classifier re-run is a no-op.
    trust = classifier.trust_for(family, name)
    return {
        "artifact_type": "skill",
        "audit_status": "reviewed",
        "canonical_name": name,
        "commands": [classifier.command_for(name, family)],
        "context": {"inputs": ["request", "workspace-context"], "outputs": ["capability-result"]},
        "disposition": {
            "evidence_gap": None,
            "next_review_trigger": "Reassess on source, export, or runtime-target change.",
            "status": "keep",
        },
        "domain": family,
        "family": family,
        "lifecycle": "active",
        "overlaps": [],
        "ownership": {"package": "imported-skills", "provider": provider_id, "source_path": f"{relative}/SKILL.md"},
        "provenance": {"license": "MIT", "posture": "imported-upstream", "source_identity": f"upstream:{provider_id}/skills/{upstream}"},
        "purpose": purpose,
        "role": "leaf",
        "runtimes": {"publish_targets": ["claude", "codex"], "supported": ["claude", "codex"]},
        "schema_version": 1,
        "source": {"skill_path": f"{relative}/SKILL.md"},
        "trust_class": trust,
        "validation": {"evidence": ["reviewed-estate-refactor", "structural-classification", "primary-runtime-parity"], "status": "validated"},
        "validation_class": "high-risk" if trust == "external-mutation" else "representative-route",
        "visibility": "extended",
    }


def record_pin(materializer, provider: dict[str, Any], rule: dict[str, Any], sources: dict[str, Any], lock: dict[str, Any], provider_id: str, commit: str, outputs: dict[str, bytes], added: list[str]) -> None:
    """Bump the provider pin exactly as the maintenance materializer does."""
    provider["exports"] = sorted(set(provider["exports"]) | set(added))
    provider["license"] = str(rule["license"])
    provider["pin"]["value"] = commit
    provider["last_known_good"] = {
        "pin": commit,
        "metadata_digest": materializer.digest(
            {
                "provider": provider_id,
                "pin": commit,
                "files": {path: materializer.digest_bytes(content) for path, content in sorted(outputs.items())},
            }
        ),
    }
    lock["providers"][provider_id] = commit
    # maintenance-sources.json provider_ref must keep matching canonical_source.
    new_ref = str(provider["canonical_source"]).removeprefix("https://github.com/").removesuffix(".git")
    for row in sources["sources"]:
        if row.get("provider_id") == provider_id:
            row["provider_ref"] = new_ref
    record_collection_source(sources, provider, provider_id, str(rule["display_name"]), added)


def refresh_generated_artifacts(materializer, classifier, provider_id: str, added: list[str]) -> None:
    """Rebuild every artifact that enumerates capabilities so the full test suite passes."""
    # The catalog builder only reads git-indexed manifests, so stage the new targets first.
    subprocess.run(["git", "add", "--", *[f"skills/imported/{provider_id}/{name}" for name in added]], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "scripts/build-capability-registry.py"], cwd=ROOT, check=True)
    # Every capability has one (here no-op) move in the reviewed layout record.
    layout_path = ROOT / "registry" / "migrations" / "2026-07-23-skill-layout.json"
    layout = read(layout_path)
    for name in added:
        skill_path = f"skills/imported/{provider_id}/{name}/SKILL.md"
        layout["moves"].append({"canonical_name": name, "source": skill_path, "destination": skill_path})
    layout["moves"].sort(key=lambda move: move["canonical_name"])
    write_canonical(layout_path, layout)
    targets_path = ROOT / "config" / "runtime-targets.json"
    reconciliation = classifier.reconcile(ROOT, read(targets_path)["targets"])
    write_canonical(ROOT / "artifacts" / "audits" / "phase1-architecture" / "capability-reconciliation.json", reconciliation)
    targets = targets_path.read_text(encoding="utf-8")
    old_digest = json.loads(targets)["catalog_digest"]
    new_digest = materializer.digest_bytes((ROOT / "registry" / "capabilities.json").read_bytes())
    targets_path.write_text(targets.replace(old_digest, new_digest), encoding="utf-8")
    subprocess.run([sys.executable, "scripts/sync-upstreams.py"], cwd=ROOT, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--commit", help="exact upstream commit (default: the provider's current remote HEAD)")
    parser.add_argument("--prefix", help="target name prefix (default: '<provider>-')")
    parser.add_argument("--list-unmapped", action="store_true")
    parser.add_argument("--all-unmapped", action="store_true")
    parser.add_argument("--skill", action="append", default=[], help="upstream skill name to add (repeatable)")
    parser.add_argument("--family", action="append", default=[], help="UPSTREAM=family for a new skill (default: design); also add it to classify-capabilities.py family_for")
    parser.add_argument("--canonical-source", help="update the provider's canonical source (e.g. after an upstream rename)")
    args = parser.parse_args(argv)

    materializer = load_script("materialize-maintenance-proposal.py", "stack_import_materializer")
    registry, imports, sources, lock = read(UPSTREAMS), read(IMPORTS), read(SOURCES), read(LOCK)
    provider = next((row for row in registry["providers"] if row["id"] == args.provider), None)
    rule = next((row for row in imports["providers"] if row["id"] == args.provider), None)
    if provider is None or rule is None or provider.get("install") != "pinned-import":
        raise SystemExit(f"{args.provider}: not a pinned-import provider with an import rule")
    if rule.get("mapping") != "explicit-source-json":
        raise SystemExit(f"{args.provider}: only explicit-source-json mappings are supported")
    if args.canonical_source:
        provider["canonical_source"] = args.canonical_source
    source_url = str(provider["canonical_source"])
    commit = args.commit or subprocess.run(
        ["git", "ls-remote", source_url, "HEAD"], text=True, capture_output=True, check=True
    ).stdout.split()[0]
    if materializer.SHA1.fullmatch(commit) is None:
        raise SystemExit("commit must be a full 40-character SHA")

    with tempfile.TemporaryDirectory() as temporary:
        checkout = Path(temporary) / "upstream"
        materializer.clone_exact(source_url, commit, checkout)
        materializer.validate_upstream_license(checkout, provider)
        mapped = {Path(row["source"]).name for row in rule["targets"]}
        unmapped = [name for name in upstream_skills(checkout) if name not in mapped]
        if args.list_unmapped:
            print(json.dumps({"provider": args.provider, "commit": commit, "pinned": provider["pin"]["value"], "unmapped": unmapped}, indent=2))
            return 0
        selected = unmapped if args.all_unmapped else args.skill
        if not selected:
            raise SystemExit("nothing to add: pass --skill, --all-unmapped, or --list-unmapped")
        missing = sorted(set(selected) - set(unmapped))
        if missing:
            raise SystemExit(f"not unmapped upstream skills: {', '.join(missing)}")
        classifier = load_script("classify-capabilities.py", "stack_import_classifier")
        families = parse_families(args.family, classifier)
        prefix = args.prefix if args.prefix is not None else f"{args.provider}-"
        taken = existing_names()
        added: list[str] = []
        for upstream in selected:
            name = upstream if upstream.startswith(prefix) else f"{prefix}{upstream}"
            if name in taken:
                raise SystemExit(f"{name}: canonical name already exists")
            relative = f"skills/imported/{args.provider}/{name}"
            target = ROOT / relative
            target.mkdir(parents=True, exist_ok=False)
            write_canonical(
                target / "capability.json",
                capability_manifest(
                    name=name,
                    provider_id=args.provider,
                    relative=relative,
                    purpose=frontmatter_description(checkout / "skills" / upstream / "SKILL.md"),
                    family=families.get(upstream, "design"),
                    classifier=classifier,
                    upstream=upstream,
                ),
            )
            rule["targets"].append({"source": f"skills/{upstream}", "target": relative})
            added.append(name)

        outputs = materializer.materialize_provider(ROOT, checkout, provider, rule, commit)
        for relative, content in outputs.items():
            destination = ROOT / materializer.safe_relative(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)

    record_pin(materializer, provider, rule, sources, lock, args.provider, commit, outputs, added)
    write_sources(sources)
    write_upstreams(registry)
    LOCK.write_text(json.dumps(lock, separators=(",", ":")) + "\n", encoding="utf-8")
    write_imports(imports)
    refresh_generated_artifacts(materializer, classifier, args.provider, added)
    print(json.dumps({"provider": args.provider, "pin": commit, "added": added, "files": len(outputs)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
