#!/usr/bin/env python3
"""Materialize one quarantined capability change in an isolated checkout.

The input packet is a proposal, not an instruction to edit the active Stack
checkout.  A separate authorization artifact must bind the exact packet
digest, base commit, and ``isolated-owner-local-patch-only`` scope.  The
materializer copies the base commit into a disposable local clone, applies
only the declared byte changes, emits a deterministic patch and receipts into
an owner-only directory, and then removes the clone.

There is deliberately no branch, worktree registration, network, PR, install,
runtime, or active-evidence operation in this module.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
HEX64 = re.compile(r"^[a-f0-9]{64}$")
COMMIT = re.compile(r"^[a-f0-9]{40}$")
OPAQUE = re.compile(r"^[a-z][a-z0-9-]{1,32}:[a-f0-9]{16,64}$")
SAFE_PATH = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._/-]+$")

ROLE_TO_CHANGE_KIND = {
    "skill": "skill-update",
    "reference": "reference-update",
    "registry": "registry-metadata",
    "test": "test-support",
    "documentation": "documentation",
}
FORBIDDEN_SEGMENTS = {
    ".git", "vendor", "vendors", "imported", "package", "packages", "plugins",
    "commands", "routing", "runtime", "runtimes",
}
PRIVATE_FIELD_RE = re.compile(
    r"(?:^|[^a-z])(?:api[_ -]?key|access[_ -]?token|secret|password|passwd|credential|"
    r"private[_ -]?key|authorization|bearer|ssn|social[_ -]?security|patient|medical|"
    r"diagnosis|medication|health[_ -]?record|family[_ -]?health|/users/|/home/|"
    r"/private/|/var/folders/|file://)(?:$|[^a-z])",
    re.IGNORECASE,
)
SHEBANG_RE = re.compile(r"^#!(?:\s*)/", re.MULTILINE)


class MaterializationError(ValueError):
    """The capability change cannot be materialized without weakening a gate."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_json(value: Any) -> str:
    return digest_bytes(canonical_json(value).encode("utf-8"))


def load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MaterializationError(f"{label} is not readable JSON") from error
    if not isinstance(value, dict):
        raise MaterializationError(f"{label} must be a JSON object")
    return value


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _is_commit(value: Any) -> bool:
    return isinstance(value, str) and COMMIT.fullmatch(value) is not None


def _is_opaque(value: Any) -> bool:
    return isinstance(value, str) and OPAQUE.fullmatch(value) is not None


def _stable_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return " ".join(f"{key} {_stable_text(child)}" for key, child in sorted(value.items(), key=lambda pair: str(pair[0])))
    if isinstance(value, (list, tuple, set)):
        return " ".join(_stable_text(item) for item in value)
    return str(value)


def privacy_scan(value: Any) -> list[str]:
    """Return stable field labels, never the sensitive value itself."""

    findings: list[str] = []

    def visit(current: Any, path: str) -> None:
        if isinstance(current, Mapping):
            for key, child in current.items():
                key_text = str(key)
                if PRIVATE_FIELD_RE.search(key_text):
                    findings.append(path + "." + key_text)
                visit(child, path + "." + key_text)
            return
        if isinstance(current, (list, tuple)):
            for index, child in enumerate(current):
                visit(child, f"{path}[{index}]")
            return
        if isinstance(current, str) and PRIVATE_FIELD_RE.search(current):
            findings.append(path)

    visit(value, "$" )
    return sorted(set(findings))


def safe_relative(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise MaterializationError("change path is unsafe")
    if SAFE_PATH.fullmatch(value) is None:
        raise MaterializationError("change path is unsafe")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise MaterializationError("change path is unsafe")
    lowered = [part.lower() for part in path.parts]
    if any(part in FORBIDDEN_SEGMENTS for part in lowered):
        raise MaterializationError("change path targets a forbidden surface")
    if value.startswith((".github/", "registry/commands", "registry/routing-rules", "config/runtime-targets")):
        raise MaterializationError("change path targets a forbidden surface")
    return path


def _under(path: PurePosixPath, parent: PurePosixPath) -> bool:
    return path == parent or parent in path.parents


def _run_git(repository: Path, args: list[str], *, timeout: int = 30, check: bool = True) -> str:
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "LC_ALL": "C",
    }
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository), *args],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MaterializationError("isolated git operation failed") from error
    if check and completed.returncode != 0:
        raise MaterializationError("isolated git operation failed")
    return completed.stdout


def _assert_repository(repository: Path) -> Path:
    resolved = repository.expanduser().resolve(strict=False)
    if not resolved.is_dir() or resolved.is_symlink():
        raise MaterializationError("active Stack checkout is unavailable")
    try:
        root = Path(_run_git(resolved, ["rev-parse", "--show-toplevel"]).strip()).resolve()
    except MaterializationError:
        raise MaterializationError("active Stack checkout is not a git repository")
    if root != resolved:
        raise MaterializationError("repository path is not the checkout root")
    return resolved


def _git_head(repository: Path) -> str:
    head = _run_git(repository, ["rev-parse", "--verify", "HEAD"]).strip()
    if not _is_commit(head):
        raise MaterializationError("active checkout HEAD is not an immutable commit")
    return head


def _status_digest(repository: Path) -> str:
    status = _run_git(repository, ["status", "--porcelain=v1", "--untracked-files=all"], check=True)
    return digest_bytes(status.encode("utf-8"))


def _path_digest(repository: Path, relative: PurePosixPath) -> str | None:
    path = repository.joinpath(*relative.parts)
    if path.is_symlink():
        raise MaterializationError("declared path contains a symlink")
    if not path.exists():
        return None
    if not path.is_file():
        raise MaterializationError("declared path is not a regular file")
    return digest_bytes(path.read_bytes())


def _path_mode(repository: Path, relative: PurePosixPath) -> int | None:
    path = repository.joinpath(*relative.parts)
    if path.is_symlink():
        raise MaterializationError("declared path contains a symlink")
    if not path.exists():
        return None
    return stat.S_IMODE(path.stat().st_mode)


def _assert_no_symlink_components(repository: Path, relative: PurePosixPath) -> None:
    current = repository
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise MaterializationError("declared path contains a symlink")


def _validate_target(repository: Path, target: Mapping[str, Any]) -> tuple[PurePosixPath, PurePosixPath]:
    required = {"canonical_name", "capability_path", "provider", "package", "upstream_pin"}
    if set(target) != required:
        raise MaterializationError("target has unsupported or missing fields")
    if not isinstance(target.get("canonical_name"), str) or re.fullmatch(r"[a-z0-9][a-z0-9-]*", target["canonical_name"]) is None:
        raise MaterializationError("target capability name is invalid")
    if target.get("provider") != "stack" or target.get("package") != "stack" or target.get("upstream_pin") is not None:
        raise MaterializationError("provider-owned or imported target is not eligible")
    capability_path = safe_relative(target.get("capability_path"))
    if len(capability_path.parts) < 3 or capability_path.parts[0] != "skills" or capability_path.name != "SKILL.md":
        raise MaterializationError("target must be an existing Stack skill capability")
    _assert_no_symlink_components(repository, capability_path)
    absolute = repository.joinpath(*capability_path.parts)
    if not absolute.is_file() or absolute.is_symlink():
        raise MaterializationError("target capability does not exist")
    capability_root = PurePosixPath(*capability_path.parts[:-1])
    if "imported" in {part.lower() for part in capability_root.parts}:
        raise MaterializationError("provider-owned or imported target is not eligible")

    # The registry is authoritative when present.  A sibling capability.json
    # is accepted for isolated fixture repositories that intentionally omit the
    # generated registry, but it must still identify a Stack-owned capability.
    registry = repository / "registry" / "capabilities.json"
    rows: list[Mapping[str, Any]] = []
    registry_present = registry.exists()
    if registry.is_file() and not registry.is_symlink():
        try:
            document = json.loads(registry.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise MaterializationError("capability registry is unreadable") from error
        if not isinstance(document, Mapping) or not isinstance(document.get("capabilities"), list):
            raise MaterializationError("capability registry has an unsupported shape")
        rows = [row for row in document["capabilities"] if isinstance(row, Mapping)]
    elif registry_present:
        raise MaterializationError("capability registry is not a regular file")
    matches = [row for row in rows if row.get("canonical_name") == target.get("canonical_name")]
    if registry_present and not matches:
        raise MaterializationError("target is not an existing registered capability")
    if matches:
        row = matches[0]
        ownership = row.get("ownership") if isinstance(row.get("ownership"), Mapping) else {}
        source = row.get("source") if isinstance(row.get("source"), Mapping) else {}
        provider = ownership.get("provider", row.get("provider"))
        package = ownership.get("package", row.get("package"))
        paths = {ownership.get("source_path"), source.get("skill_path")}
        if provider != "stack" or package != "stack":
            raise MaterializationError("target is provider-owned or imported")
        if paths and capability_path.as_posix() not in paths:
            raise MaterializationError("target capability path does not match registry")
    else:
        sibling = absolute.parent / "capability.json"
        if sibling.is_file() and not sibling.is_symlink():
            try:
                manifest = json.loads(sibling.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise MaterializationError("target capability manifest is unreadable") from error
            ownership = manifest.get("ownership") if isinstance(manifest, Mapping) and isinstance(manifest.get("ownership"), Mapping) else {}
            provider = ownership.get("provider", manifest.get("provider") if isinstance(manifest, Mapping) else None)
            package = ownership.get("package", manifest.get("package") if isinstance(manifest, Mapping) else None)
            name = manifest.get("canonical_name") if isinstance(manifest, Mapping) else None
            if name not in {None, target.get("canonical_name")} or provider not in {None, "stack"} or package not in {None, "stack"}:
                raise MaterializationError("target is provider-owned or imported")
        elif rows:
            raise MaterializationError("target capability metadata is missing")
    return capability_path, capability_root


def _automatic_weekly_path(path: PurePosixPath) -> bool:
    if len(path.parts) >= 3 and path.parts[0] == "skills" and path.name == "SKILL.md":
        return True
    if path.parts and path.parts[0] == "skills" and "references" in path.parts and path.suffix == ".md":
        reference_index = path.parts.index("references")
        return reference_index >= 2 and reference_index < len(path.parts) - 1
    return False


def _validate_packet(
    packet: Mapping[str, Any],
    repository: Path,
    policy: Mapping[str, Any],
    *,
    automatic_weekly: bool = False,
) -> tuple[PurePosixPath, PurePosixPath, list[dict[str, Any]]]:
    expected_top_level = {
        "schema_version", "change_id", "state", "approval_state", "base_commit",
        "source_lineage", "target", "rationale", "rollback", "edits", "evaluation",
    }
    if set(packet) != expected_top_level:
        raise MaterializationError("candidate packet has unsupported or missing top-level fields")
    if packet.get("schema_version") != 1 or packet.get("state") != "candidate_quarantined" or packet.get("approval_state") != "candidate_unapproved":
        raise MaterializationError("candidate packet is not quarantined and unapproved")
    if not _is_opaque(packet.get("change_id")):
        raise MaterializationError("candidate change_id is invalid")
    if not _is_commit(packet.get("base_commit")):
        raise MaterializationError("candidate packet base_commit is invalid")
    if packet.get("base_commit") != _git_head(repository):
        raise MaterializationError("candidate packet base_commit does not match active checkout HEAD")
    lineage = packet.get("source_lineage")
    lineage_fields = {"packet_id", "packet_digest", "card_ids", "revision_ids", "evidence_ids", "parent_digests"}
    campaign_fields = {"campaign_run_id", "campaign_receipt_digest", "design_packet_artifact_digest", "retrieval_artifact_digest", "candidate_evaluation_artifact_digest"}
    if not isinstance(lineage, Mapping) or frozenset(lineage) not in {frozenset(lineage_fields), frozenset(lineage_fields | campaign_fields)}:
        raise MaterializationError("source lineage has unsupported or missing fields")
    if not isinstance(lineage, Mapping) or not _is_opaque(lineage.get("packet_id")) or not _is_digest(lineage.get("packet_digest")):
        raise MaterializationError("source lineage is incomplete")
    for key in ("card_ids", "revision_ids", "evidence_ids", "parent_digests"):
        rows = lineage.get(key)
        if not isinstance(rows, list) or not rows or len(rows) != len(set(rows)):
            raise MaterializationError("source lineage is incomplete")
        if key == "parent_digests":
            if not all(_is_digest(row) for row in rows):
                raise MaterializationError("source lineage digest is invalid")
        elif not all(_is_opaque(row) for row in rows):
            raise MaterializationError("source lineage identity is invalid")
    if automatic_weekly:
        if not campaign_fields <= set(lineage) or not isinstance(lineage.get("campaign_run_id"), str) or not lineage["campaign_run_id"]:
            raise MaterializationError("automatic weekly campaign lineage is incomplete")
        if any(not _is_digest(lineage.get(key)) for key in campaign_fields - {"campaign_run_id"}):
            raise MaterializationError("automatic weekly campaign lineage digest is invalid")
    target = packet.get("target")
    if not isinstance(target, Mapping):
        raise MaterializationError("candidate target is missing")
    capability_path, capability_root = _validate_target(repository, target)
    rationale = packet.get("rationale")
    rationale_fields = {"change_kind", "expected_behavior", "overlap_analysis", "license_posture", "privacy_class"}
    if not isinstance(rationale, Mapping) or frozenset(rationale) not in {frozenset(rationale_fields), frozenset(rationale_fields | {"materiality"})}:
        raise MaterializationError("candidate rationale is missing")
    change_kind = rationale.get("change_kind")
    if change_kind not in set(ROLE_TO_CHANGE_KIND.values()):
        raise MaterializationError("candidate change_kind is unsupported")
    expected = rationale.get("expected_behavior")
    if not isinstance(expected, list) or not expected or not all(isinstance(item, str) and item.strip() for item in expected):
        raise MaterializationError("candidate expected_behavior is missing")
    overlap = rationale.get("overlap_analysis")
    if not isinstance(overlap, Mapping) or set(overlap) != {"status", "compared_capabilities", "explanation"} or overlap.get("status") not in {"no_collision", "overlap_resolved", "human_review_required"}:
        raise MaterializationError("candidate overlap analysis is missing")
    if rationale.get("license_posture") != "stack-owned-reviewed-derivative" or rationale.get("privacy_class") != "reviewed-software-derivative":
        raise MaterializationError("candidate provenance or privacy posture is unsafe")
    if automatic_weekly:
        materiality = rationale.get("materiality")
        if not isinstance(materiality, Mapping) or set(materiality) != {"basis", "source_count", "critique_failure_ids", "evaluation_failure_ids"}:
            raise MaterializationError("automatic weekly material evidence is incomplete")
        basis = materiality.get("basis")
        source_count = materiality.get("source_count")
        critique_failures = materiality.get("critique_failure_ids")
        evaluation_failures = materiality.get("evaluation_failure_ids")
        if not isinstance(source_count, int) or isinstance(source_count, bool) or source_count != len(lineage["evidence_ids"]):
            raise MaterializationError("automatic weekly material evidence source count is invalid")
        if not isinstance(critique_failures, list) or not all(_is_opaque(value) for value in critique_failures) or not isinstance(evaluation_failures, list) or not all(_is_opaque(value) for value in evaluation_failures):
            raise MaterializationError("automatic weekly material evidence failure binding is invalid")
        if (
            basis == "two-independent-sources" and source_count >= 2 and not critique_failures and not evaluation_failures
        ) or (
            basis == "source-plus-repeated-critique-failure" and source_count >= 1 and critique_failures and not evaluation_failures
        ) or (
            basis == "source-fixes-hard-evaluation-failure" and source_count >= 1 and evaluation_failures and not critique_failures
        ):
            pass
        else:
            raise MaterializationError("automatic weekly material evidence does not satisfy an approved basis")
    rollback = packet.get("rollback")
    if not isinstance(rollback, Mapping) or set(rollback) != {"base_commit", "path_digests"} or rollback.get("base_commit") != packet.get("base_commit") or not isinstance(rollback.get("path_digests"), Mapping):
        raise MaterializationError("rollback binding is incomplete")
    evaluation = packet.get("evaluation")
    if not isinstance(evaluation, Mapping) or set(evaluation) != {"profile", "development_manifest_digest", "holdout_manifest_digest", "rotating_canary_manifest_digest", "harness_required"} or evaluation.get("profile") != "design-learning-v1" or evaluation.get("harness_required") is not True:
        raise MaterializationError("design evaluation binding is incomplete")
    for key in ("development_manifest_digest", "holdout_manifest_digest", "rotating_canary_manifest_digest"):
        if not _is_digest(evaluation.get(key)):
            raise MaterializationError("design evaluation manifest digest is invalid")

    materialization = policy.get("materialization") if isinstance(policy.get("materialization"), Mapping) else {}
    automatic = policy.get("automatic_weekly_design_promotion") if automatic_weekly else None
    if automatic_weekly:
        if not isinstance(automatic, Mapping) or automatic.get("state") != "active" or automatic.get("authorization_contract") != "weekly-design-auto-promotion-approved-v1":
            raise MaterializationError("automatic weekly design policy is unavailable")
        maximum = automatic.get("maximum_changed_files")
    else:
        maximum = materialization.get("maximum_changed_files", 5)
    if not isinstance(maximum, int) or maximum < 1:
        raise MaterializationError("materialization policy is invalid")
    edits = packet.get("edits")
    if not isinstance(edits, list) or not 1 <= len(edits) <= min(5, maximum):
        raise MaterializationError("candidate must declare between one and five edits")
    allowed_roles = materialization.get("allowed_roles", list(ROLE_TO_CHANGE_KIND))
    if not isinstance(allowed_roles, list) or not set(allowed_roles) <= set(ROLE_TO_CHANGE_KIND):
        raise MaterializationError("materialization role policy is invalid")
    paths: set[str] = set()
    total_bytes = 0
    validated: list[dict[str, Any]] = []
    for edit in edits:
        if not isinstance(edit, Mapping):
            raise MaterializationError("candidate edit is not an object")
        required = {"path", "role", "operation", "before_digest", "after_digest", "content"}
        if set(edit) != required:
            raise MaterializationError("candidate edit has unsupported or missing fields")
        relative = safe_relative(edit.get("path"))
        path_text = relative.as_posix()
        if path_text in paths:
            raise MaterializationError("candidate edits must declare unique paths")
        paths.add(path_text)
        role = edit.get("role")
        if role not in allowed_roles:
            raise MaterializationError("edit role is not allowlisted")
        if automatic_weekly and role not in {"skill", "reference"}:
            raise MaterializationError("automatic weekly edit role is outside the approved contract")
        primary_role = next((candidate_role for candidate_role, candidate_kind in ROLE_TO_CHANGE_KIND.items() if candidate_kind == change_kind), None)
        # A skill/reference change may carry small, explicitly declared
        # registry/test/documentation support edits.  Other change kinds are
        # single-role changes.  This keeps the primary capability mapping
        # mandatory while allowing the U18 mixed primary+support packet shape.
        support_roles = {"registry", "test", "documentation"}
        if role != primary_role and not (change_kind in {"skill-update", "reference-update"} and role in support_roles):
            raise MaterializationError("edit role is inconsistent with change_kind")
        if role in {"skill", "reference"} and not _under(relative, capability_root):
            raise MaterializationError("skill/reference edit escapes the existing capability root")
        if role == "registry" and not path_text.startswith("registry/"):
            raise MaterializationError("registry edit is outside registry/")
        if role == "test" and not path_text.startswith("tests/"):
            raise MaterializationError("test edit is outside tests/")
        if role == "documentation" and not (path_text.startswith("docs/") or _under(relative, capability_root)):
            raise MaterializationError("documentation edit is outside an allowlisted documentation root")
        operation = edit.get("operation")
        if operation not in {"create", "replace"}:
            raise MaterializationError("candidate deletion or rename is not allowed")
        if automatic_weekly and (operation != "replace" or not _automatic_weekly_path(relative)):
            raise MaterializationError("automatic weekly edit path is outside the approved contract")
        content = edit.get("content")
        if not isinstance(content, str) or not content:
            raise MaterializationError("candidate edit content is empty")
        encoded = content.encode("utf-8")
        total_bytes += len(encoded)
        if SHEBANG_RE.search(content):
            raise MaterializationError("executable candidate content is not allowed")
        current_digest = _path_digest(repository, relative)
        current_mode = _path_mode(repository, relative)
        before = edit.get("before_digest")
        if operation == "create":
            if before is not None or current_digest is not None:
                raise MaterializationError("create edit must target an absent path")
        else:
            if not _is_digest(before) or current_digest != before:
                raise MaterializationError("before_digest does not match the active base")
        if not _is_digest(edit.get("after_digest")) or digest_bytes(encoded) != edit.get("after_digest"):
            raise MaterializationError("after_digest does not match declared content")
        if current_mode is not None and current_mode & 0o111:
            raise MaterializationError("executable candidate path is not allowed")
        rollback_digest = rollback["path_digests"].get(path_text)
        if rollback_digest != before:
            raise MaterializationError("rollback path digest does not match edit")
        validated.append({"path": relative, "role": role, "operation": operation, "before_digest": before, "after_digest": edit["after_digest"], "content": content})
    if set(rollback["path_digests"]) != paths:
        raise MaterializationError("rollback path set does not match declared edits")
    if not any(row["role"] == next(role for role, kind in ROLE_TO_CHANGE_KIND.items() if kind == change_kind) for row in validated):
        raise MaterializationError("candidate is missing its primary capability edit")
    policy_total = automatic.get("maximum_total_bytes") if automatic_weekly and isinstance(automatic, Mapping) else materialization.get("maximum_total_bytes", 131072)
    if not isinstance(policy_total, int) or total_bytes > policy_total:
        raise MaterializationError("candidate exceeds materialization byte limit")
    findings = privacy_scan(packet)
    if findings:
        raise MaterializationError("candidate privacy scan failed")
    if overlap.get("status") == "human_review_required":
        raise MaterializationError("candidate overlap analysis requires human review")
    return capability_path, capability_root, validated


def _validate_authorization(
    authorization: Mapping[str, Any],
    packet: Mapping[str, Any],
    *,
    automatic_weekly: bool = False,
) -> None:
    required = {"schema_version", "change_digest", "base_commit", "scope", "decision", "reviewed_by", "reviewed_at"}
    if automatic_weekly:
        required |= {"authorization_contract", "campaign_run_id", "campaign_receipt_digest"}
    if set(authorization) != required or authorization.get("schema_version") != 1:
        raise MaterializationError("materialization authorization has unsupported or missing fields")
    if authorization.get("change_digest") != digest_json(packet):
        raise MaterializationError("materialization authorization does not match the exact packet digest")
    if authorization.get("base_commit") != packet.get("base_commit"):
        raise MaterializationError("materialization authorization does not match base_commit")
    if authorization.get("scope") != "isolated-owner-local-patch-only" or authorization.get("decision") != "approved":
        raise MaterializationError("materialization authorization scope is unsafe")
    if automatic_weekly:
        if authorization.get("authorization_contract") != "weekly-design-auto-promotion-approved-v1":
            raise MaterializationError("automatic weekly authorization contract is invalid")
        if not isinstance(authorization.get("campaign_run_id"), str) or not authorization["campaign_run_id"]:
            raise MaterializationError("automatic weekly authorization campaign is invalid")
        if not _is_digest(authorization.get("campaign_receipt_digest")):
            raise MaterializationError("automatic weekly authorization campaign digest is invalid")
        lineage = packet.get("source_lineage")
        if not isinstance(lineage, Mapping) or lineage.get("campaign_run_id") != authorization.get("campaign_run_id") or lineage.get("campaign_receipt_digest") != authorization.get("campaign_receipt_digest"):
            raise MaterializationError("automatic weekly authorization does not match candidate lineage")
    if not isinstance(authorization.get("reviewed_by"), str) or not authorization["reviewed_by"].strip():
        raise MaterializationError("materialization authorization requires a reviewer")
    try:
        datetime.fromisoformat(str(authorization.get("reviewed_at")).replace("Z", "+00:00"))
    except ValueError as error:
        raise MaterializationError("materialization authorization requires an ISO timestamp") from error
    privacy_subject = dict(authorization)
    privacy_subject.pop("authorization_contract", None)
    if privacy_scan(privacy_subject):
        raise MaterializationError("materialization authorization privacy scan failed")


def _owner_output_dir(path: Path, repository: Path) -> Path:
    lexical = path.expanduser()
    if not lexical.is_absolute():
        lexical = Path.cwd() / lexical
    lexical = Path(os.path.abspath(lexical))
    current = Path(lexical.anchor)
    for component in lexical.parts[1:]:
        current = current / component
        # macOS exposes /tmp and /var through stable system symlinks.  They
        # are not user-controlled output parents; every other symlink in the
        # requested path is rejected before resolution.
        if current.is_symlink() and current not in {Path("/tmp"), Path("/var"), Path("/private")}:
            raise MaterializationError("owner-local output has a symlink parent")
    resolved = lexical.resolve(strict=False)
    if resolved == repository or repository in resolved.parents or resolved == Path.home().resolve():
        raise MaterializationError("owner-local output must be outside the active checkout")
    if resolved.is_symlink():
        raise MaterializationError("owner-local output may not be a symlink")
    try:
        if not resolved.exists():
            resolved.mkdir(parents=True, mode=0o700)
        info = resolved.stat()
    except OSError as error:
        raise MaterializationError("owner-local output is unavailable") from error
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise MaterializationError("owner-local output must be a 0700 directory")
    return resolved


def _write_idempotent(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise MaterializationError("owner-local receipt path may not be a symlink")
    if path.exists():
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise MaterializationError("owner-local receipt permissions are unsafe")
        if path.read_bytes() != data:
            raise MaterializationError("existing owner-local receipt differs from deterministic rerun")
        return
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            offset = 0
            while offset < len(data):
                offset += os.write(descriptor, data[offset:])
            os.fsync(descriptor)
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        try:
            os.link(temporary, path)
        except FileExistsError:
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or path.read_bytes() != data:
                raise MaterializationError("existing owner-local receipt differs from deterministic rerun")
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    except OSError as error:
        raise MaterializationError("unable to create owner-local receipt") from error


def _clone_exact(repository: Path, base_commit: str, destination: Path) -> Path:
    clone = destination / "checkout"
    try:
        subprocess.run(
            ["git", "clone", "--no-local", "--no-hardlinks", "--no-checkout", str(repository), str(clone)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=True,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"), "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"},
        )
        _run_git(clone, ["checkout", "--detach", "--quiet", base_commit])
        if _git_head(clone) != base_commit:
            raise MaterializationError("isolated checkout base commit mismatch")
        _run_git(clone, ["remote", "remove", "origin"], check=False)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise MaterializationError("unable to create disposable isolated checkout") from error
    return clone


def _apply_edits(checkout: Path, edits: list[dict[str, Any]]) -> None:
    for edit in edits:
        relative = edit["path"]
        _assert_no_symlink_components(checkout, relative)
        destination = checkout.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.is_symlink():
            raise MaterializationError("isolated destination is a symlink")
        if edit["operation"] == "replace" and digest_bytes(destination.read_bytes()) != edit["before_digest"]:
            raise MaterializationError("isolated before_digest changed")
        if edit["operation"] == "create" and destination.exists():
            raise MaterializationError("isolated create destination already exists")
        destination.write_bytes(edit["content"].encode("utf-8"))
        os.chmod(destination, 0o600)
        if destination.stat().st_mode & 0o111:
            raise MaterializationError("isolated candidate path became executable")
    _run_git(checkout, ["add", "--", *[edit["path"].as_posix() for edit in edits]])


def _render_review_markdown(packet: Mapping[str, Any], receipt: Mapping[str, Any]) -> str:
    target = packet["target"]
    rationale = packet["rationale"]
    evaluation = packet["evaluation"]
    evidence = ", ".join(packet["source_lineage"]["evidence_ids"])
    behavior = "\n".join(f"- {item}" for item in rationale["expected_behavior"])
    overlap = rationale["overlap_analysis"]
    scope = "\n".join(f"- `{row['path']}` ({row['role']}, {row['operation']})" for row in receipt["edits"])
    return "\n".join(
        [
            "# Capability Change Review", "", f"- Change: `{packet['change_id']}`", "- State: `candidate_quarantined`",
            f"- Target: `{target['canonical_name']}`", f"- Base commit: `{packet['base_commit']}`",
            f"- Patch digest: `{receipt['patch_digest']}`", f"- Evidence: {evidence}", "", "## Expected behavior", "", behavior,
            "", "## Scope and overlap", "", scope, "", f"Overlap status: `{overlap['status']}`.", "",
            overlap.get("explanation", ""), "", "## Evaluation", "", f"- Profile: `{evaluation['profile']}`",
            f"- Development manifest: `{evaluation['development_manifest_digest']}`",
            f"- Holdout manifest: `{evaluation['holdout_manifest_digest']}`",
            f"- Rotating canary manifest: `{evaluation['rotating_canary_manifest_digest']}`",
            "- Result: `prepared-awaiting-human-review`", "", "## Safety boundary", "",
            "This artifact is an owner-local quarantined patch. It does not authorize a branch, pull request, merge, install, runtime publication, active-evidence pointer update, provider spend, or source mutation.",
            "", "## Rollback", "", f"Restore the declared paths from base commit `{packet['base_commit']}`. Publication must retain separate merge, compile, install, discovery, and rollback receipts.", "",
        ]
    )


def materialize_change(
    packet: Mapping[str, Any] | Path | str,
    authorization: Mapping[str, Any] | Path | str,
    repository: Path = ROOT,
    output_dir: Path | None = None,
    policy: Mapping[str, Any] | None = None,
    automatic_weekly: bool = False,
) -> dict[str, Any]:
    """Materialize ``packet`` and return its deterministic receipt."""

    if isinstance(packet, (Path, str)):
        packet = load_object(Path(packet), "candidate packet")
    if isinstance(authorization, (Path, str)):
        authorization = load_object(Path(authorization), "materialization authorization")
    if output_dir is None:
        raise MaterializationError("owner-local output directory is required")
    active = _assert_repository(Path(repository))
    policy_doc: Mapping[str, Any]
    if policy is None:
        try:
            policy_doc = load_object(ROOT / "config" / "capability-activation-policy.json", "capability activation policy")
        except MaterializationError:
            raise
    else:
        policy_doc = policy
    if privacy_scan(packet):
        raise MaterializationError("candidate privacy scan failed")
    _validate_authorization(authorization, packet, automatic_weekly=automatic_weekly)
    _validate_packet(packet, active, policy_doc, automatic_weekly=automatic_weekly)
    output = _owner_output_dir(Path(output_dir), active)
    before_status = _status_digest(active)
    before_head = _git_head(active)
    edit_rows = packet["edits"]
    before_file_digests = {row["path"]: row["before_digest"] for row in edit_rows}
    with tempfile.TemporaryDirectory(prefix="stack-capability-change-") as temporary:
        temporary_root = Path(temporary)
        os.chmod(temporary_root, 0o700)
        checkout = _clone_exact(active, packet["base_commit"], temporary_root)
        _apply_edits(checkout, [
            {**row, "path": safe_relative(row["path"])} for row in edit_rows
        ])
        changed = _run_git(checkout, ["diff", "--cached", "--name-only", "--no-ext-diff"]).splitlines()
        expected_paths = sorted(row["path"] for row in edit_rows)
        if sorted(changed) != expected_paths:
            raise MaterializationError("isolated patch changed an undeclared path")
        patch = _run_git(checkout, ["diff", "--cached", "--binary", "--no-ext-diff", "--no-color"], timeout=60).encode("utf-8")
        if not patch:
            raise MaterializationError("candidate produced an empty patch")
    after_head = _git_head(active)
    after_status = _status_digest(active)
    after_file_digests = {row["path"]: _path_digest(active, safe_relative(row["path"])) for row in edit_rows}
    unchanged = before_head == after_head and before_status == after_status and before_file_digests == after_file_digests
    if not unchanged:
        raise MaterializationError("active checkout changed during isolated materialization")
    patch_digest = digest_bytes(patch)
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "receipt_kind": "capability-change-materialization",
        "status": "prepared",
        "change_digest": digest_json(packet),
        "change_id": packet["change_id"],
        "base_commit": packet["base_commit"],
        "target": packet["target"],
        "edits": [
            {"path": row["path"], "role": row["role"], "operation": row["operation"], "before_digest": row["before_digest"], "after_digest": row["after_digest"]}
            for row in edit_rows
        ],
        "patch_digest": patch_digest,
        "patch_filename": "capability-change.patch",
        "authorization": {
            "change_digest": authorization["change_digest"],
            "base_commit": authorization["base_commit"],
            "scope": authorization["scope"],
            "decision": authorization["decision"],
            **(
                {
                    "authorization_contract": authorization["authorization_contract"],
                    "campaign_run_id": authorization["campaign_run_id"],
                    "campaign_receipt_digest": authorization["campaign_receipt_digest"],
                }
                if automatic_weekly
                else {}
            ),
        },
        "active_checkout": {
            "head_before": before_head,
            "head_after": after_head,
            "status_digest_before": before_status,
            "status_digest_after": after_status,
            "file_digests_before": before_file_digests,
            "file_digests_after": after_file_digests,
            "unchanged": True,
        },
        "isolation": {"disposable_checkout": True, "network": "not_used", "temporary_checkout_cleaned": True},
        "quarantine": {"owner_local": True, "retrieval_truth": False, "future_fixtures": False, "active_evidence": False},
        "activation": {"active_pointer": False, "install": False, "publish": False, "draft_pr": False, "network_action": False},
        "next_gate": "human-review",
    }
    review_receipt = {
        "schema_version": 1,
        "receipt_kind": "capability-change-review",
        "status": "awaiting_human_review",
        "change_digest": receipt["change_digest"],
        "patch_digest": patch_digest,
        "base_commit": packet["base_commit"],
        "scope": "isolated-owner-local-patch-only",
        "decision": "not-yet-reviewed",
        "quarantined": True,
        "active_pointer_advanced": False,
        "install_performed": False,
        "publication_performed": False,
        "draft_pr_created": False,
    }
    _write_idempotent(output / "capability-change.patch", patch)
    _write_idempotent(output / "materialization-receipt.json", canonical_json(receipt).encode("utf-8"))
    _write_idempotent(output / "capability-change-review.json", canonical_json(review_receipt).encode("utf-8"))
    _write_idempotent(output / "capability-change-review.md", _render_review_markdown(packet, receipt).encode("utf-8"))
    return receipt


# Short aliases make the contract convenient for focused unit tests and
# preserve the vocabulary used by the U18 plan.
materialize = materialize_change


def _load_policy(path: Path) -> dict[str, Any]:
    return load_object(path, "capability activation policy")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--authorization", "--review", dest="authorization", type=Path, required=True)
    parser.add_argument("--repository", type=Path, default=ROOT)
    parser.add_argument("--policy", type=Path, default=ROOT / "config" / "capability-activation-policy.json")
    parser.add_argument("--out", type=Path, required=True, help="owner-only output directory")
    parser.add_argument("--automatic-weekly-design", action="store_true", help="enforce the approved weekly skill/reference-only contract")
    args = parser.parse_args(argv)
    try:
        packet = load_object(args.packet, "candidate packet")
        authorization = load_object(args.authorization, "materialization authorization")
        policy = _load_policy(args.policy)
        receipt = materialize_change(
            packet,
            authorization,
            repository=args.repository,
            output_dir=args.out,
            policy=policy,
            automatic_weekly=args.automatic_weekly_design,
        )
    except (MaterializationError, OSError, TypeError, KeyError) as error:
        print(f"capability change materialization failed closed: {error}", file=sys.stderr)
        return 2
    print(canonical_json({"status": receipt["status"], "change_digest": receipt["change_digest"], "output": str(args.out)}), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
