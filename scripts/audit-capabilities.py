#!/usr/bin/env python3
"""Read-only, deterministic inventory of Stack capability artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from string import Template
from typing import Any


ARTIFACT_REFERENCE_DIRS = {"references", "instructions", "examples", "eval"}
METADATA_SUFFIXES = {".json", ".yaml", ".yml", ".toml"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def digest(value: Any) -> str:
    payload = value if isinstance(value, str) else canonical_json(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def tracked_paths(root: Path) -> tuple[list[str], str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            check=True, capture_output=True, text=False,
        )
        paths = sorted(item.decode("utf-8") for item in result.stdout.split(b"\0") if item)
        # `git ls-files --cached` retains paths deleted in the working tree.
        # A migration audit must describe the tree that would be committed, not
        # resurrect removed capabilities as empty tracked records.
        return [path for path in paths if (root / path).is_file()], "git"
    except (OSError, subprocess.CalledProcessError):
        return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()), "tree-scan"


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def identity_text(path: str, content: str) -> str:
    """Return stable capability identity text, excluding incidental body rules."""
    header = ""
    if content.startswith("---\n"):
        end = content.find("\n---", 4)
        if end != -1:
            header = content[4:end]
    if not header:
        header = "\n".join(content.splitlines()[:3])
    return (path + "\n" + header).lower()


def scope_identity_text(path: str, content: str) -> str:
    """Use only stable names for scope classification, never use-case examples."""
    identity = identity_text(path, content)
    name_lines = [line for line in identity.splitlines() if line.strip().startswith("name:")]
    normalized = path.lower() + "\n" + "\n".join(name_lines)
    return normalized.replace("-", " ").replace("_", " ")


def classify(path: str, content: str, policy: dict[str, Any]) -> str:
    parts = Path(path).parts
    name = Path(path).name
    if name == "SKILL.md":
        lower = identity_text(path, content)
        if any(keyword in lower for keyword in policy["router_keywords"]):
            return "router"
        return "callable-skill"
    if any(part in ARTIFACT_REFERENCE_DIRS for part in parts):
        return "reference"
    if name in {"source.json", "source.md"}:
        return "provenance"
    if Path(path).suffix.lower() in METADATA_SUFFIXES:
        return "metadata"
    return "supporting-artifact"


def collection_for(path: str) -> str:
    parts = Path(path).parts
    return "/".join(parts[:2]) if len(parts) >= 2 else path


def evidence_for(path: str, content: str, all_paths: set[str]) -> tuple[list[str], list[str]]:
    collection = collection_for(path)
    prefix = collection + "/"
    collection_paths = [candidate for candidate in all_paths if candidate.startswith(prefix)]
    evidence = ["tracked"]
    gaps: list[str] = []
    if any("source" in Path(candidate).name.lower() for candidate in collection_paths):
        evidence.append("provenance-file")
    else:
        gaps.append("missing-provenance-or-source-pin")
    if any("eval" in Path(candidate).parts or "test" in Path(candidate).name.lower() for candidate in collection_paths):
        evidence.append("validation-material")
    else:
        gaps.append("missing-validation-evidence")
    # Source files often carry license posture; inspect the collection itself without
    # treating an absent declaration as an automatic archive decision.
    if "license" in content.lower() or any("license" in candidate.lower() for candidate in collection_paths):
        evidence.append("license-posture")
    else:
        gaps.append("missing-license-evidence")
    if "agents/openai.yaml" in collection_paths or "metadata:" in content[:2000]:
        evidence.append("runtime-exposure")
    else:
        gaps.append("missing-runtime-evidence")
    if "imported" in content[:3000].lower() and "provenance-file" not in evidence:
        gaps.append("imported-package-missing-source-pin")
    return evidence, gaps


def disposition_for(path: str, content: str, kind: str, policy: dict[str, Any], overlap_index: dict[str, list[str]]) -> dict[str, str]:
    lower = identity_text(path, content)
    if path in overlap_index:
        return {"proposed_disposition": "merge", "reason": "policy overlap cluster: " + ", ".join(overlap_index[path]), "destination": "reviewed canonical capability"}
    scope_lower = scope_identity_text(path, content)
    if any(keyword in scope_lower for keyword in policy["out_of_scope_keywords"]):
        return {"proposed_disposition": "move", "reason": "useful but outside design/build identity keyword match", "destination": policy["out_of_scope_destination"]}
    if kind == "reference":
        return {"proposed_disposition": "demote", "reason": "reference collection is not independently callable", "destination": "reference-pack"}
    if "imported" in lower and ("source" not in lower or "license" not in lower):
        return {"proposed_disposition": "hold", "reason": "imported package needs provenance/license review", "destination": "pending evidence"}
    if kind == "router":
        return {"proposed_disposition": "hold", "reason": "router needs supported design/build workflow review", "destination": "pending evidence"}
    return {"proposed_disposition": "keep", "reason": "tracked callable/supporting capability artifact; policy review still required", "destination": "current collection"}


def capability_records(root: Path, artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Roll artifact evidence up to each callable entrypoint.

    Nested skills own their own subtree. A parent skill owns descendant artifacts
    only when they are not below another callable entrypoint. This keeps the
    complete artifact ledger while making the migration review operate on actual
    capabilities rather than individual reference files.
    """
    by_path = {record["path"]: record for record in artifacts}
    skill_paths = sorted(
        record["path"]
        for record in artifacts
        if record["artifact_type"] in {"callable-skill", "router"}
    )
    skill_dirs = {path: Path(path).parent for path in skill_paths}
    records: list[dict[str, Any]] = []
    for skill_path in skill_paths:
        directory = skill_dirs[skill_path]
        nested_dirs = [
            candidate
            for other, candidate in skill_dirs.items()
            if other != skill_path and directory in candidate.parents
        ]
        owned = []
        for artifact in artifacts:
            artifact_path = Path(artifact["path"])
            if directory not in artifact_path.parents and artifact_path != directory:
                continue
            if any(child == artifact_path.parent or child in artifact_path.parents for child in nested_dirs):
                continue
            owned.append(artifact)

        manifest_path = (directory / "capability.json").as_posix()
        canonical_name = directory.as_posix().removeprefix("skills/").replace("/", "-")
        if manifest_path in by_path:
            try:
                manifest = json.loads((root / manifest_path).read_text(encoding="utf-8"))
                canonical_name = manifest.get("canonical_name", canonical_name)
            except (OSError, json.JSONDecodeError):
                pass

        skill = by_path[skill_path]
        evidence, evidence_locations, evidence_gaps = capability_evidence(
            root,
            owned,
            manifest_path if manifest_path in by_path else None,
        )
        records.append({
            "canonical_name": canonical_name,
            "skill_path": skill_path,
            "manifest_path": manifest_path if manifest_path in by_path else None,
            "collection": collection_for(skill_path),
            "nested": len(Path(skill_path).parts) > 3,
            "artifact_count": len(owned),
            "artifact_paths": sorted(record["path"] for record in owned),
            "evidence": evidence,
            "evidence_locations": evidence_locations,
            "evidence_gaps": evidence_gaps,
            "review_state": "unreviewed",
            "proposed_disposition": skill["proposed_disposition"],
            "reason": skill["reason"],
            "destination": skill["destination"],
        })
    return sorted(records, key=lambda row: (row["canonical_name"], row["skill_path"]))


def capability_evidence(
    root: Path,
    owned: list[dict[str, Any]],
    manifest_path: str | None,
) -> tuple[list[str], dict[str, list[str]], list[str]]:
    """Derive evidence only from files owned by one callable capability."""
    owned_paths = sorted(record["path"] for record in owned)
    locations: dict[str, list[str]] = {}
    manifest: dict[str, Any] = {}
    if manifest_path:
        try:
            loaded = json.loads((root / manifest_path).read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manifest = loaded
        except (OSError, json.JSONDecodeError):
            manifest = {}

    source_files = [
        path
        for path in owned_paths
        if Path(path).name.lower() in {"source.json", "source.md"}
    ]
    provenance = manifest.get("provenance", {}) if isinstance(manifest.get("provenance"), dict) else {}
    posture = provenance.get("posture")
    source_identity = provenance.get("source_identity")
    if source_files or (
        posture == "repository-local"
        and isinstance(source_identity, str)
        and source_identity.startswith("stack:")
    ):
        locations["provenance"] = source_files or [manifest_path] if manifest_path else source_files

    license_value = provenance.get("license")
    license_files = [path for path in owned_paths if "license" in Path(path).name.lower()]
    if license_files or (isinstance(license_value, str) and license_value.lower() not in {"", "unknown", "unreviewed"}):
        locations["license"] = license_files or ([manifest_path] if manifest_path else [])

    validation = manifest.get("validation", {}) if isinstance(manifest.get("validation"), dict) else {}
    validation_files = [
        path
        for path in owned_paths
        if "eval" in Path(path).parts or "test" in Path(path).name.lower()
    ]
    validation_refs = validation.get("evidence") if isinstance(validation.get("evidence"), list) else []
    if validation.get("status") == "validated" and validation_refs:
        locations["validation"] = [str(item) for item in validation_refs]
    elif validation_files:
        locations["validation"] = validation_files

    runtimes = manifest.get("runtimes", {}) if isinstance(manifest.get("runtimes"), dict) else {}
    runtime_files = [path for path in owned_paths if path.endswith("/agents/openai.yaml")]
    runtime_names = [
        str(item)
        for key in ("supported", "publish_targets")
        for item in runtimes.get(key, [])
        if isinstance(item, str)
    ]
    if runtime_files:
        locations["runtime"] = runtime_files
    elif runtime_names and manifest_path:
        locations["runtime"] = [manifest_path]

    gaps = []
    for key, gap in (
        ("provenance", "missing-provenance-or-source-pin"),
        ("license", "missing-license-evidence"),
        ("validation", "missing-validation-evidence"),
        ("runtime", "missing-runtime-evidence"),
    ):
        if not locations.get(key):
            gaps.append(gap)
    return sorted(locations), {key: sorted(value) for key, value in sorted(locations.items())}, gaps


def render_markdown(template: str, report: dict[str, Any]) -> str:
    inventory = report["inventory"]
    calibration_rows = "\n".join(f"- `{row['case']}` -> `{row['expected_disposition']}` — {row['reason']}" for row in report["calibration_sample"])
    proposals = [record for record in report["capabilities"] if record["proposed_disposition"] != "keep"]
    proposal_rows = "\n".join(f"- `{row['canonical_name']}` (`{row['skill_path']}`) -> **{row['proposed_disposition']}** ({row['reason']}); unreviewed" for row in proposals[:report["policy"]["review_packet_cap"]]) or "- No consequential proposals."
    gaps = [(record["canonical_name"], gap) for record in report["capabilities"] for gap in record["evidence_gaps"]]
    gap_rows = "\n".join(f"- `{path}`: {gap}" for path, gap in gaps) or "- None."
    values = {
        "policy_revision": report["policy"]["revision"], "policy_digest": report["policy"]["digest"],
        "artifact_count": inventory["tracked_artifacts"], "discovered_artifact_count": inventory["discovered_artifacts"],
        "coverage_percent": inventory["artifact_coverage_percent"], "callable_count": inventory["callable_entrypoints"],
        "nested_callable_count": inventory["nested_callable_entrypoints"], "collection_count": inventory["collections"],
        "capability_count": inventory["capabilities"],
        "calibration_rows": calibration_rows, "proposal_rows": proposal_rows, "gap_rows": gap_rows,
    }
    return Template(template).safe_substitute(values)


def audit(root: Path, policy_path: Path, template_path: Path) -> tuple[dict[str, Any], str]:
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    paths, discovery_mode = tracked_paths(root)
    roots = tuple(directory.rstrip("/") + "/" for directory in policy["capability_roots"])
    capability_paths = [path for path in paths if path.startswith(roots)]
    all_paths = set(capability_paths)
    overlap_index: dict[str, list[str]] = {}
    for cluster in policy.get("overlap_groups", []):
        existing = [path for path in cluster if path in all_paths]
        for path in existing:
            overlap_index[path] = [other for other in existing if other != path]
    artifacts = []
    for relative in capability_paths:
        content = read_text(root / relative)
        kind = classify(relative, content, policy)
        evidence, gaps = evidence_for(relative, content, all_paths)
        proposal = disposition_for(relative, content, kind, policy, overlap_index)
        artifacts.append({
            "path": relative, "collection": collection_for(relative), "artifact_type": kind,
            "evidence": evidence, "evidence_gaps": sorted(set(gaps)), "review_state": "unreviewed",
            **proposal,
        })
    artifacts.sort(key=lambda row: row["path"])
    callable_paths = [row["path"] for row in artifacts if row["artifact_type"] in {"callable-skill", "router"}]
    nested = [path for path in callable_paths if len(Path(path).parts) > 3]
    collections = sorted({row["collection"] for row in artifacts})
    capabilities = capability_records(root, artifacts)
    report = {
        "schema_version": "capability-estate-audit/v1", "non_mutating": True,
        "human_approval": "not granted", "discovery_mode": discovery_mode,
        "policy": {"revision": policy["revision"], "digest": digest(policy), "review_packet_cap": policy["review_packet_cap"]},
        "calibration_sample": policy["calibration_samples"],
        "inventory": {
            "tracked_artifacts": len(capability_paths), "discovered_artifacts": len(artifacts),
            "artifact_coverage_percent": 100 if len(capability_paths) == len(artifacts) else 0,
            "capabilities": len(capabilities),
            "callable_entrypoints": len(callable_paths), "nested_callable_entrypoints": len(nested),
            "collections": len(collections), "artifact_types": dict(sorted(Counter(row["artifact_type"] for row in artifacts).items())),
        },
        "callable_entrypoints": callable_paths, "nested_callable_entrypoints": nested,
        "capabilities": capabilities,
        "overlap_clusters": [cluster for cluster in policy.get("overlap_groups", []) if all(path in all_paths for path in cluster)],
        "artifacts": artifacts,
    }
    return report, render_markdown(template_path.read_text(encoding="utf-8"), report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--template", type=Path)
    parser.add_argument("--output-dir", type=Path, help="Optional directory for deterministic JSON and Markdown artifacts.")
    args = parser.parse_args()
    root = args.root.resolve()
    repository_root = Path(__file__).resolve().parents[1]
    report, markdown = audit(
        root,
        args.policy or root / "config/audit-policy.json",
        args.template or repository_root / "templates/capability-audit.md",
    )
    if args.output_dir:
        output = args.output_dir.resolve()
        output.mkdir(parents=True, exist_ok=True)
        (output / "capability-audit.json").write_text(canonical_json(report), encoding="utf-8")
        (output / "capability-audit.md").write_text(markdown, encoding="utf-8")
    else:
        print(canonical_json(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
