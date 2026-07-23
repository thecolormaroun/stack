#!/usr/bin/env python3
"""Prepare a blocked capability-evaluation packet; never evaluate or activate."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRIAGE_PATH = ROOT / "scripts/triage-bookmark-candidates.py"
SPEC = importlib.util.spec_from_file_location("bookmark_triage", TRIAGE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load bookmark triage safeguards")
TRIAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRIAGE)
PIN = re.compile(r"(?:sha256:)?[a-f0-9]{40,64}$")


class PreparationError(ValueError):
    pass


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def prepare(candidate: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise PreparationError("candidate must be an object")
    if candidate.get("review_state") not in {None, "blocked-pending-human-review"}:
        raise PreparationError("candidate must remain blocked pending human review")
    pin = candidate.get("source_pin")
    if not isinstance(pin, str) or not PIN.fullmatch(pin):
        raise PreparationError("immutable source_pin is required")
    sandbox = policy.get("evaluation", {})
    expected = {
        "network": "deny", "ambient_credentials": "deny", "private_corpus_mounts": "deny",
        "writes": "temporary-workspace-only", "artifact_output_only": True,
    }
    if any(sandbox.get(key) != value for key, value in expected.items()):
        raise PreparationError("policy sandbox contract is unsafe")
    leaks = TRIAGE.contains_private_field(candidate)
    # The pin is intentionally allowed as an immutable provenance reference.
    leaks = [leak for leak in leaks if leak not in {"source_pin"}]
    if leaks:
        raise PreparationError("candidate leak check failed: " + ", ".join(leaks))
    if candidate.get("disposition") in {"blocked-import", "no-action"}:
        raise PreparationError("candidate is not eligible for evaluation")
    if any(candidate.get(key) for key in ("requested_actions", "evaluation_command", "sandbox_overrides")):
        raise PreparationError("candidate cannot request execution privileges")
    dependencies = candidate.get("dependencies", [])
    allowed = policy.get("allowed_evaluation_dependencies", [])
    if not isinstance(dependencies, list) or not all(dep in allowed for dep in dependencies):
        raise PreparationError("candidate dependencies are not explicitly allowlisted")
    return {
        "schema_version": 1,
        "packet_kind": "capability-evaluation-candidate",
        "intake_id": candidate.get("intake_id"),
        "disposition": candidate.get("disposition"),
        "source_pin": pin,
        "prior_provenance": candidate.get("prior_provenance"),
        "evaluation": {
            "sandbox": sandbox,
            "status": "blocked-pending-provenance-and-evaluation-review",
            "human_gates": policy.get("review_gates", []),
        },
        "activation": "prohibited-until-separate-publication-review",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=ROOT / "config/capability-activation-policy.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        packet = prepare(load(args.candidate), load(args.policy))
        leaks = TRIAGE.contains_private_field(packet)
        if leaks:
            raise PreparationError("prepared packet leak check failed")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"candidate preparation failed closed: {error}", file=sys.stderr)
        return 2
    args.out.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
