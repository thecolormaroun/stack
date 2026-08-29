#!/usr/bin/env python3
"""Evaluate a quarantined design-learning candidate against frozen evidence.

This evaluator is intentionally a receipt producer.  It never imports a
candidate into Stack, edits a fixture, advances an active pointer, installs a
runtime, opens a PR, or falls back to a network/provider.  A missing or
incomplete ``STACK_DESIGN_EVAL_ROOT`` is a visible ``blocked-eval`` result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
HEX64 = re.compile(r"^[a-f0-9]{64}$")
COMMIT = re.compile(r"^[a-f0-9]{40}$")


class DesignEvaluationError(ValueError):
    """The evaluator cannot prove a safe, deterministic result."""


EvaluationError = DesignEvaluationError


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_json(value: Any) -> str:
    return digest_bytes(canonical_json(value).encode("utf-8"))


def digest_file(path: Path) -> str:
    try:
        return digest_bytes(path.read_bytes())
    except (OSError, UnicodeError) as error:
        raise DesignEvaluationError("evaluation artifact is unreadable") from error


def load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DesignEvaluationError(f"{label} is not readable JSON") from error
    if not isinstance(value, dict):
        raise DesignEvaluationError(f"{label} must be a JSON object")
    return value


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _load_value(value: Any, label: str) -> tuple[Any, str, str | None]:
    """Return (decoded value, exact digest, source path without exposing it)."""

    if isinstance(value, Path):
        try:
            raw = value.read_bytes()
            decoded = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise DesignEvaluationError(f"{label} is not readable JSON") from error
        return decoded, digest_bytes(raw), value.name
    if isinstance(value, str):
        path = Path(value)
        return _load_value(path, label)
    return value, digest_json(value), None


def _profile(document: Mapping[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = document.get("design_profiles")
    if not isinstance(profiles, Mapping) or not isinstance(profiles.get(profile_name), Mapping):
        raise DesignEvaluationError("design evaluation profile is unavailable")
    profile = dict(profiles[profile_name])
    required = {
        "harness_environment", "minimum_repetitions", "maximum_score_stddev", "minimum_development_wins",
        "minimum_effect_size", "minimum_weighted_aggregate_improvement", "maximum_dimension_regression",
        "maximum_holdout_regression", "maximum_rubric_disagreement", "required_task_feedback",
        "dimension_weights", "hard_gates", "required_splits",
    }
    if not required.issubset(profile):
        raise DesignEvaluationError("design evaluation profile is incomplete")
    weights = profile.get("dimension_weights")
    if not isinstance(weights, Mapping) or not weights or any(not isinstance(value, (int, float)) or value <= 0 for value in weights.values()):
        raise DesignEvaluationError("design evaluation dimension weights are invalid")
    if not math.isclose(sum(float(value) for value in weights.values()), 1.0, abs_tol=1e-9):
        raise DesignEvaluationError("design evaluation dimension weights must sum to one")
    for key in ("minimum_repetitions", "minimum_development_wins"):
        if not isinstance(profile[key], int) or profile[key] < 1:
            raise DesignEvaluationError("design evaluation profile count is invalid")
    for key in (
        "maximum_score_stddev", "minimum_effect_size", "minimum_weighted_aggregate_improvement",
        "maximum_dimension_regression", "maximum_holdout_regression", "maximum_rubric_disagreement",
    ):
        if not isinstance(profile[key], (int, float)) or not 0 <= float(profile[key]) <= 1:
            raise DesignEvaluationError("design evaluation profile threshold is invalid")
    if not isinstance(profile["harness_environment"], str) or not profile["harness_environment"]:
        raise DesignEvaluationError("design evaluation harness environment is invalid")
    if not isinstance(profile["hard_gates"], list) or not profile["hard_gates"] or len(set(profile["hard_gates"])) != len(profile["hard_gates"]):
        raise DesignEvaluationError("design evaluation hard gates are invalid")
    if set(profile["required_splits"]) != {"development", "holdout", "rotating_canary"}:
        raise DesignEvaluationError("design evaluation splits are invalid")
    return profile


def _validate_packet(packet: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    expected_top_level = {
        "schema_version", "change_id", "state", "approval_state", "base_commit",
        "source_lineage", "target", "rationale", "rollback", "edits", "evaluation",
    }
    if set(packet) != expected_top_level:
        raise DesignEvaluationError("candidate packet has unsupported or missing top-level fields")
    if packet.get("schema_version") != 1 or packet.get("state") != "candidate_quarantined" or packet.get("approval_state") != "candidate_unapproved":
        raise DesignEvaluationError("candidate packet is not quarantined and unapproved")
    if not isinstance(packet.get("base_commit"), str) or COMMIT.fullmatch(packet["base_commit"]) is None:
        raise DesignEvaluationError("candidate packet base_commit is invalid")
    if not isinstance(packet.get("change_id"), str) or re.fullmatch(r"[a-z][a-z0-9-]{1,32}:[a-f0-9]{16,64}", packet["change_id"]) is None:
        raise DesignEvaluationError("candidate packet change_id is invalid")
    nested_shapes = {
        "source_lineage": {"packet_id", "packet_digest", "card_ids", "revision_ids", "evidence_ids", "parent_digests"},
        "target": {"canonical_name", "capability_path", "provider", "package", "upstream_pin"},
        "rationale": {"change_kind", "expected_behavior", "overlap_analysis", "license_posture", "privacy_class"},
        "rollback": {"base_commit", "path_digests"},
    }
    for key, fields in nested_shapes.items():
        value = packet.get(key)
        if not isinstance(value, Mapping) or set(value) != fields:
            raise DesignEvaluationError(f"candidate packet {key} shape is unsupported")
    if packet["target"].get("provider") != "stack" or packet["target"].get("package") != "stack" or packet["target"].get("upstream_pin") is not None:
        raise DesignEvaluationError("candidate packet target is not Stack-owned")
    if not isinstance(packet["edits"], list) or not 1 <= len(packet["edits"]) <= 5:
        raise DesignEvaluationError("candidate packet edits are unsupported")
    for edit in packet["edits"]:
        if not isinstance(edit, Mapping) or set(edit) != {"path", "role", "operation", "before_digest", "after_digest", "content"}:
            raise DesignEvaluationError("candidate packet edit shape is unsupported")
    evaluation = packet.get("evaluation")
    if not isinstance(evaluation, Mapping) or evaluation.get("profile") != "design-learning-v1" or evaluation.get("harness_required") is not True:
        raise DesignEvaluationError("candidate packet is not bound to design-learning-v1")
    for key in ("development_manifest_digest", "holdout_manifest_digest", "rotating_canary_manifest_digest"):
        if not _is_digest(evaluation.get(key)):
            raise DesignEvaluationError("candidate packet manifest digest is invalid")
    return digest_json(packet), dict(evaluation)


def _validate_materialization(receipt: Mapping[str, Any], packet: Mapping[str, Any], packet_digest: str) -> None:
    expected = {
        "schema_version", "receipt_kind", "status", "change_digest", "change_id",
        "base_commit", "target", "edits", "patch_digest", "patch_filename",
        "authorization", "active_checkout", "isolation", "quarantine",
        "activation", "next_gate",
    }
    if set(receipt) != expected or receipt.get("schema_version") != 1 or receipt.get("status") != "prepared" or receipt.get("receipt_kind") != "capability-change-materialization":
        raise DesignEvaluationError("materialization receipt is incomplete or not prepared")
    bound = receipt.get("change_digest", receipt.get("candidate_packet_digest"))
    if bound != packet_digest:
        raise DesignEvaluationError("materialization receipt does not match candidate packet")
    if receipt.get("base_commit") != packet.get("base_commit"):
        raise DesignEvaluationError("materialization receipt does not match packet base_commit")
    if receipt.get("change_id") != packet.get("change_id") or receipt.get("target") != packet.get("target"):
        raise DesignEvaluationError("materialization receipt does not match packet target")
    receipt_edits = receipt.get("edits")
    packet_edits = packet.get("edits")
    if not isinstance(receipt_edits, list) or not isinstance(packet_edits, list) or [row.get("path") for row in receipt_edits if isinstance(row, Mapping)] != [row.get("path") for row in packet_edits if isinstance(row, Mapping)]:
        raise DesignEvaluationError("materialization receipt does not match packet edits")
    if not _is_digest(receipt.get("patch_digest")):
        raise DesignEvaluationError("materialization receipt patch digest is invalid")
    active = receipt.get("active_checkout")
    if not isinstance(active, Mapping) or active.get("unchanged") is not True or active.get("head_before") != active.get("head_after") or active.get("status_digest_before") != active.get("status_digest_after"):
        raise DesignEvaluationError("materialization receipt does not prove active checkout preservation")
    isolation = receipt.get("isolation")
    if not isinstance(isolation, Mapping) or isolation.get("disposable_checkout") is not True or isolation.get("temporary_checkout_cleaned") is not True or isolation.get("network") != "not_used":
        raise DesignEvaluationError("materialization receipt does not prove isolated cleanup")
    quarantine = receipt.get("quarantine")
    if not isinstance(quarantine, Mapping) or quarantine.get("owner_local") is not True or quarantine.get("retrieval_truth") is not False or quarantine.get("future_fixtures") is not False or quarantine.get("active_evidence") is not False:
        raise DesignEvaluationError("materialization receipt does not preserve quarantine")
    activation = receipt.get("activation")
    if not isinstance(activation, Mapping) or any(activation.get(key) is not False for key in ("active_pointer", "install", "publish", "draft_pr", "network_action")):
        raise DesignEvaluationError("materialization receipt authorizes activation")


def _manifest(value: Any, expected_split: str, expected_digest: str) -> tuple[dict[str, Any], str]:
    decoded, exact_digest, _ = _load_value(value, f"{expected_split} manifest")
    if not isinstance(decoded, Mapping):
        raise DesignEvaluationError(f"{expected_split} manifest is not an object")
    manifest = dict(decoded)
    if exact_digest != expected_digest:
        raise DesignEvaluationError(f"{expected_split} manifest digest does not match packet")
    if manifest.get("schema_version") != 1 or manifest.get("split") != expected_split or manifest.get("frozen") is not True:
        raise DesignEvaluationError(f"{expected_split} manifest is not frozen")
    if manifest.get("candidate_generated_inputs") is not False:
        raise DesignEvaluationError(f"{expected_split} manifest contains candidate-generated inputs")
    if expected_split == "holdout" and manifest.get("protected") is not True:
        raise DesignEvaluationError("holdout manifest is not protected")
    if expected_split == "rotating_canary" and manifest.get("owner_local_in_production") is not True:
        raise DesignEvaluationError("rotating canary is not owner-local")
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise DesignEvaluationError(f"{expected_split} manifest has no fixtures")
    seen: set[str] = set()
    for fixture in fixtures:
        if not isinstance(fixture, Mapping) or not isinstance(fixture.get("id"), str) or not fixture["id"] or fixture["id"] in seen:
            raise DesignEvaluationError(f"{expected_split} manifest has invalid fixture identities")
        if not isinstance(fixture.get("weight"), (int, float)) or float(fixture["weight"]) <= 0:
            raise DesignEvaluationError(f"{expected_split} fixture weight is invalid")
        seen.add(fixture["id"])
    return manifest, exact_digest


def _fixture_rows(value: Any, expected_split: str) -> list[dict[str, Any]]:
    decoded, _digest, _ = _load_value(value, f"{expected_split} results")
    if isinstance(decoded, list):
        rows: Any = decoded
        root: Mapping[str, Any] = {}
    elif isinstance(decoded, Mapping):
        root = decoded
        rows = decoded.get("results", decoded.get("fixtures", decoded.get("repetitions")))
        if rows is None and all(isinstance(key, str) for key in decoded):
            rows = []
            for key, child in decoded.items():
                if isinstance(child, Mapping):
                    rows.append({"fixture_id": key, **child})
    else:
        rows = None
        root = {}
    if not isinstance(rows, list):
        raise DesignEvaluationError(f"{expected_split} results are incomplete")
    output: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise DesignEvaluationError(f"{expected_split} result row is invalid")
        fixture_id = row.get("fixture_id", row.get("id", row.get("fixture")))
        repetitions = row.get("repetitions")
        if isinstance(repetitions, list):
            for repetition_index, repetition in enumerate(repetitions):
                if not isinstance(repetition, Mapping):
                    raise DesignEvaluationError(f"{expected_split} repetition is invalid")
                combined = dict(row)
                combined.pop("repetitions", None)
                combined.update(repetition)
                combined["fixture_id"] = fixture_id or combined.get("fixture_id", combined.get("id"))
                combined["repetition"] = repetition.get("repetition", repetition_index + 1)
                output.append(combined)
            continue
        # A top-level repetitions array may contain fixture groups.  Expand a
        # group with ``fixtures`` recursively while retaining its repetition.
        grouped = row.get("fixtures")
        if isinstance(grouped, list):
            for child in grouped:
                if not isinstance(child, Mapping):
                    raise DesignEvaluationError(f"{expected_split} grouped fixture is invalid")
                combined = dict(child)
                combined["repetition"] = row.get("repetition", index + 1)
                output.append(combined)
            continue
        combined = dict(row)
        combined["fixture_id"] = fixture_id
        combined.setdefault("repetition", row.get("run", index + 1))
        output.append(combined)
    if isinstance(root.get("feedback"), (list, Mapping)):
        for row in output:
            row.setdefault("task_usefulness_feedback", root["feedback"])
    return output


DIMENSION_ALIASES = {
    "task_usefulness": {"task_usefulness", "task-usefulness", "usefulness", "task"},
    "visual_quality": {"visual_quality", "visual-quality", "visual"},
    "behavior": {"behavior", "behaviour", "functional", "interaction"},
    "accessibility": {"accessibility", "a11y"},
    "privacy": {"privacy", "privacy_safety", "privacy-safety"},
    "citation": {"citation", "citations", "provenance"},
}


def _dimension_value(dimensions: Mapping[str, Any], name: str) -> float | None:
    aliases = DIMENSION_ALIASES.get(name, {name})
    for key, value in dimensions.items():
        if str(key).lower() in aliases and isinstance(value, (int, float)) and not isinstance(value, bool):
            if not 0 <= float(value) <= 1:
                raise DesignEvaluationError("evaluation dimension score is outside [0,1]")
            return float(value)
    return None


def _score_block(value: Any, weights: Mapping[str, float]) -> dict[str, Any]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        overall = float(value)
        dimensions: dict[str, float] = {}
        if not 0 <= overall <= 1:
            raise DesignEvaluationError("evaluation score is outside [0,1]")
    elif isinstance(value, Mapping):
        overall_value = value.get("overall", value.get("aggregate", value.get("score", value.get("value"))))
        raw_dimensions = value.get("dimensions", value.get("rubric", value.get("scores", {})))
        if not isinstance(raw_dimensions, Mapping):
            raw_dimensions = {}
        dimensions = {}
        for name in weights:
            score = _dimension_value(raw_dimensions, name)
            if score is not None:
                dimensions[name] = score
        if dimensions and set(dimensions) != set(weights):
            raise DesignEvaluationError("evaluation dimensions are incomplete")
        if set(dimensions) == set(weights):
            weighted = sum(float(weights[name]) * dimensions[name] for name in weights)
            if overall_value is not None and (not isinstance(overall_value, (int, float)) or isinstance(overall_value, bool) or abs(float(overall_value) - weighted) > 1e-6):
                raise DesignEvaluationError("evaluation aggregate does not match dimension weights")
            overall = weighted
        elif overall_value is None:
            raise DesignEvaluationError("evaluation score is missing aggregate or dimensions")
        elif isinstance(overall_value, (int, float)) and not isinstance(overall_value, bool):
            overall = float(overall_value)
            if not 0 <= overall <= 1:
                raise DesignEvaluationError("evaluation aggregate is outside [0,1]")
        else:
            raise DesignEvaluationError("evaluation aggregate is invalid")
    else:
        raise DesignEvaluationError("evaluation score block is invalid")
    if set(dimensions) != set(weights):
        raise DesignEvaluationError("evaluation dimensions are incomplete")
    return {"overall": overall, "dimensions": dimensions}


def _pair(row: Mapping[str, Any], weights: Mapping[str, float]) -> tuple[dict[str, Any], dict[str, Any]]:
    scores = row.get("scores") if isinstance(row.get("scores"), Mapping) else {}
    baseline_value = row.get("baseline", scores.get("baseline"))
    candidate_value = row.get("candidate", scores.get("candidate"))
    if baseline_value is None or candidate_value is None:
        raise DesignEvaluationError("evaluation result is missing baseline or candidate score")
    return _score_block(baseline_value, weights), _score_block(candidate_value, weights)


def _gates(row: Mapping[str, Any], candidate: Mapping[str, Any], required: Sequence[str]) -> dict[str, bool]:
    values: Any = candidate.get("hard_gates", candidate.get("gates"))
    if values is None:
        values = row.get("candidate_hard_gates", row.get("hard_gates", row.get("gates")))
    if not isinstance(values, Mapping):
        raise DesignEvaluationError("candidate hard-gate results are missing")
    result: dict[str, bool] = {}
    for name in required:
        value = values.get(name)
        if not isinstance(value, bool):
            raise DesignEvaluationError("candidate hard-gate results are incomplete")
        result[name] = value
    return result


def _feedback_values(row: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[Any]:
    values: list[Any] = []
    for source in (candidate, row):
        for key in ("task_usefulness_feedback", "usefulness_feedback", "task_feedback", "feedback"):
            if key not in source:
                continue
            value = source[key]
            if isinstance(value, list):
                values.extend(value)
            else:
                values.append(value)
    return values


def _feedback_kind(value: Any) -> str:
    if isinstance(value, Mapping):
        if value.get("synthetic") is True or value.get("is_synthetic") is True:
            return "synthetic"
        if value.get("real") is True or value.get("is_real") is True:
            return "real"
        kind = str(value.get("kind", value.get("source", value.get("type", "")))).lower()
        if kind in {"synthetic", "fixture", "simulated", "model"}:
            return "synthetic"
        if kind in {"real", "user", "human", "task", "task-use", "task_use"}:
            return "real"
        if isinstance(value.get("text"), str) and value["text"].strip():
            return "unknown"
    if isinstance(value, str) and value.strip():
        return "unknown"
    return "missing"


def _rubric_disagreement(row: Mapping[str, Any], candidate: Mapping[str, Any]) -> float | None:
    candidates = [candidate, row]
    rubric: Any = None
    usefulness: Any = None
    for source in candidates:
        if rubric is None:
            rubric = source.get("rubric_score", source.get("rubric"))
        if usefulness is None:
            usefulness = source.get("task_usefulness_score", source.get("usefulness_score"))
    if isinstance(rubric, Mapping):
        rubric = rubric.get("overall", rubric.get("score", rubric.get("value")))
    if isinstance(usefulness, Mapping):
        usefulness = usefulness.get("overall", usefulness.get("score", usefulness.get("value")))
    if isinstance(rubric, (int, float)) and isinstance(usefulness, (int, float)):
        return abs(float(rubric) - float(usefulness))
    return None


def _resolve_result_path(root: Path, split: str) -> Path | None:
    names = [
        f"{split}-results.json", f"{split}_results.json", f"{split}.json",
        f"{split}/results.json", f"{split}/result.json", f"{split}/evaluation.json",
    ]
    for name in names:
        path = root / name
        if path.is_file() and not path.is_symlink():
            return path
    return None


def _owner_output(path: Path) -> tuple[Path, bool]:
    lexical = path.expanduser()
    if not lexical.is_absolute():
        lexical = Path.cwd() / lexical
    lexical = Path(os.path.abspath(lexical))
    current = Path(lexical.anchor)
    for component in lexical.parts[1:]:
        current = current / component
        if current.is_symlink() and current not in {Path("/tmp"), Path("/var"), Path("/private")}:
            raise DesignEvaluationError("evaluation output has a symlink parent")
    resolved = lexical.resolve(strict=False)
    if resolved == ROOT or ROOT in resolved.parents or resolved == Path.home().resolve() or resolved.is_symlink():
        raise DesignEvaluationError("evaluation output must be owner-local and outside Stack")
    if resolved.suffix.lower() == ".json":
        directory = resolved.parent
        output_file = resolved
    else:
        directory = resolved
        output_file = resolved / "design-learning-evaluation-receipt.json"
    if not directory.exists():
        directory.mkdir(parents=True, mode=0o700)
    info = directory.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise DesignEvaluationError("evaluation output directory must be owner-only")
    return output_file, True


def _write_idempotent(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise DesignEvaluationError("evaluation output may not be a symlink")
    if path.exists():
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise DesignEvaluationError("evaluation output permissions are unsafe")
        if path.read_bytes() != data:
            raise DesignEvaluationError("existing evaluation receipt differs from deterministic rerun")
        return
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
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
            raise DesignEvaluationError("existing evaluation receipt differs from deterministic rerun")
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _blocked_receipt(packet_digest: str | None, reason: str, *, expected: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "receipt_kind": "design-learning-evaluation",
        "status": "blocked-eval",
        "candidate_packet_digest": packet_digest,
        "reason_codes": [reason],
        "manifests": dict(expected or {}),
        "quarantine": {"results_owner_local": True, "candidate_outputs": True, "retrieval_truth": False, "future_fixtures": False},
        "activation": {"active_pointer": False, "install": False, "publish": False, "draft_pr": False, "network_action": False},
        "next_gate": "provide-complete-frozen-design-eval-harness",
    }


def evaluate_design_candidate(
    packet: Mapping[str, Any],
    materialization_receipt: Mapping[str, Any],
    manifests: Mapping[str, Any],
    results: Mapping[str, Any],
    profile: Mapping[str, Any],
    harness_root: Path | None = None,
) -> dict[str, Any]:
    """Evaluate decoded packet, receipt, manifests, and result documents."""

    packet_digest, evaluation = _validate_packet(packet)
    _validate_materialization(materialization_receipt, packet, packet_digest)
    profile_doc = dict(profile)
    if isinstance(profile_doc.get("design_profiles"), Mapping):
        profile_doc = dict(profile_doc["design_profiles"].get("design-learning-v1", {}))
    expected_root = profile_doc.get("harness_environment", "STACK_DESIGN_EVAL_ROOT")
    root = harness_root if harness_root is not None else (Path(os.environ[expected_root]) if os.environ.get(expected_root) else None)
    if root is None or not root.is_dir() or root.is_symlink():
        return _blocked_receipt(packet_digest, "missing_eval_root")
    root_info = root.lstat()
    if root_info.st_uid != os.getuid() or stat.S_IMODE(root_info.st_mode) != 0o700:
        return _blocked_receipt(packet_digest, "unsafe_eval_root")
    expected_digests = {
        "development": evaluation["development_manifest_digest"],
        "holdout": evaluation["holdout_manifest_digest"],
        "rotating_canary": evaluation["rotating_canary_manifest_digest"],
    }
    manifest_docs: dict[str, dict[str, Any]] = {}
    manifest_receipts: dict[str, Any] = {}
    result_values: dict[str, Any] = {}
    result_digests: dict[str, str] = {}
    reasons: list[str] = []
    try:
        for split in ("development", "holdout", "rotating_canary"):
            supplied = manifests.get(split)
            if supplied is None:
                candidate = root / f"{split}-manifest.json"
                supplied = candidate if candidate.is_file() else None
            if supplied is None:
                raise DesignEvaluationError(f"missing_{split}_manifest")
            manifest, exact_digest = _manifest(supplied, split, expected_digests[split])
            manifest_docs[split] = manifest
            manifest_receipts[split] = {"digest": exact_digest, "fixture_count": len(manifest["fixtures"]), "frozen": True}
            result = results.get(split)
            if result is None and isinstance(supplied, (Path, str)):
                result = _resolve_result_path(root, split)
            if result is None:
                raise DesignEvaluationError(f"missing_{split}_results")
            decoded, exact_result_digest, _ = _load_value(result, f"{split} results")
            if not isinstance(decoded, Mapping):
                raise DesignEvaluationError(f"invalid_{split}_results")
            binding = {
                "candidate_packet_digest": packet_digest,
                "materialization_receipt_digest": digest_json(materialization_receipt),
                "manifest_digest": exact_digest,
            }
            if any(decoded.get(key) != value for key, value in binding.items()):
                raise DesignEvaluationError(f"unbound_{split}_results")
            result_values[split] = decoded
            result_digests[split] = exact_result_digest
    except DesignEvaluationError as error:
        reason = str(error)
        return _blocked_receipt(packet_digest, reason, expected=manifest_receipts)

    fixture_maps: dict[str, dict[str, Mapping[str, Any]]] = {}
    normalized: dict[str, list[dict[str, Any]]] = {}
    weights: Mapping[str, float] = profile_doc["dimension_weights"]
    for split in ("development", "holdout", "rotating_canary"):
        fixtures = manifest_docs[split]["fixtures"]
        fixture_maps[split] = {str(row["id"]): row for row in fixtures}
        try:
            rows = _fixture_rows(result_values[split], split)
        except DesignEvaluationError as error:
            return _blocked_receipt(packet_digest, str(error), expected=manifest_receipts)
        expected_ids = set(fixture_maps[split])
        actual_ids = {str(row.get("fixture_id")) for row in rows}
        if None in actual_ids or not expected_ids <= actual_ids or actual_ids - expected_ids:
            return _blocked_receipt(packet_digest, f"incomplete_{split}_fixture_results", expected=manifest_receipts)
        normalized_rows: list[dict[str, Any]] = []
        try:
            for row in rows:
                fixture_id = str(row["fixture_id"])
                baseline, candidate = _pair(row, weights)
                candidate_block = row.get("candidate") if isinstance(row.get("candidate"), Mapping) else {}
                gates = _gates(row, candidate_block, profile_doc["hard_gates"])
                feedback = _feedback_values(row, candidate_block)
                disagreement = _rubric_disagreement(row, candidate_block)
                normalized_rows.append({
                    "fixture_id": fixture_id,
                    "repetition": row.get("repetition"),
                    "baseline": baseline,
                    "candidate": candidate,
                    "gates": gates,
                    "feedback": feedback,
                    "feedback_kinds": [_feedback_kind(value) for value in feedback],
                    "rubric_disagreement": disagreement,
                })
        except DesignEvaluationError as error:
            return _blocked_receipt(packet_digest, str(error), expected=manifest_receipts)
        by_fixture: dict[str, list[dict[str, Any]]] = {fixture_id: [] for fixture_id in expected_ids}
        for row in normalized_rows:
            repetition = row["repetition"]
            if not isinstance(repetition, int) or isinstance(repetition, bool) or repetition < 1:
                return _blocked_receipt(packet_digest, f"invalid_{split}_repetition", expected=manifest_receipts)
            if any(previous["repetition"] == repetition for previous in by_fixture[row["fixture_id"]]):
                return _blocked_receipt(packet_digest, f"duplicate_{split}_repetition", expected=manifest_receipts)
            by_fixture[row["fixture_id"]].append(row)
        minimum_repetitions = int(profile_doc["minimum_repetitions"])
        if any(len(rows_for_fixture) < minimum_repetitions for rows_for_fixture in by_fixture.values()):
            return _blocked_receipt(packet_digest, f"insufficient_{split}_repetitions", expected=manifest_receipts)
        normalized[split] = normalized_rows

    # Explicit synthetic inputs/results are allowed to produce a review packet,
    # but never to become active evidence by themselves.
    real_feedback = 0
    feedback_present = 0
    synthetic_only = True
    max_disagreement = 0.0
    unstable_fixtures: list[str] = []
    unstable_improvements: list[str] = []
    fixture_dimension_regressions: dict[str, dict[str, float]] = {}
    holdout_fixture_regressions: dict[str, float] = {}
    all_dimension_deltas: dict[str, list[float]] = {name: [] for name in weights}
    split_metrics: dict[str, Any] = {}
    hard_gate_failures: list[dict[str, Any]] = []

    for split, rows in normalized.items():
        by_fixture: dict[str, list[dict[str, Any]]] = {fixture_id: [] for fixture_id in fixture_maps[split]}
        for row in rows:
            by_fixture[row["fixture_id"]].append(row)
            kinds = row["feedback_kinds"]
            feedback_present += len(kinds)
            real_feedback += sum(kind == "real" for kind in kinds)
            if any(kind == "real" for kind in kinds):
                synthetic_only = False
            for gate, passed in row["gates"].items():
                if not passed:
                    hard_gate_failures.append({"split": split, "fixture_id": row["fixture_id"], "gate": gate})
            if row["rubric_disagreement"] is not None:
                max_disagreement = max(max_disagreement, float(row["rubric_disagreement"]))
        fixture_metrics: dict[str, Any] = {}
        weighted_deltas: list[tuple[float, float]] = []
        for fixture_id, fixture_rows in by_fixture.items():
            candidate_scores = [float(row["candidate"]["overall"]) for row in fixture_rows]
            if pstdev(candidate_scores) > float(profile_doc["maximum_score_stddev"]):
                unstable_fixtures.append(f"{split}:{fixture_id}")
            improvement_scores = [float(row["candidate"]["overall"]) - float(row["baseline"]["overall"]) for row in fixture_rows]
            if pstdev(improvement_scores) > float(profile_doc["maximum_score_stddev"]):
                unstable_improvements.append(f"{split}:{fixture_id}")
            aggregate_delta = mean(improvement_scores)
            fixture_weight = float(fixture_maps[split][fixture_id]["weight"])
            weighted_deltas.append((fixture_weight, aggregate_delta))
            if split == "holdout" and aggregate_delta < -float(profile_doc["maximum_holdout_regression"]):
                holdout_fixture_regressions[fixture_id] = aggregate_delta
            dimension_deltas: dict[str, float] = {}
            for name in weights:
                values: list[float] = []
                for row in fixture_rows:
                    candidate_value = row["candidate"]["dimensions"].get(name)
                    baseline_value = row["baseline"]["dimensions"].get(name)
                    if candidate_value is not None and baseline_value is not None:
                        values.append(float(candidate_value) - float(baseline_value))
                if values:
                    dimension_deltas[name] = mean(values)
                    all_dimension_deltas[name].extend(values)
            fixture_regressions = {
                name: delta for name, delta in dimension_deltas.items()
                if delta < -float(profile_doc["maximum_dimension_regression"])
            }
            if fixture_regressions:
                fixture_dimension_regressions[f"{split}:{fixture_id}"] = fixture_regressions
            fixture_metrics[fixture_id] = {
                "repetitions": len(fixture_rows),
                "baseline_mean": mean(float(row["baseline"]["overall"]) for row in fixture_rows),
                "candidate_mean": mean(candidate_scores),
                "improvement": aggregate_delta,
                "dimension_improvements": dimension_deltas,
            }
        denominator = sum(weight for weight, _delta in weighted_deltas)
        split_metrics[split] = {
            "fixtures": fixture_metrics,
            "weighted_aggregate_improvement": sum(weight * delta for weight, delta in weighted_deltas) / denominator if denominator else 0.0,
        }

    dev_metrics = split_metrics["development"]
    development_wins = [fixture_id for fixture_id, metrics in dev_metrics["fixtures"].items() if metrics["improvement"] >= float(profile_doc["minimum_effect_size"])]
    weighted_improvement = float(dev_metrics["weighted_aggregate_improvement"])
    development_feedback_gaps = sorted({
        row["fixture_id"]
        for row in normalized["development"]
        if not any(kind == "real" for kind in row["feedback_kinds"])
    })
    dimension_regressions = {
        name: delta for name, values in all_dimension_deltas.items() if values and (delta := mean(values)) < -float(profile_doc["maximum_dimension_regression"])
    }
    holdout_regression = bool(holdout_fixture_regressions) or float(split_metrics["holdout"]["weighted_aggregate_improvement"]) < -float(profile_doc["maximum_holdout_regression"])
    # A hard gate or a protected holdout regression always rejects a candidate,
    # even if the development score is otherwise a winner.
    if hard_gate_failures:
        reasons.append("hard_gate_failure")
    if holdout_regression:
        reasons.append("holdout_regression")
    if len(development_wins) < int(profile_doc["minimum_development_wins"]):
        reasons.append("insufficient_development_wins")
    if weighted_improvement < float(profile_doc["minimum_weighted_aggregate_improvement"]):
        reasons.append("insufficient_weighted_improvement")
    if dimension_regressions:
        reasons.append("dimension_regression")
    if fixture_dimension_regressions:
        reasons.append("fixture_dimension_regression")
    if profile_doc.get("required_task_feedback") and feedback_present == 0:
        reasons.append("missing_task_usefulness_feedback")
    elif profile_doc.get("required_task_feedback") and real_feedback == 0:
        reasons.append("missing_real_task_usefulness_feedback")
    elif profile_doc.get("required_task_feedback") and development_feedback_gaps:
        reasons.append("incomplete_real_task_usefulness_feedback")
    if unstable_fixtures or unstable_improvements:
        reasons.append("unstable_scores")
    if max_disagreement > float(profile_doc["maximum_rubric_disagreement"]):
        reasons.append("rubric_usefulness_disagreement")

    if feedback_present == 0:
        status = "blocked-eval"
    elif "hard_gate_failure" in reasons or "holdout_regression" in reasons or "fixture_dimension_regression" in reasons:
        status = "rejected"
    elif unstable_fixtures or unstable_improvements or max_disagreement > float(profile_doc["maximum_rubric_disagreement"]):
        status = "human_review_required"
    elif real_feedback == 0 or development_feedback_gaps:
        status = "human_review_required"
    elif reasons:
        # A complete harness with a weak candidate is a terminal rejection. A
        # missing feedback field was handled as a blocked harness above; an
        # explicitly synthetic feedback set remains review-only below.
        status = "rejected"
    else:
        status = "awaiting_approval"
    if synthetic_only and status == "awaiting_approval":
        reasons.append("synthetic_evidence_requires_real_task_use")

    receipt = {
        "schema_version": 1,
        "receipt_kind": "design-learning-evaluation",
        "status": status,
        "candidate_packet_digest": packet_digest,
        "materialization_receipt_digest": digest_json(materialization_receipt),
        "profile": "design-learning-v1",
        "harness": {"environment": profile_doc.get("harness_environment", "STACK_DESIGN_EVAL_ROOT"), "complete": True, "root_present": True},
        "manifests": manifest_receipts,
        "results": {split: {"digest": result_digests[split], "quarantined": True} for split in result_digests},
        "metrics": {
            "development_wins": sorted(development_wins),
            "development_win_count": len(development_wins),
            "development_weighted_aggregate_improvement": weighted_improvement,
            "dimension_regressions": dimension_regressions,
            "fixture_dimension_regressions": fixture_dimension_regressions,
            "holdout_fixture_regressions": holdout_fixture_regressions,
            "holdout_weighted_aggregate_improvement": split_metrics["holdout"]["weighted_aggregate_improvement"],
            "rotating_canary_weighted_aggregate_improvement": split_metrics["rotating_canary"]["weighted_aggregate_improvement"],
            "hard_gate_failures": hard_gate_failures,
            "unstable_fixtures": sorted(unstable_fixtures),
            "unstable_improvements": sorted(unstable_improvements),
            "maximum_rubric_usefulness_disagreement": max_disagreement,
            "real_task_usefulness_feedback_count": real_feedback,
            "task_usefulness_feedback_count": feedback_present,
            "development_feedback_gaps": development_feedback_gaps,
            "synthetic_only": synthetic_only,
            "splits": split_metrics,
        },
        "gates": {
            "minimum_repetitions": True,
            "development_wins": len(development_wins) >= int(profile_doc["minimum_development_wins"]),
            "weighted_aggregate_improvement": weighted_improvement >= float(profile_doc["minimum_weighted_aggregate_improvement"]),
            "dimension_regression": not dimension_regressions,
            "holdout_regression": not holdout_regression,
            "hard_gates": not hard_gate_failures,
            "task_usefulness_feedback": feedback_present > 0,
            "score_stability": not unstable_fixtures,
            "rubric_usefulness_agreement": max_disagreement <= float(profile_doc["maximum_rubric_disagreement"]),
        },
        "reason_codes": sorted(set(reasons)),
        "quarantine": {"results_owner_local": True, "candidate_outputs": True, "retrieval_truth": False, "future_fixtures": False},
        "activation": {"active_pointer": False, "install": False, "publish": False, "draft_pr": False, "network_action": False},
        "next_gate": "human-review-and-publication-receipts" if status == "awaiting_approval" else "human-review" if status == "human_review_required" else "revise-or-discard-candidate",
    }
    return receipt


def evaluate(
    packet_path: Path,
    materialization_path: Path,
    manifest_paths: Mapping[str, Path] | None = None,
    result_paths: Mapping[str, Path] | None = None,
    profiles_path: Path = ROOT / "config" / "candidate-evaluation-profiles.json",
    profile_name: str = "design-learning-v1",
    output_path: Path | None = None,
    harness_root: Path | None = None,
) -> dict[str, Any]:
    packet = load_object(packet_path, "candidate packet")
    materialization = load_object(materialization_path, "materialization receipt")
    profiles = load_object(profiles_path, "candidate evaluation profiles")
    selected = _profile(profiles, profile_name)
    manifests = dict(manifest_paths or {})
    results = dict(result_paths or {})
    receipt = evaluate_design_candidate(packet, materialization, manifests=manifests, results=results, profile=selected, harness_root=harness_root)
    if output_path is not None:
        target, _ = _owner_output(output_path)
        _write_idempotent(target, canonical_json(receipt).encode("utf-8"))
    return receipt


evaluate_candidate = evaluate_design_candidate
evaluate_design_intelligence_candidate = evaluate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--materialization-receipt", "--receipt", dest="materialization", type=Path, required=True)
    parser.add_argument("--development-manifest", type=Path)
    parser.add_argument("--holdout-manifest", type=Path)
    parser.add_argument("--rotating-canary-manifest", type=Path)
    parser.add_argument("--development-results", type=Path)
    parser.add_argument("--holdout-results", type=Path)
    parser.add_argument("--rotating-canary-results", type=Path)
    parser.add_argument("--profiles", type=Path, default=ROOT / "config" / "candidate-evaluation-profiles.json")
    parser.add_argument("--profile", default="design-learning-v1")
    parser.add_argument("--harness-root", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifests = {
            key: value for key, value in {
                "development": args.development_manifest,
                "holdout": args.holdout_manifest,
                "rotating_canary": args.rotating_canary_manifest,
            }.items() if value is not None
        }
        results = {
            key: value for key, value in {
                "development": args.development_results,
                "holdout": args.holdout_results,
                "rotating_canary": args.rotating_canary_results,
            }.items() if value is not None
        }
        receipt = evaluate(
            args.packet, args.materialization, manifest_paths=manifests, result_paths=results,
            profiles_path=args.profiles, profile_name=args.profile, output_path=args.out, harness_root=args.harness_root,
        )
    except (DesignEvaluationError, OSError, TypeError, KeyError) as error:
        print(f"design candidate evaluation failed closed: {error}", file=sys.stderr)
        return 2
    print(canonical_json({"status": receipt["status"], "output": str(args.out)}), end="")
    # A receipt is useful even for a blocked/rejected/human-review result, but
    # only an all-gates-passing candidate reaches the prepared review state.
    return 0 if receipt["status"] == "awaiting_approval" else 3


if __name__ == "__main__":
    raise SystemExit(main())
