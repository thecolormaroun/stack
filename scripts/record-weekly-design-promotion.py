#!/usr/bin/env python3
"""Validate and persist a private terminal receipt for the weekly design loop.

This recorder does not perform evaluation, GitHub, merge, or runtime actions.
It binds the receipts from those actions into one owner-local, fail-closed
terminal outcome so a scheduled run cannot claim publication without proof.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _configured_runtime_receipts_root() -> Path:
    try:
        config = json.loads((ROOT / "config/weekly-intelligence.json").read_text(encoding="utf-8"))
        raw = config["automatic_promotion"]["runtime_receipts_root"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError("weekly runtime receipt root is not configured") from error
    if raw != "~/.local/state/stack/runtime-receipts":
        raise RuntimeError("weekly runtime receipt root is not the approved owner-local path")
    return Path(os.path.abspath(str(Path(raw).expanduser())))


TRUSTED_RUNTIME_RECEIPTS_ROOT = _configured_runtime_receipts_root()
HEX64 = re.compile(r"^[a-f0-9]{64}$")
COMMIT = re.compile(r"^[a-f0-9]{40}$")
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
OPAQUE = re.compile(r"^[a-z][a-z0-9-]{1,32}:[a-f0-9]{16,64}$")
CONTENT_FILE_RE = re.compile(r"^candidate-content/[a-f0-9]{64}\.utf8$")
AUTHORIZATION_CONTRACT = "weekly-design-auto-promotion-approved-v1"
REQUIRED_GATES = (
    "material-evidence",
    "isolated-materialization",
    "frozen-design-eval",
    "full-repository-tests",
    "fresh-independent-review",
    "pull-request-ci",
    "merge-verification",
    "runtime-publication",
    "rollback-receipt",
)
GATE_STATES = {"passed", "failed", "unavailable", "not_applicable"}
DISPOSITIONS = {"published", "no_action", "rejected_no_queue", "retry_with_alert"}
CANDIDATE_STATES = {"absent", "selected"}
PULL_REQUEST_STATES = {"not_created", "closed", "open", "merged"}
RUNTIME_STATES = {"not_run", "published"}
MAX_PRIVATE_JSON_BYTES = 1024 * 1024
EVIDENCE_KEYS = (
    "candidate_packet",
    "materialization",
    "evaluation",
    "repository_tests",
    "independent_review",
    "pull_request_ci",
    "merge_verification",
    "runtime_publication",
    "rollback_receipt",
)
GATE_EVIDENCE = dict(zip(REQUIRED_GATES, EVIDENCE_KEYS))


class PromotionReceiptError(ValueError):
    """A terminal promotion outcome is incomplete, unsafe, or contradictory."""


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _allowed_system_alias(path: Path) -> bool:
    expected = {
        Path("/tmp"): Path("/private/tmp"),
        Path("/var"): Path("/private/var"),
        Path("/etc"): Path("/private/etc"),
    }.get(path)
    return expected is not None and Path(os.path.realpath(path)) == expected


def _reject_symlink_ancestors(path: Path, *, allow_missing_leaf: bool = False) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current = current / component
        try:
            details = current.lstat()
        except FileNotFoundError:
            if allow_missing_leaf and current == path:
                return
            raise PromotionReceiptError("owner-local path is unavailable") from None
        except OSError as error:
            raise PromotionReceiptError("owner-local path is unavailable") from error
        if stat.S_ISLNK(details.st_mode) and not _allowed_system_alias(current):
            raise PromotionReceiptError("owner-local path must not use a symlink")


def _private_file(
    path: Path,
    label: str,
    *,
    maximum_bytes: int | None = MAX_PRIVATE_JSON_BYTES,
) -> tuple[Path, bytes]:
    lexical = Path(os.path.abspath(str(Path(path).expanduser())))
    _reject_symlink_ancestors(lexical)
    resolved = lexical.resolve(strict=False)
    try:
        resolved.relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise PromotionReceiptError(f"{label} must be owner-local outside the repository")
    try:
        parent = resolved.parent.lstat()
        details = resolved.lstat()
    except OSError as error:
        raise PromotionReceiptError(f"{label} is unavailable") from error
    if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) != 0o600:
        raise PromotionReceiptError(f"{label} must be an owner-only regular file with mode 0600")
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700:
        raise PromotionReceiptError(f"{label} parent must be an owner-only directory with mode 0700")
    if maximum_bytes is not None and details.st_size > maximum_bytes:
        raise PromotionReceiptError(f"{label} exceeds the private JSON size limit")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(resolved, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.getuid()
            or stat.S_IMODE(opened.st_mode) != 0o600
            or (maximum_bytes is not None and opened.st_size > maximum_bytes)
        ):
            raise PromotionReceiptError(f"{label} changed during validation")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            content = handle.read() if maximum_bytes is None else handle.read(maximum_bytes + 1)
    except OSError as error:
        raise PromotionReceiptError(f"{label} is unavailable") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if maximum_bytes is not None and len(content) > maximum_bytes:
        raise PromotionReceiptError(f"{label} exceeds the private JSON size limit")
    return resolved, content


def _object_from_bytes(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PromotionReceiptError(f"{label} must be readable JSON") from error
    if not isinstance(value, dict):
        raise PromotionReceiptError(f"{label} must be a JSON object")
    return value


def _weekly_contract() -> Any:
    path = ROOT / "scripts" / "run-stack-weekly-intelligence.py"
    spec = importlib.util.spec_from_file_location("weekly_design_promotion_contract", path)
    if spec is None or spec.loader is None:
        raise PromotionReceiptError("campaign validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _campaign(path: Path) -> tuple[dict[str, Any], str, Path]:
    resolved, raw = _private_file(path, "campaign receipt")
    value = _object_from_bytes(raw, "campaign receipt")
    try:
        _weekly_contract().validate_receipt(value)
    except Exception as error:
        raise PromotionReceiptError("campaign receipt fails the canonical coordinator contract") from error
    if value.get("terminal_state") not in {"prepared", "no_action"}:
        raise PromotionReceiptError("campaign terminal state is not eligible for automatic promotion")
    return value, _digest_bytes(raw), resolved


def _live_binding(
    path: Path,
    expected_digest: str,
    campaign_path: Path,
    campaign: Mapping[str, Any],
    campaign_digest: str,
) -> tuple[dict[str, Any], str]:
    if HEX64.fullmatch(expected_digest) is None:
        raise PromotionReceiptError("live binding receipt digest is invalid")
    resolved, raw = _private_file(path, "live binding receipt")
    exact_digest = _digest_bytes(raw)
    if exact_digest != expected_digest:
        raise PromotionReceiptError("live binding receipt digest does not match the returned digest")
    value = _object_from_bytes(raw, "live binding receipt")
    required = {
        "schema_version",
        "task_id",
        "campaign_run_id",
        "campaign_receipt_relative_path",
        "campaign_receipt_digest",
        "campaign_terminal_state",
        "campaign_reason_code",
        "receipt_persisted",
    }
    if set(value) != required or value.get("schema_version") != 1 or value.get("task_id") != "stack-weekly-live-binding" or value.get("receipt_persisted") is not True:
        raise PromotionReceiptError("live binding receipt shape is invalid")
    relative = value.get("campaign_receipt_relative_path")
    if not isinstance(relative, str) or relative.startswith("/") or ".." in PurePosixPath(relative).parts:
        raise PromotionReceiptError("live binding campaign path is invalid")
    if resolved.parent.name != "live-receipts" or resolved.parent.parent.name != "live":
        raise PromotionReceiptError("live binding receipt is outside the canonical live state path")
    weekly_root = resolved.parents[2]
    expected_campaign = (weekly_root / relative).resolve(strict=False)
    if expected_campaign != campaign_path:
        raise PromotionReceiptError("campaign receipt path does not match the live binding")
    if (
        value.get("campaign_run_id") != campaign.get("run_id")
        or value.get("campaign_receipt_digest") != campaign_digest
        or value.get("campaign_terminal_state") != campaign.get("terminal_state")
        or value.get("campaign_reason_code") != campaign.get("reason_code")
    ):
        raise PromotionReceiptError("campaign receipt does not match the live binding")
    return value, exact_digest


def _decision(
    value: Mapping[str, Any] | Path | str,
) -> tuple[dict[str, Any], Path | None, str | None]:
    if isinstance(value, (Path, str)):
        resolved, raw = _private_file(Path(value), "promotion decision")
        document = _object_from_bytes(raw, "promotion decision")
        file_digest = _digest_bytes(raw)
    elif isinstance(value, Mapping):
        document = dict(value)
        resolved = None
        file_digest = None
    else:
        raise PromotionReceiptError("promotion decision must be an object")
    expected = {
        "schema_version",
        "authorization_contract",
        "disposition",
        "reason_code",
        "candidate",
        "gates",
        "pull_request",
        "runtime",
        "evidence",
    }
    if set(document) != expected or document.get("schema_version") != 1:
        raise PromotionReceiptError("promotion decision shape is unsupported")
    if document.get("authorization_contract") != AUTHORIZATION_CONTRACT:
        raise PromotionReceiptError("promotion authorization contract is invalid")
    if document.get("disposition") not in DISPOSITIONS:
        raise PromotionReceiptError("promotion disposition is invalid")
    if not isinstance(document.get("reason_code"), str) or SAFE_ID.fullmatch(document["reason_code"]) is None:
        raise PromotionReceiptError("promotion reason code is invalid")
    return document, resolved, file_digest


def _evidence_documents(value: Any) -> tuple[
    dict[str, dict[str, Any] | None],
    dict[str, str | None],
    dict[str, Path | None],
]:
    if not isinstance(value, Mapping) or set(value) != set(EVIDENCE_KEYS):
        raise PromotionReceiptError("promotion evidence set is incomplete")
    documents: dict[str, dict[str, Any] | None] = {}
    digests: dict[str, str | None] = {}
    paths: dict[str, Path | None] = {}
    for name in EVIDENCE_KEYS:
        descriptor = value[name]
        if descriptor is None:
            documents[name] = None
            digests[name] = None
            paths[name] = None
            continue
        if not isinstance(descriptor, Mapping) or set(descriptor) != {"path", "digest"}:
            raise PromotionReceiptError(f"{name} evidence descriptor is invalid")
        expected_digest = descriptor.get("digest")
        if not isinstance(expected_digest, str) or HEX64.fullmatch(expected_digest) is None:
            raise PromotionReceiptError(f"{name} evidence digest is invalid")
        path = descriptor.get("path")
        if not isinstance(path, str) or not path:
            raise PromotionReceiptError(f"{name} evidence path is invalid")
        resolved, raw = _private_file(
            Path(path),
            f"{name} evidence",
            maximum_bytes=None if name == "candidate_packet" else MAX_PRIVATE_JSON_BYTES,
        )
        if _digest_bytes(raw) != expected_digest:
            raise PromotionReceiptError(f"{name} evidence digest does not match the file")
        documents[name] = _object_from_bytes(raw, f"{name} evidence")
        digests[name] = expected_digest
        paths[name] = resolved
    return documents, digests, paths


def _digest_json(value: Any) -> str:
    return _digest_bytes(_canonical(value))


def _automatic_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or value.startswith("/") or ".." in PurePosixPath(value).parts:
        return False
    path = PurePosixPath(value)
    if len(path.parts) >= 3 and path.parts[0] == "skills" and path.name == "SKILL.md":
        return True
    if path.parts and path.parts[0] == "skills" and "references" in path.parts and path.suffix == ".md":
        index = path.parts.index("references")
        return index >= 2 and index < len(path.parts) - 1
    return False


def _candidate_content_size(edit: Mapping[str, Any], candidate_path: Path | None) -> int:
    """Validate one inline or digest-addressed body without buffering a file."""

    content_file = edit.get("content_file")
    if not isinstance(content_file, str) or CONTENT_FILE_RE.fullmatch(content_file) is None:
        raise PromotionReceiptError("candidate packet content_file is invalid")
    if content_file != f"candidate-content/{edit.get('after_digest')}.utf8":
        raise PromotionReceiptError("candidate packet content_file is not digest-addressed")
    if candidate_path is None:
        raise PromotionReceiptError("candidate packet path is required for content_file")
    root = candidate_path.parent.resolve(strict=True)
    source = root / content_file
    expected_parent = root / "candidate-content"
    _reject_symlink_ancestors(source)
    try:
        parent = expected_parent.stat()
        details = source.stat()
    except OSError as error:
        raise PromotionReceiptError("candidate packet content_file is unavailable") from error
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.getuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
        or not stat.S_ISREG(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) != 0o600
    ):
        raise PromotionReceiptError("candidate packet content_file permissions are unsafe")

    digest = hashlib.sha256()
    size = 0
    descriptor = -1
    try:
        descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.getuid()
            or stat.S_IMODE(opened.st_mode) != 0o600
        ):
            raise PromotionReceiptError("candidate packet content_file changed during validation")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            while chunk := handle.read(65536):
                size += len(chunk)
                digest.update(chunk)
    except OSError as error:
        raise PromotionReceiptError("candidate packet content_file is unreadable") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not size or digest.hexdigest() != edit.get("after_digest"):
        raise PromotionReceiptError("candidate packet content_file digest is invalid")
    return size


def _git_base_file(base_commit: str, path: str, repository: Path = ROOT) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), "show", f"{base_commit}:{path}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"), "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PromotionReceiptError("candidate base file cannot be verified") from error
    if result.returncode != 0:
        raise PromotionReceiptError("candidate must replace an existing file in its base commit")
    return result.stdout


def _campaign_artifacts(
    campaign: Mapping[str, Any],
    campaign_path: Path,
) -> dict[str, tuple[dict[str, Any], str]]:
    if campaign_path.parent.name != "receipts":
        raise PromotionReceiptError("campaign receipt is outside the coordinator receipt directory")
    state_root = campaign_path.parent.parent
    records = {
        stage.get("id"): stage
        for stage in campaign.get("stages", [])
        if isinstance(stage, Mapping)
    }
    artifacts: dict[str, tuple[dict[str, Any], str]] = {}
    for stage_id in ("design_packet", "retrieval", "candidate_evaluation"):
        stage = records.get(stage_id)
        if not isinstance(stage, Mapping) or stage.get("status") not in {"completed", "reused"}:
            raise PromotionReceiptError(f"campaign {stage_id} stage is not complete")
        relative = stage.get("artifact_path")
        if not isinstance(relative, str) or relative.startswith("/") or ".." in PurePosixPath(relative).parts:
            raise PromotionReceiptError(f"campaign {stage_id} artifact path is invalid")
        artifact_path = (state_root / relative).resolve(strict=False)
        try:
            artifact_path.relative_to(state_root.resolve(strict=True))
        except (OSError, ValueError) as error:
            raise PromotionReceiptError(f"campaign {stage_id} artifact escapes coordinator state") from error
        _resolved, raw = _private_file(artifact_path, f"campaign {stage_id} artifact")
        artifact_digest = _digest_bytes(raw)
        if artifact_digest != stage.get("output_digest"):
            raise PromotionReceiptError(f"campaign {stage_id} artifact digest is invalid")
        artifacts[stage_id] = (_object_from_bytes(raw, f"campaign {stage_id} artifact"), artifact_digest)
    return artifacts


def _candidate_packet(
    document: Mapping[str, Any],
    campaign: Mapping[str, Any],
    campaign_digest: str,
    campaign_path: Path,
    candidate_path: Path | None = None,
    repository: Path = ROOT,
) -> tuple[str, int, int]:
    if document.get("schema_version") != 1 or not isinstance(document.get("base_commit"), str) or COMMIT.fullmatch(document["base_commit"]) is None:
        raise PromotionReceiptError("candidate packet identity is invalid")
    target = document.get("target")
    if not isinstance(target, Mapping) or target.get("provider") != "stack" or target.get("package") != "stack" or target.get("upstream_pin") is not None:
        raise PromotionReceiptError("candidate packet target is not Stack-owned")
    lineage = document.get("source_lineage")
    rationale = document.get("rationale")
    materiality = rationale.get("materiality") if isinstance(rationale, Mapping) else None
    lineage_fields = {"packet_id", "packet_digest", "card_ids", "revision_ids", "evidence_ids", "parent_digests", "campaign_run_id", "campaign_receipt_digest", "design_packet_artifact_digest", "retrieval_artifact_digest", "candidate_evaluation_artifact_digest"}
    if not isinstance(lineage, Mapping) or set(lineage) != lineage_fields or not isinstance(lineage.get("evidence_ids"), list) or not isinstance(materiality, Mapping) or set(materiality) != {"basis", "source_count", "critique_failure_ids", "evaluation_failure_ids"}:
        raise PromotionReceiptError("candidate packet lacks material evidence binding")
    artifacts = _campaign_artifacts(campaign, campaign_path)
    design, design_digest = artifacts["design_packet"]
    retrieval, retrieval_digest = artifacts["retrieval"]
    _candidate_evaluation, candidate_evaluation_digest = artifacts["candidate_evaluation"]
    if (
        lineage.get("campaign_run_id") != campaign.get("run_id")
        or lineage.get("campaign_receipt_digest") != campaign_digest
        or lineage.get("design_packet_artifact_digest") != design_digest
        or lineage.get("retrieval_artifact_digest") != retrieval_digest
        or lineage.get("candidate_evaluation_artifact_digest") != candidate_evaluation_digest
        or lineage.get("packet_id") != design.get("packet_id")
        or lineage.get("packet_digest") != design.get("packet_digest")
    ):
        raise PromotionReceiptError("candidate packet lineage does not match campaign artifacts")
    evidence_ids = lineage["evidence_ids"]
    source_count = materiality.get("source_count")
    critique_failures = materiality.get("critique_failure_ids")
    evaluation_failures = materiality.get("evaluation_failure_ids")
    if (
        not isinstance(source_count, int)
        or isinstance(source_count, bool)
        or source_count < 1
        or not all(isinstance(value, str) and OPAQUE.fullmatch(value) for value in evidence_ids)
        or len(evidence_ids) != len(set(evidence_ids))
        or not isinstance(critique_failures, list)
        or len(critique_failures) != len(set(critique_failures))
        or not all(isinstance(value, str) and OPAQUE.fullmatch(value) for value in critique_failures)
        or not isinstance(evaluation_failures, list)
        or len(evaluation_failures) != len(set(evaluation_failures))
        or not all(isinstance(value, str) and OPAQUE.fullmatch(value) for value in evaluation_failures)
    ):
        raise PromotionReceiptError("candidate packet material evidence count is invalid")
    cards = design.get("cards")
    changes = design.get("candidate_changes")
    results = retrieval.get("results")
    if not isinstance(cards, list) or not isinstance(changes, list) or not isinstance(results, list):
        raise PromotionReceiptError("campaign artifacts lack candidate lineage records")
    card_ids = set(lineage.get("card_ids", []))
    revision_ids = set(lineage.get("revision_ids", []))
    design_card_ids = {row.get("card_id") for row in cards if isinstance(row, Mapping)}
    design_revision_ids = {row.get("revision_id") for row in cards if isinstance(row, Mapping)}
    retrieval_evidence_ids = {row.get("evidence_id") for row in results if isinstance(row, Mapping)}
    matching_changes = [row for row in changes if isinstance(row, Mapping) and row.get("change_id") == document.get("change_id")]
    if not card_ids or not revision_ids or not set(evidence_ids) or not card_ids <= design_card_ids or not revision_ids <= design_revision_ids or not set(evidence_ids) <= retrieval_evidence_ids or len(matching_changes) != 1:
        raise PromotionReceiptError("candidate lineage IDs are not present in campaign artifacts")
    change = matching_changes[0]
    if change.get("card_id") not in card_ids or change.get("revision_id") not in revision_ids or set(change.get("evidence_ids", [])) != set(evidence_ids):
        raise PromotionReceiptError("candidate change is not exactly bound to campaign evidence")
    selected_card_id = change.get("card_id")
    selected_revision_id = change.get("revision_id")
    evidence_sources: dict[str, set[str]] = {evidence_id: set() for evidence_id in evidence_ids}
    cards_by_id: dict[str, Mapping[str, Any]] = {}
    for card in cards:
        if not isinstance(card, Mapping):
            continue
        card_id = card.get("card_id")
        if isinstance(card_id, str):
            cards_by_id[card_id] = card
        if card_id != selected_card_id or card.get("revision_id") != selected_revision_id:
            continue
        citations = card.get("evidence_citations")
        if not isinstance(citations, list):
            continue
        for citation in citations:
            if not isinstance(citation, Mapping):
                continue
            evidence_id = citation.get("evidence_id")
            source_identity = citation.get("source_identity")
            if evidence_id in evidence_sources and isinstance(source_identity, str) and OPAQUE.fullmatch(source_identity):
                evidence_sources[evidence_id].add(source_identity)
    if any(len(values) != 1 for values in evidence_sources.values()):
        raise PromotionReceiptError("candidate evidence lacks an exact campaign source identity")
    independent_sources = {next(iter(values)) for values in evidence_sources.values()}
    if source_count != len(independent_sources):
        raise PromotionReceiptError("candidate packet material evidence source count is invalid")

    valid_critique_failures: set[str] = set()
    clusters = design.get("clusters")
    if isinstance(clusters, list):
        for cluster in clusters:
            if not isinstance(cluster, Mapping) or not isinstance(cluster.get("cluster_id"), str):
                continue
            cluster_cards = cluster.get("card_ids")
            if (
                not isinstance(cluster_cards, list)
                or not all(isinstance(card_id, str) for card_id in cluster_cards)
                or len(set(cluster_cards)) < 2
                or cluster.get("count") != len(set(cluster_cards))
                or selected_card_id not in cluster_cards
            ):
                continue
            records = [cards_by_id.get(card_id) for card_id in set(cluster_cards)]
            if all(
                isinstance(record, Mapping)
                and isinstance(record.get("anti_pattern_failure_mode"), list)
                and bool(record["anti_pattern_failure_mode"])
                for record in records
            ):
                valid_critique_failures.add(cluster["cluster_id"])
    metrics = _candidate_evaluation.get("metrics")
    hard_failures = metrics.get("hard_gate_failures") if isinstance(metrics, Mapping) else None
    valid_evaluation_failures = {
        failure.get("failure_id")
        for failure in hard_failures
        if isinstance(failure, Mapping)
        and isinstance(failure.get("failure_id"), str)
        and OPAQUE.fullmatch(failure["failure_id"])
    } if isinstance(hard_failures, list) else set()
    if not set(critique_failures) <= valid_critique_failures or not set(evaluation_failures) <= valid_evaluation_failures:
        raise PromotionReceiptError("candidate packet material failure IDs are not present in campaign artifacts")
    basis = materiality.get("basis")
    material = (
        basis == "two-independent-sources" and source_count >= 2 and not critique_failures and not evaluation_failures
    ) or (
        basis == "source-plus-repeated-critique-failure" and source_count >= 1 and bool(critique_failures) and not evaluation_failures
    ) or (
        basis == "source-fixes-hard-evaluation-failure" and source_count >= 1 and bool(evaluation_failures) and not critique_failures
    )
    if not material:
        raise PromotionReceiptError("candidate packet does not satisfy an approved materiality basis")
    edits = document.get("edits")
    if not isinstance(edits, list) or not edits:
        raise PromotionReceiptError("candidate packet must declare at least one edit")
    total = 0
    seen: set[str] = set()
    for edit in edits:
        common = {"path", "role", "operation", "before_digest", "after_digest"}
        if not isinstance(edit, Mapping) or set(edit) != common | {"content_file"}:
            raise PromotionReceiptError("candidate packet edit shape is invalid")
        path = edit.get("path")
        role = edit.get("role")
        if not _automatic_path(path) or role not in {"skill", "reference"} or edit.get("operation") != "replace" or path in seen:
            raise PromotionReceiptError("candidate packet edit is outside the automatic contract")
        seen.add(path)
        total += _candidate_content_size(edit, candidate_path)
        base = _git_base_file(document["base_commit"], path, repository)
        if _digest_bytes(base) != edit.get("before_digest"):
            raise PromotionReceiptError("candidate packet before digest does not match its base commit")
    return _digest_json(document), len(edits), total


def _materialization(document: Mapping[str, Any], packet: Mapping[str, Any], packet_digest: str, campaign: Mapping[str, Any], campaign_digest: str) -> None:
    if document.get("schema_version") != 1 or document.get("receipt_kind") != "capability-change-materialization" or document.get("status") != "prepared" or document.get("change_digest") != packet_digest or document.get("base_commit") != packet.get("base_commit"):
        raise PromotionReceiptError("materialization evidence is not bound to the candidate")
    authorization = document.get("authorization")
    if not isinstance(authorization, Mapping) or authorization.get("authorization_contract") != AUTHORIZATION_CONTRACT or authorization.get("campaign_run_id") != campaign.get("run_id") or authorization.get("campaign_receipt_digest") != campaign_digest:
        raise PromotionReceiptError("materialization evidence is not bound to the campaign authorization")
    campaign_evidence = document.get("campaign_evidence")
    if (
        not isinstance(campaign_evidence, Mapping)
        or set(campaign_evidence) != {
            "receipt_digest",
            "materiality_verified_before_materialization",
        }
        or campaign_evidence.get("receipt_digest") != campaign_digest
        or campaign_evidence.get("materiality_verified_before_materialization") is not True
    ):
        raise PromotionReceiptError("materialization evidence lacks verified campaign materiality")
    packet_paths = [row.get("path") for row in packet.get("edits", []) if isinstance(row, Mapping)]
    receipt_paths = [row.get("path") for row in document.get("edits", []) if isinstance(row, Mapping)] if isinstance(document.get("edits"), list) else []
    active = document.get("active_checkout")
    isolation = document.get("isolation")
    if packet_paths != receipt_paths or not isinstance(active, Mapping) or active.get("unchanged") is not True or active.get("head_before") != active.get("head_after") or not isinstance(isolation, Mapping) or isolation.get("disposable_checkout") is not True or isolation.get("network") != "not_used" or isolation.get("temporary_checkout_cleaned") is not True:
        raise PromotionReceiptError("materialization evidence does not prove isolated exact-scope preservation")


def _evaluation(document: Mapping[str, Any], packet_digest: str, materialization_digest: str) -> None:
    gates = document.get("gates")
    metrics = document.get("metrics")
    if document.get("schema_version") != 1 or document.get("receipt_kind") != "design-learning-evaluation" or document.get("status") != "awaiting_approval" or document.get("candidate_packet_digest") != packet_digest or document.get("materialization_receipt_digest") != materialization_digest:
        raise PromotionReceiptError("evaluation evidence is not an all-gates-passing candidate result")
    if not isinstance(gates, Mapping) or not gates or any(value is not True for value in gates.values()):
        raise PromotionReceiptError("evaluation evidence has a failed design gate")
    if not isinstance(metrics, Mapping) or metrics.get("synthetic_only") is not False or not isinstance(metrics.get("real_task_usefulness_feedback_count"), int) or metrics["real_task_usefulness_feedback_count"] < 1:
        raise PromotionReceiptError("evaluation evidence lacks real task-use feedback")


def _timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _test_receipt(document: Mapping[str, Any], packet_digest: str, head_sha: str) -> None:
    if set(document) != {"schema_version", "receipt_kind", "status", "candidate_digest", "head_sha", "command", "test_count", "exit_code", "observed_at"} or document.get("schema_version") != 1 or document.get("receipt_kind") != "stack-full-repository-tests" or document.get("status") != "passed" or document.get("candidate_digest") != packet_digest or document.get("head_sha") != head_sha or document.get("command") != ["python3", "-m", "unittest", "discover", "-s", "tests"] or document.get("exit_code") != 0 or not isinstance(document.get("test_count"), int) or document["test_count"] < 1 or not _timestamp(document.get("observed_at")):
        raise PromotionReceiptError("repository test evidence is invalid or unbound")


def _review_receipt(document: Mapping[str, Any], packet_digest: str, head_sha: str) -> None:
    required = {"schema_version", "receipt_kind", "status", "candidate_digest", "head_sha", "verdict", "reviewer_family", "reviewer_id", "independence_verified", "reviewed_at"}
    if set(document) != required or document.get("schema_version") != 1 or document.get("receipt_kind") != "stack-independent-review" or document.get("status") != "passed" or document.get("candidate_digest") != packet_digest or document.get("head_sha") != head_sha or document.get("verdict") != "ship" or document.get("independence_verified") is not True or not isinstance(document.get("reviewer_family"), str) or not document["reviewer_family"] or not isinstance(document.get("reviewer_id"), str) or not document["reviewer_id"] or not _timestamp(document.get("reviewed_at")):
        raise PromotionReceiptError("independent review evidence is invalid or unbound")


def _pull_request_ci(document: Mapping[str, Any], packet_digest: str, pull_request: Mapping[str, Any]) -> None:
    if document.get("schema_version") != 1 or document.get("receipt_kind") != "github-pull-request-ci" or document.get("status") != "passed" or document.get("candidate_digest") != packet_digest or document.get("number") != pull_request.get("number") or document.get("head_sha") != pull_request.get("head_sha") or document.get("draft") is not False or document.get("all_required_checks_passed") is not True or document.get("auto_merge_enabled") is not True:
        raise PromotionReceiptError("pull request CI evidence is invalid or unbound")


def _merge_receipt(document: Mapping[str, Any], packet_digest: str, pull_request: Mapping[str, Any]) -> None:
    if document.get("schema_version") != 1 or document.get("receipt_kind") != "github-merge-verification" or document.get("status") != "passed" or document.get("candidate_digest") != packet_digest or document.get("number") != pull_request.get("number") or document.get("head_sha") != pull_request.get("head_sha") or document.get("merge_commit") != pull_request.get("merge_commit") or document.get("origin_main_commit") != pull_request.get("merge_commit"):
        raise PromotionReceiptError("merge verification evidence is invalid or unbound")


def _runtime_receipts(
    install: Mapping[str, Any],
    rollback: Mapping[str, Any],
    merge_commit: str,
    runtime: Mapping[str, Any],
    install_digest: str,
    rollback_digest: str,
    install_path: Path,
    rollback_path: Path,
) -> None:
    verifiers = install.get("verifier_results")
    source_commits = install.get("source_commits")
    if install.get("schema_version") != 1 or install.get("status") != "published" or install.get("targets") != ["claude", "codex"] or not isinstance(source_commits, list) or not all(isinstance(commit, str) and COMMIT.fullmatch(commit) for commit in source_commits) or set(source_commits) != {merge_commit} or not isinstance(verifiers, list) or {row.get("target") for row in verifiers if isinstance(row, Mapping) and row.get("status") == "passed"} != {"claude", "codex"}:
        raise PromotionReceiptError("runtime publication evidence is invalid or unbound")
    prior = rollback.get("prior_targets")
    if rollback.get("schema_version") != 1 or not isinstance(prior, Mapping) or set(prior) != {"claude", "codex"}:
        raise PromotionReceiptError("rollback evidence is invalid")
    if any(value is not None and (not isinstance(value, str) or not value.startswith("/")) for value in prior.values()):
        raise PromotionReceiptError("rollback evidence prior targets are invalid")
    expected_prior_state = {target: prior[target] is not None for target in ("claude", "codex")}
    if install.get("prior_targets") != expected_prior_state:
        raise PromotionReceiptError("rollback evidence does not match the runtime publication transaction")
    transaction_id = install.get("transaction_id")
    if not isinstance(transaction_id, str) or SAFE_ID.fullmatch(transaction_id) is None or rollback.get("transaction_id") != transaction_id:
        raise PromotionReceiptError("runtime publication and rollback transaction IDs do not match")
    if (
        install_path.name != "install.json"
        or rollback_path.name != "rollback.json"
        or install_path.parent != rollback_path.parent
        or install_path.parent.name != transaction_id
        or install_path.parent.parent.name != "transactions"
    ):
        raise PromotionReceiptError("runtime evidence is not the immutable transaction receipt pair")
    _reject_symlink_ancestors(TRUSTED_RUNTIME_RECEIPTS_ROOT)
    if TRUSTED_RUNTIME_RECEIPTS_ROOT.resolve(strict=False) != TRUSTED_RUNTIME_RECEIPTS_ROOT:
        raise PromotionReceiptError("configured installer receipt root must not redirect")
    expected_transaction = TRUSTED_RUNTIME_RECEIPTS_ROOT / "transactions" / transaction_id
    if install_path.parent != expected_transaction or rollback_path.parent != expected_transaction:
        raise PromotionReceiptError("runtime evidence is outside the configured installer receipt root")
    for directory in (TRUSTED_RUNTIME_RECEIPTS_ROOT, TRUSTED_RUNTIME_RECEIPTS_ROOT / "transactions"):
        try:
            details = directory.lstat()
        except OSError as error:
            raise PromotionReceiptError("configured installer receipt root is unavailable") from error
        if not stat.S_ISDIR(details.st_mode) or details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) != 0o700:
            raise PromotionReceiptError("configured installer receipt root must be owner-only mode 0700")
    if runtime.get("install_receipt_digest") != install_digest or runtime.get("rollback_receipt_digest") != rollback_digest:
        raise PromotionReceiptError("runtime receipt digests do not match the evidence files")


def _validate_candidate(value: Any) -> str:
    if not isinstance(value, Mapping) or set(value) != {"state", "digest", "changed_files", "total_bytes"}:
        raise PromotionReceiptError("candidate receipt shape is invalid")
    state = value.get("state")
    if state == "absent":
        if value.get("digest") is not None or value.get("changed_files") != 0 or value.get("total_bytes") != 0:
            raise PromotionReceiptError("absent candidate receipt is invalid")
    elif state == "selected":
        if not isinstance(value.get("digest"), str) or HEX64.fullmatch(value["digest"]) is None:
            raise PromotionReceiptError("selected candidate digest is invalid")
        if not isinstance(value.get("changed_files"), int) or isinstance(value.get("changed_files"), bool) or value["changed_files"] < 1:
            raise PromotionReceiptError("selected candidate file count is invalid")
        if not isinstance(value.get("total_bytes"), int) or isinstance(value.get("total_bytes"), bool) or value["total_bytes"] < 1:
            raise PromotionReceiptError("selected candidate byte count is invalid")
    elif state not in CANDIDATE_STATES:
        raise PromotionReceiptError("candidate state is invalid")
    return state


def _validate_gates(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != set(REQUIRED_GATES):
        raise PromotionReceiptError("promotion gate set is incomplete")
    gates = dict(value)
    if any(status not in GATE_STATES for status in gates.values()):
        raise PromotionReceiptError("promotion gate status is invalid")
    return gates


def _validate_pull_request(value: Any) -> str:
    if not isinstance(value, Mapping) or set(value) != {"state", "number", "head_sha", "merge_commit"}:
        raise PromotionReceiptError("pull request receipt shape is invalid")
    state = value.get("state")
    if state == "merged":
        if not isinstance(value.get("number"), int) or isinstance(value.get("number"), bool) or value["number"] < 1:
            raise PromotionReceiptError("merged pull request number is invalid")
        if not isinstance(value.get("head_sha"), str) or COMMIT.fullmatch(value["head_sha"]) is None:
            raise PromotionReceiptError("merged pull request head is invalid")
        if not isinstance(value.get("merge_commit"), str) or COMMIT.fullmatch(value["merge_commit"]) is None:
            raise PromotionReceiptError("merged pull request commit is invalid")
    elif state == "not_created":
        if any(value.get(key) is not None for key in ("number", "head_sha", "merge_commit")):
            raise PromotionReceiptError("not-created pull request receipt is invalid")
    elif state in {"closed", "open"}:
        if not isinstance(value.get("number"), int) or isinstance(value.get("number"), bool) or value["number"] < 1:
            raise PromotionReceiptError("non-merged pull request number is invalid")
        if not isinstance(value.get("head_sha"), str) or COMMIT.fullmatch(value["head_sha"]) is None:
            raise PromotionReceiptError("non-merged pull request head is invalid")
        if value.get("merge_commit") is not None:
            raise PromotionReceiptError("non-merged pull request cannot claim a merge commit")
    elif state not in PULL_REQUEST_STATES:
        raise PromotionReceiptError("pull request state is invalid")
    return state


def _validate_runtime(value: Any) -> str:
    if not isinstance(value, Mapping) or set(value) != {
        "state",
        "targets",
        "install_receipt_digest",
        "rollback_receipt_digest",
    }:
        raise PromotionReceiptError("runtime receipt shape is invalid")
    state = value.get("state")
    if state == "published":
        if value.get("targets") != ["claude", "codex"]:
            raise PromotionReceiptError("published runtime targets are invalid")
        for key in ("install_receipt_digest", "rollback_receipt_digest"):
            if not isinstance(value.get(key), str) or HEX64.fullmatch(value[key]) is None:
                raise PromotionReceiptError("published runtime receipt proof is invalid")
    elif state == "not_run":
        if value.get("targets") != [] or value.get("install_receipt_digest") is not None or value.get("rollback_receipt_digest") is not None:
            raise PromotionReceiptError("non-published runtime receipt is invalid")
    elif state not in RUNTIME_STATES:
        raise PromotionReceiptError("runtime state is invalid")
    return state


def _validate_outcome(
    document: dict[str, Any],
    campaign: Mapping[str, Any],
    campaign_digest: str,
    campaign_path: Path,
    evidence: Mapping[str, dict[str, Any] | None],
    evidence_digests: Mapping[str, str | None],
    evidence_paths: Mapping[str, Path | None],
) -> None:
    disposition = document["disposition"]
    candidate = _validate_candidate(document["candidate"])
    gates = _validate_gates(document["gates"])
    pull_request = _validate_pull_request(document["pull_request"])
    runtime = _validate_runtime(document["runtime"])

    if campaign.get("terminal_state") == "no_action" and disposition != "no_action":
        raise PromotionReceiptError("a no_action campaign cannot promote a candidate")
    if candidate == "selected" and (
        campaign.get("terminal_state") != "prepared"
        or campaign.get("reason_code") != "automatic_promotion_pending"
    ):
        raise PromotionReceiptError("selected candidate requires a prepared automatic-promotion campaign")
    if candidate == "absent" and evidence.get("candidate_packet") is not None:
        raise PromotionReceiptError("absent candidate cannot include candidate evidence")
    if candidate == "selected":
        packet = evidence.get("candidate_packet")
        if packet is None:
            raise PromotionReceiptError("selected candidate requires a bound candidate packet")
        packet_digest, changed_files, total_bytes = _candidate_packet(
            packet,
            campaign,
            campaign_digest,
            campaign_path,
            evidence_paths["candidate_packet"] or Path(),
        )
        if document["candidate"] != {
            "state": "selected",
            "digest": packet_digest,
            "changed_files": changed_files,
            "total_bytes": total_bytes,
        }:
            raise PromotionReceiptError("candidate summary does not match the candidate packet")
    else:
        packet = None
        packet_digest = ""

    for gate, status in gates.items():
        if status == "passed" and evidence.get(GATE_EVIDENCE[gate]) is None:
            raise PromotionReceiptError(f"passed gate lacks {GATE_EVIDENCE[gate]} evidence")

    if disposition == "published":
        if candidate != "selected" or any(status != "passed" for status in gates.values()):
            raise PromotionReceiptError("published outcome requires a selected candidate and every gate passed")
        if pull_request != "merged" or runtime != "published":
            raise PromotionReceiptError("published outcome requires merged pull request and published runtime proof")
        assert packet is not None
        materialization = evidence["materialization"]
        evaluation = evidence["evaluation"]
        tests = evidence["repository_tests"]
        review = evidence["independent_review"]
        ci = evidence["pull_request_ci"]
        merge = evidence["merge_verification"]
        install = evidence["runtime_publication"]
        rollback = evidence["rollback_receipt"]
        assert all(item is not None for item in (materialization, evaluation, tests, review, ci, merge, install, rollback))
        _materialization(materialization, packet, packet_digest, campaign, campaign_digest)
        _evaluation(evaluation, packet_digest, evidence_digests["materialization"] or "")
        _test_receipt(tests, packet_digest, document["pull_request"]["head_sha"])
        _review_receipt(review, packet_digest, document["pull_request"]["head_sha"])
        _pull_request_ci(ci, packet_digest, document["pull_request"])
        _merge_receipt(merge, packet_digest, document["pull_request"])
        _runtime_receipts(
            install,
            rollback,
            document["pull_request"]["merge_commit"],
            document["runtime"],
            evidence_digests["runtime_publication"] or "",
            evidence_digests["rollback_receipt"] or "",
            evidence_paths["runtime_publication"] or Path(),
            evidence_paths["rollback_receipt"] or Path(),
        )
    elif disposition == "no_action":
        if candidate != "absent" or any(status != "not_applicable" for status in gates.values()):
            raise PromotionReceiptError("no_action requires no candidate and no applicable gates")
        if pull_request != "not_created" or runtime != "not_run":
            raise PromotionReceiptError("no_action cannot create a review queue or publish a runtime")
        if any(value is not None for value in evidence.values()):
            raise PromotionReceiptError("no_action cannot claim promotion evidence")
    elif disposition == "rejected_no_queue":
        if candidate != "selected" or "failed" not in gates.values() or "unavailable" in gates.values():
            raise PromotionReceiptError("rejected_no_queue requires a selected candidate and a failed gate")
        if pull_request not in {"not_created", "closed"} or runtime != "not_run":
            raise PromotionReceiptError("rejected candidate cannot leave a review queue or runtime change")
    elif disposition == "retry_with_alert":
        if "unavailable" not in gates.values():
            raise PromotionReceiptError("retry_with_alert requires an unavailable gate")
        if pull_request not in {"not_created", "closed"} or runtime != "not_run":
            raise PromotionReceiptError("retry_with_alert cannot merge or publish a runtime change")


def _output_directory(path: Path) -> Path:
    lexical = Path(os.path.abspath(str(Path(path).expanduser())))
    _reject_symlink_ancestors(lexical, allow_missing_leaf=True)
    resolved = lexical.resolve(strict=False)
    try:
        resolved.relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise PromotionReceiptError("promotion receipt directory must be owner-local outside the repository")
    try:
        if resolved.exists():
            details = resolved.lstat()
            if not stat.S_ISDIR(details.st_mode) or details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) != 0o700:
                raise PromotionReceiptError("promotion receipt directory must be owner-only mode 0700")
        else:
            parent = resolved.parent.lstat()
            if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700:
                raise PromotionReceiptError("promotion receipt parent must be owner-only mode 0700")
            resolved.mkdir(mode=0o700)
        return resolved
    except OSError as error:
        raise PromotionReceiptError("promotion receipt directory is unavailable") from error


def _persist(path: Path, receipt: dict[str, Any]) -> None:
    encoded = _canonical(receipt)
    if path.exists() or path.is_symlink():
        _existing, content = _private_file(path, "existing promotion receipt")
        if content == encoded:
            return
        raise PromotionReceiptError("promotion receipt would overwrite conflicting evidence")
    staged: Path | None = None
    try:
        descriptor, staged_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        staged = Path(staged_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(staged, path)
        except FileExistsError:
            _existing, content = _private_file(path, "existing promotion receipt")
            if content != encoded:
                raise PromotionReceiptError("promotion receipt would overwrite conflicting evidence")
    except OSError as error:
        raise PromotionReceiptError("unable to persist promotion receipt") from error
    finally:
        if staged is not None:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                pass


def record(
    live_receipt_path: Path | str,
    live_receipt_digest: str,
    campaign_path: Path | str,
    decision: Mapping[str, Any] | Path | str,
    out_dir: Path | str,
) -> dict[str, Any]:
    campaign, campaign_digest, resolved_campaign = _campaign(Path(campaign_path))
    _live, live_digest = _live_binding(
        Path(live_receipt_path),
        live_receipt_digest,
        resolved_campaign,
        campaign,
        campaign_digest,
    )
    document, decision_path, decision_digest = _decision(decision)
    if decision_path is not None:
        candidate_digest = document.get("candidate", {}).get("digest")
        candidate_component = candidate_digest if candidate_digest is not None else "no-candidate"
        expected_name = f"{campaign['run_id']}--{candidate_component}--{decision_digest}.json"
        if decision_path.name != expected_name:
            raise PromotionReceiptError("promotion decision filename digest is invalid")
    evidence, evidence_digests, evidence_paths = _evidence_documents(document["evidence"])
    _validate_outcome(
        document,
        campaign,
        campaign_digest,
        resolved_campaign,
        evidence,
        evidence_digests,
        evidence_paths,
    )
    receipt = {
        "schema_version": 1,
        "receipt_kind": "weekly-design-automatic-promotion",
        "authorization_contract": AUTHORIZATION_CONTRACT,
        "disposition": document["disposition"],
        "reason_code": document["reason_code"],
        "campaign": {
            "run_id": campaign["run_id"],
            "input_fingerprint": campaign["input_fingerprint"],
            "receipt_digest": campaign_digest,
        },
        "live_binding_receipt_digest": live_digest,
        "candidate": document["candidate"],
        "gates": document["gates"],
        "pull_request": document["pull_request"],
        "runtime": document["runtime"],
        "evidence": evidence_digests,
        "receipt_persisted": True,
    }
    candidate_digest = document["candidate"]["digest"]
    receipt_digest = _digest_json(receipt)
    receipt_name = (
        f"{campaign['run_id']}--{candidate_digest}--{receipt_digest}.json"
        if candidate_digest is not None
        else f"{campaign['run_id']}.json"
    )
    destination = _output_directory(Path(out_dir)) / receipt_name
    _persist(destination, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-receipt", type=Path, required=True, help="owner-local live binding receipt (0600)")
    parser.add_argument("--live-receipt-digest", required=True, help="exact SHA-256 returned by the live entrypoint")
    parser.add_argument("--campaign-receipt", type=Path, required=True, help="owner-local collection receipt (0600)")
    parser.add_argument("--decision", type=Path, required=True, help="owner-local terminal decision document (0600)")
    parser.add_argument("--out-dir", type=Path, required=True, help="owner-local terminal receipt directory (0700)")
    arguments = parser.parse_args()
    try:
        receipt = record(
            arguments.live_receipt,
            arguments.live_receipt_digest,
            arguments.campaign_receipt,
            arguments.decision,
            arguments.out_dir,
        )
    except PromotionReceiptError as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
