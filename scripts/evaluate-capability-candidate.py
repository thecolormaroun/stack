#!/usr/bin/env python3
"""Evaluate an exact candidate commit in a credential-free disposable sandbox.

The evaluator never runs candidate-provided commands. A reviewed, repository-
owned profile determines the structural checks. The candidate tree is exported
from an immutable Git commit, copied into a temporary workspace, inspected by a
trusted worker under ``sandbox-exec``, and discarded. Only a bounded receipt is
written to the requested output path.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import resource
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PIN = re.compile(r"[a-f0-9]{40,64}$")
PROFILE_NAME = re.compile(r"[a-z0-9][a-z0-9-]*$")
ALLOWED_REVIEW_STATES = {"approved"}
AMBIENT_CREDENTIAL_KEYS = {
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "GH_TOKEN",
    "GOOGLE_APPLICATION_CREDENTIALS", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
}


class EvaluationError(ValueError):
    """A candidate cannot be evaluated without weakening the contract."""


def canonical_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_json(value: object) -> str:
    return digest_bytes(canonical_json(value).encode("utf-8"))


def load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvaluationError(f"{label} is not readable JSON") from error
    if not isinstance(value, dict):
        raise EvaluationError(f"{label} must be a JSON object")
    return value


def validate_packet(packet: dict[str, Any]) -> None:
    if packet.get("schema_version") != 1 or packet.get("packet_kind") != "capability-evaluation-candidate":
        raise EvaluationError("candidate packet has an unsupported contract")
    evaluation = packet.get("evaluation")
    if not isinstance(evaluation, dict) or evaluation.get("status") != "blocked-pending-provenance-and-evaluation-review":
        raise EvaluationError("candidate packet is not blocked at the evaluation gate")
    if packet.get("activation") != "prohibited-until-separate-publication-review":
        raise EvaluationError("candidate packet does not prohibit activation")
    pin = packet.get("source_pin")
    if not isinstance(pin, str) or not PIN.fullmatch(pin):
        raise EvaluationError("candidate packet requires an immutable source pin")


def validate_review(review: dict[str, Any], packet: dict[str, Any], profile_name: str) -> None:
    required = {
        "schema_version", "packet_digest", "source_pin", "profile",
        "provenance_review", "evaluation_execution_review", "reviewed_by", "reviewed_at",
    }
    if set(review) != required or review.get("schema_version") != 1:
        raise EvaluationError("evaluation authorization has unsupported or missing fields")
    if review.get("packet_digest") != digest_json(packet):
        raise EvaluationError("evaluation authorization does not match the candidate packet")
    if review.get("source_pin") != packet.get("source_pin"):
        raise EvaluationError("evaluation authorization does not match the source pin")
    if review.get("profile") != profile_name:
        raise EvaluationError("evaluation authorization does not match the profile")
    if review.get("provenance_review") not in ALLOWED_REVIEW_STATES:
        raise EvaluationError("provenance review is not approved")
    if review.get("evaluation_execution_review") not in ALLOWED_REVIEW_STATES:
        raise EvaluationError("evaluation execution review is not approved")
    if not isinstance(review.get("reviewed_by"), str) or not review["reviewed_by"].strip():
        raise EvaluationError("evaluation authorization requires a reviewer")
    try:
        datetime.fromisoformat(str(review.get("reviewed_at")).replace("Z", "+00:00"))
    except ValueError as error:
        raise EvaluationError("evaluation authorization requires an ISO timestamp") from error


def load_profile(path: Path, profile_name: str) -> dict[str, Any]:
    document = load_object(path, "evaluation profiles")
    profiles = document.get("profiles")
    if document.get("schema_version") != 1 or not isinstance(profiles, dict):
        raise EvaluationError("evaluation profiles have an unsupported contract")
    profile = profiles.get(profile_name)
    if not isinstance(profile, dict) or not PROFILE_NAME.fullmatch(profile_name):
        raise EvaluationError("unknown evaluation profile")
    required = {"artifact_type", "required_paths", "max_files", "max_total_bytes", "forbid_executable_files"}
    if set(profile) != required:
        raise EvaluationError("evaluation profile has unsupported or missing fields")
    paths = profile.get("required_paths")
    if not isinstance(paths, list) or not paths or not all(
        isinstance(item, str) and item and not Path(item).is_absolute() and ".." not in Path(item).parts
        for item in paths
    ):
        raise EvaluationError("evaluation profile required_paths are unsafe")
    if not isinstance(profile.get("max_files"), int) or not 1 <= profile["max_files"] <= 2000:
        raise EvaluationError("evaluation profile max_files is unsafe")
    if not isinstance(profile.get("max_total_bytes"), int) or not 1 <= profile["max_total_bytes"] <= 64 * 1024 * 1024:
        raise EvaluationError("evaluation profile max_total_bytes is unsafe")
    if profile.get("forbid_executable_files") is not True:
        raise EvaluationError("evaluation profile must reject executable candidate files")
    return profile


def git_archive(repository: Path, pin: str, *, max_files: int, max_total_bytes: int) -> bytes:
    if not repository.is_dir() or repository.is_symlink():
        raise EvaluationError("candidate source repository must be a real directory")
    try:
        subprocess.run(
            ["git", "-C", str(repository), "cat-file", "-e", f"{pin}^{{commit}}"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
        )
        listing = subprocess.run(
            ["git", "-C", str(repository), "ls-tree", "-rlz", "--full-tree", pin],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
        ).stdout
        records = [record for record in listing.split(b"\0") if record]
        total_bytes = 0
        for record in records:
            metadata = record.split(b"\t", 1)[0].split()
            if len(metadata) != 4 or metadata[1] != b"blob" or not metadata[3].isdigit():
                raise EvaluationError("candidate source contains an unsupported Git object")
            total_bytes += int(metadata[3])
        if len(records) > max_files or total_bytes > max_total_bytes:
            raise EvaluationError("candidate source exceeds the evaluation profile limits")
        result = subprocess.run(
            ["git", "-C", str(repository), "archive", "--format=tar", pin],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise EvaluationError("candidate source pin is unavailable from the local repository") from error
    return result.stdout


def apply_process_limits() -> None:
    """Bound the trusted worker even if a platform sandbox regression occurs."""
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def extract_archive(archive: bytes, destination: Path) -> None:
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as value:
            members = value.getmembers()
            for member in members:
                relative = Path(member.name)
                if relative.is_absolute() or ".." in relative.parts or member.issym() or member.islnk() or member.isdev():
                    raise EvaluationError("candidate archive contains an unsafe path or link")
            value.extractall(destination, filter="data")
    except (tarfile.TarError, OSError) as error:
        raise EvaluationError("candidate archive cannot be safely extracted") from error


def sandbox_profile(workspace: Path, forbidden_read: Path, forbidden_write: Path) -> str:
    def literal(path: Path) -> str:
        return str(path.resolve()).replace("\\", "\\\\").replace('"', '\\"')

    home = Path.home().resolve()
    return " ".join(
        [
            "(version 1)",
            "(deny default)",
            "(allow process*)",
            "(allow file-read*)",
            f'(deny file-read* (subpath "{literal(home)}"))',
            '(deny file-read* (subpath "/Volumes"))',
            '(deny file-read* (subpath "/Network"))',
            f'(deny file-read* (literal "{literal(forbidden_read)}"))',
            f'(allow file-read* (subpath "{literal(workspace)}"))',
            f'(allow file-write* (subpath "{literal(workspace)}"))',
            f'(deny file-write* (literal "{literal(forbidden_write)}"))',
            '(allow file-write-data (literal "/dev/null"))',
            "(deny network*)",
        ]
    )


def sandbox_worker(job_path: Path) -> int:
    """Trusted worker entrypoint. Candidate files are data and never executed."""
    job = load_object(job_path, "sandbox job")
    bundle = Path(job["bundle"])
    output = Path(job["output"])
    profile = job["profile"]
    forbidden_read = Path(job["forbidden_read"])
    forbidden_write = Path(job["forbidden_write"])

    probes: dict[str, bool] = {}
    try:
        forbidden_read.read_bytes()
        probes["parent_workspace_read_denied"] = False
    except OSError as error:
        probes["parent_workspace_read_denied"] = error.errno in {1, 13}
    try:
        forbidden_write.write_text("escape", encoding="utf-8")
        probes["outside_write_denied"] = False
    except OSError as error:
        probes["outside_write_denied"] = error.errno in {1, 13}
    try:
        connection = socket.socket()
        try:
            connection.settimeout(0.1)
            connection.connect(("127.0.0.1", 9))
            probes["network_denied"] = False
        finally:
            connection.close()
    except OSError as error:
        probes["network_denied"] = error.errno in {1, 13}
    probes["ambient_credentials_absent"] = not (AMBIENT_CREDENTIAL_KEYS & set(os.environ))

    records: list[str] = []
    executable_files: list[str] = []
    total_bytes = 0
    for path in sorted(bundle.rglob("*")):
        if path.is_symlink():
            raise EvaluationError("candidate bundle contains a symlink")
        if not path.is_file():
            continue
        relative = path.relative_to(bundle).as_posix()
        size = path.stat().st_size
        total_bytes += size
        records.append(f"{relative}:{size}:{digest_bytes(path.read_bytes())}")
        if stat.S_IMODE(path.stat().st_mode) & 0o111:
            executable_files.append(relative)

    required = profile["required_paths"]
    missing = [item for item in required if not (bundle / item).is_file()]
    checks = {
        "required_paths_present": not missing,
        "file_limit_passed": len(records) <= profile["max_files"],
        "byte_limit_passed": total_bytes <= profile["max_total_bytes"],
        "no_executable_candidate_files": not executable_files,
        "skill_document_nonempty": (bundle / "SKILL.md").is_file() and bool((bundle / "SKILL.md").read_text(encoding="utf-8").strip()),
    }
    try:
        capability = json.loads((bundle / "capability.json").read_text(encoding="utf-8"))
        checks["capability_manifest_is_object"] = isinstance(capability, dict)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        checks["capability_manifest_is_object"] = False

    passed = all(probes.values()) and all(checks.values())
    result = {
        "schema_version": 1,
        "status": "passed" if passed else "failed",
        "sandbox": probes,
        "checks": checks,
        "artifact": {
            "file_count": len(records),
            "total_bytes": total_bytes,
            "tree_digest": digest_bytes("\n".join(records).encode("utf-8")),
        },
    }
    output.write_text(canonical_json(result), encoding="utf-8")
    return 0 if passed else 3


def run_evaluation(
    packet_path: Path,
    review_path: Path,
    source_repository: Path,
    profiles_path: Path,
    profile_name: str,
    output_path: Path,
) -> dict[str, Any]:
    if sys.platform != "darwin" or shutil.which("sandbox-exec") is None:
        raise EvaluationError("a supported fail-closed sandbox backend is unavailable")
    packet = load_object(packet_path, "candidate packet")
    validate_packet(packet)
    profile = load_profile(profiles_path, profile_name)
    review = load_object(review_path, "evaluation authorization")
    validate_review(review, packet, profile_name)
    archive = git_archive(
        source_repository.resolve(), packet["source_pin"],
        max_files=profile["max_files"], max_total_bytes=profile["max_total_bytes"],
    )

    with tempfile.TemporaryDirectory(prefix="stack-candidate-eval-") as temporary:
        outer = Path(temporary)
        os.chmod(outer, 0o700)
        forbidden_read = outer / "outside-read-sentinel"
        forbidden_write = outer / "outside-write-sentinel"
        forbidden_read.write_text("not available to evaluator", encoding="utf-8")
        forbidden_write.write_text("must remain unchanged", encoding="utf-8")
        workspace = outer / "workspace"
        workspace.mkdir(mode=0o700)
        bundle = workspace / "candidate"
        bundle.mkdir(mode=0o700)
        extract_archive(archive, bundle)
        worker = workspace / "worker.py"
        shutil.copy2(Path(__file__), worker)
        result_path = workspace / "evaluation-result.json"
        job_path = workspace / "job.json"
        job = {
            "bundle": str(bundle),
            "output": str(result_path),
            "profile": profile,
            "forbidden_read": str(forbidden_read),
            "forbidden_write": str(forbidden_write),
        }
        job_path.write_text(canonical_json(job), encoding="utf-8")
        environment = {
            "HOME": str(workspace / "empty-home"),
            "LANG": "C.UTF-8",
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "TMPDIR": str(workspace),
        }
        command = [
            "/usr/bin/sandbox-exec", "-p", sandbox_profile(workspace, forbidden_read, forbidden_write),
            "/usr/bin/python3", str(worker), "--sandbox-worker", str(job_path),
        ]
        try:
            completed = subprocess.run(
                command,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                preexec_fn=apply_process_limits,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise EvaluationError("sandbox evaluation did not complete") from error
        if completed.returncode not in {0, 3} or not result_path.is_file():
            raise EvaluationError("sandbox evaluation failed without a valid artifact")
        result = load_object(result_path, "sandbox result")
        if set(result) != {"schema_version", "status", "sandbox", "checks", "artifact"} or result.get("schema_version") != 1:
            raise EvaluationError("sandbox returned an unsupported result")
        if result.get("status") not in {"passed", "failed"}:
            raise EvaluationError("sandbox returned an invalid status")
        if not isinstance(result.get("sandbox"), dict) or not all(isinstance(value, bool) for value in result["sandbox"].values()):
            raise EvaluationError("sandbox returned invalid enforcement evidence")
        if not isinstance(result.get("checks"), dict) or not all(isinstance(value, bool) for value in result["checks"].values()):
            raise EvaluationError("sandbox returned invalid check evidence")
        if result["status"] == "passed" and (not all(result["sandbox"].values()) or not all(result["checks"].values())):
            raise EvaluationError("sandbox result contradicts its passed status")
        if forbidden_write.read_text(encoding="utf-8") != "must remain unchanged":
            raise EvaluationError("sandbox wrote outside its workspace")

    receipt = {
        "schema_version": 1,
        "receipt_kind": "capability-evaluation",
        "candidate_packet_digest": digest_json(packet),
        "source_pin": packet["source_pin"],
        "profile": profile_name,
        "status": result.get("status"),
        "sandbox": result.get("sandbox"),
        "limits": {
            "cpu_seconds": 10,
            "wall_seconds": 30,
            "max_output_bytes": 8388608,
            "max_files": profile["max_files"],
            "max_candidate_bytes": profile["max_total_bytes"],
        },
        "checks": result.get("checks"),
        "artifact": result.get("artifact"),
        "evaluated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "activation": "prohibited-pending-result-review-and-publication-review",
        "next_gate": "human-evaluation-result-review",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(canonical_json(receipt), encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--source-repository", type=Path)
    parser.add_argument("--profiles", type=Path, default=ROOT / "config/candidate-evaluation-profiles.json")
    parser.add_argument("--profile", default="skill-structure-v1")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--sandbox-worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.sandbox_worker:
        try:
            return sandbox_worker(args.sandbox_worker)
        except (EvaluationError, OSError, KeyError, TypeError, UnicodeDecodeError):
            return 4
    if not all((args.packet, args.review, args.source_repository, args.out)):
        parser.error("--packet, --review, --source-repository, and --out are required")
    try:
        receipt = run_evaluation(
            args.packet, args.review, args.source_repository, args.profiles,
            args.profile, args.out,
        )
    except (EvaluationError, OSError, TypeError, KeyError) as error:
        print(f"candidate evaluation failed closed: {error}", file=sys.stderr)
        return 2
    print(canonical_json({"status": receipt["status"], "receipt": str(args.out)}), end="")
    return 0 if receipt["status"] == "passed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
