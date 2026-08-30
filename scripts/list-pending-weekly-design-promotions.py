#!/usr/bin/env python3
"""List unresolved weekly design promotion retries without exposing content.

The promotion recorder is append-only. A candidate digest is pending when at
least one accepted receipt says ``retry_with_alert`` and no accepted receipt
for that same campaign and candidate says ``published`` or
``rejected_no_queue``. This command returns only opaque identifiers and
owner-local decision file names so the scheduler can resume before collecting
new evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


AUTHORIZATION_CONTRACT = "weekly-design-auto-promotion-approved-v1"
HEX64 = re.compile(r"^[a-f0-9]{64}$")
SAFE_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
MAX_CONTROL_BYTES = 1024 * 1024


class PendingPromotionError(ValueError):
    """The retry inventory cannot be trusted."""


def _owner_directory(path: Path, label: str) -> Path | None:
    resolved = Path(os.path.abspath(str(path.expanduser())))
    if not resolved.exists():
        return None
    if resolved.is_symlink():
        raise PendingPromotionError(f"{label} may not be a symlink")
    details = resolved.stat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise PendingPromotionError(f"{label} must be an owner-only 0700 directory")
    return resolved


def _private_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    if path.is_symlink():
        raise PendingPromotionError(f"{label} may not be a symlink")
    try:
        details = path.stat()
    except OSError as error:
        raise PendingPromotionError(f"{label} is unavailable") from error
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_size > MAX_CONTROL_BYTES
    ):
        raise PendingPromotionError(f"{label} must be an owner-only bounded control file")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PendingPromotionError(f"{label} is not readable JSON") from error
    if not isinstance(value, dict):
        raise PendingPromotionError(f"{label} must be a JSON object")
    return value, hashlib.sha256(raw).hexdigest()


def _receipt_identity(
    document: Mapping[str, Any],
    filename: str,
    file_digest: str,
) -> tuple[str, str, str] | None:
    if (
        document.get("schema_version") != 1
        or document.get("receipt_kind") != "weekly-design-automatic-promotion"
        or document.get("authorization_contract") != AUTHORIZATION_CONTRACT
    ):
        raise PendingPromotionError("promotion receipt identity is invalid")
    campaign = document.get("campaign")
    candidate = document.get("candidate")
    disposition = document.get("disposition")
    if not isinstance(campaign, Mapping) or not isinstance(candidate, Mapping):
        raise PendingPromotionError("promotion receipt campaign or candidate is invalid")
    run_id = campaign.get("run_id")
    if not isinstance(run_id, str) or SAFE_RUN_ID.fullmatch(run_id) is None:
        raise PendingPromotionError("promotion receipt campaign identity is invalid")
    if candidate.get("state") == "absent" and disposition == "no_action":
        if filename != f"{run_id}.json":
            raise PendingPromotionError("no_action receipt filename is invalid")
        return None
    candidate_digest = candidate.get("digest")
    if (
        candidate.get("state") != "selected"
        or not isinstance(candidate_digest, str)
        or HEX64.fullmatch(candidate_digest) is None
        or disposition not in {"published", "rejected_no_queue", "retry_with_alert"}
    ):
        raise PendingPromotionError("promotion receipt candidate identity is invalid")
    expected_name = f"{run_id}--{candidate_digest}--{file_digest}.json"
    legacy_name = f"{run_id}.json"
    if filename not in {expected_name, legacy_name}:
        raise PendingPromotionError("promotion receipt filename digest is invalid")
    return run_id, candidate_digest, disposition


def pending_promotions(receipts_dir: Path, decisions_dir: Path) -> dict[str, Any]:
    receipts = _owner_directory(receipts_dir, "promotion receipt directory")
    decisions = _owner_directory(decisions_dir, "promotion decision directory")
    if receipts is None:
        return {"status": "ready", "pending": [], "count": 0}

    retries: set[tuple[str, str]] = set()
    completed: set[tuple[str, str]] = set()
    for path in sorted(receipts.glob("*.json")):
        document, file_digest = _private_json(path, "promotion receipt")
        identity = _receipt_identity(document, path.name, file_digest)
        if identity is None:
            continue
        run_id, candidate_digest, disposition = identity
        key = (run_id, candidate_digest)
        if disposition == "retry_with_alert":
            retries.add(key)
        else:
            completed.add(key)

    pending = sorted(retries - completed)
    decision_names: dict[tuple[str, str], list[str]] = {key: [] for key in pending}
    if decisions is not None:
        for path in sorted(decisions.glob("*.json")):
            document, decision_digest = _private_json(path, "promotion decision")
            candidate = document.get("candidate")
            if not (
                document.get("authorization_contract") == AUTHORIZATION_CONTRACT
                and document.get("disposition") == "retry_with_alert"
                and isinstance(candidate, Mapping)
                and isinstance(candidate.get("digest"), str)
            ):
                continue
            for key in pending:
                run_id, candidate_digest = key
                expected_name = f"{run_id}--{candidate_digest}--{decision_digest}.json"
                legacy_name = f"{run_id}.json"
                if candidate["digest"] == candidate_digest and path.name in {
                    expected_name,
                    legacy_name,
                }:
                    decision_names[key].append(path.name)

    rows = [
        {
            "campaign_run_id": run_id,
            "candidate_digest": candidate_digest,
            "decision_files": decision_names[(run_id, candidate_digest)],
        }
        for run_id, candidate_digest in pending
    ]
    missing = [
        {"campaign_run_id": row["campaign_run_id"], "candidate_digest": row["candidate_digest"]}
        for row in rows
        if not row["decision_files"]
    ]
    return {
        "status": "blocked" if missing else "ready",
        "pending": rows,
        "count": len(rows),
        "missing_decisions": missing,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    state = Path("~/.local/state/stack/weekly-intelligence").expanduser()
    parser.add_argument("--receipts-dir", type=Path, default=state / "promotion-receipts")
    parser.add_argument("--decisions-dir", type=Path, default=state / "promotion-decisions")
    args = parser.parse_args(argv)
    try:
        result = pending_promotions(args.receipts_dir, args.decisions_dir)
    except PendingPromotionError as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
