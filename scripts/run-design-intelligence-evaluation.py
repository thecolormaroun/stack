#!/usr/bin/env python3
"""Capture owner-local browser observations from a pinned JSON manifest.

Manifest v1 binds synthetic, non-private task/artifact inputs and a viewport
by absolute path and SHA-256. Optional primary_workflow steps allow
click/check/uncheck/allowlisted-key actions plus explicit UI assertions. No
text entry, human feedback interpretation, score, judge, or promotion is
implemented. The caller supplies the reviewed raw-manifest SHA-256. Outputs
are owner-only; browser request routing is not whole-process egress isolation.
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[1]
HEX64 = re.compile(r"^[a-f0-9]{64}$")
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SCRIPT_DIR = Path(__file__).resolve().parent
EVALUATOR_PATH = SCRIPT_DIR / "evaluate-design-intelligence-candidate.py"
RUN_STATE_PATH = SCRIPT_DIR / "stack-run-state.py"
DEFAULT_OUTPUT = Path.home() / ".local/state/stack/design-intelligence/evidence-runs"
ALLOWED_BROWSER_EXECUTABLES = {
    "/opt/homebrew/bin/agent-browser",
    "/usr/local/bin/agent-browser",
}
ALLOWED_ACTIONS = {"click", "check", "uncheck", "press"}
ALLOWED_KEYS = {"Enter", "Tab", "Escape", "Space", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"}
ALLOWED_ASSERTIONS = {"visible", "enabled", "checked", "text_contains", "count_is"}
MAX_MANIFEST_BYTES = 1_000_000
MAX_ASSET_BYTES = 25_000_000
MAX_INLINE_HTML_BYTES = 64_000
LEASE_SECONDS = 900
OFFLINE_POLICY = "self-contained-data-url-csp-and-abort-external-requests"
EXECUTOR_POLICY_REVISION = "synthetic-inline-v2"
REQUEST_ABORT_ROUTES = ("http://**", "https://**", "file://**")
CSP_META = (b'<meta http-equiv="Content-Security-Policy" content="'
            b"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            b"img-src data:; font-src data:; media-src data:; connect-src 'none'; "
            b"frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'\">")


class EvidenceError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise EvidenceError("project_utility_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HELPER_PATHS = {"evaluator": EVALUATOR_PATH, "workflow_store": RUN_STATE_PATH}
LOADED_HELPER_DIGESTS = {
    name: hashlib.sha256(path.read_bytes()).hexdigest()
    for name, path in HELPER_PATHS.items()
}
_eval = _load_module("_stack_design_evaluator_for_evidence", EVALUATOR_PATH)
_run_state = _load_module("_stack_run_state_for_design_evidence", RUN_STATE_PATH)


canonical_json = _eval.canonical_json
digest_bytes = _eval.digest_bytes
digest_file = _eval.digest_file


def _helper_digests() -> dict[str, str]:
    try:
        actual = {name: digest_file(path) for name, path in HELPER_PATHS.items()}
    except OSError:
        raise EvidenceError("execution_helper_unavailable") from None
    if actual != LOADED_HELPER_DIGESTS:
        raise EvidenceError("execution_helper_drift")
    return actual


def _object(value: Any, keys: set[str], label: str, *, optional: set[str] = frozenset()) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not keys <= set(value) or set(value) - keys - set(optional):
        raise EvidenceError(f"unsupported_{label}")
    return dict(value)


def _asset_ref(value: Any, label: str) -> tuple[dict[str, str], Path]:
    raw = _object(value, {"path", "sha256"}, label)
    if not isinstance(raw["path"], str) or not Path(raw["path"]).is_absolute():
        raise EvidenceError(f"invalid_{label}_path")
    if not isinstance(raw["sha256"], str) or HEX64.fullmatch(raw["sha256"]) is None:
        raise EvidenceError(f"invalid_{label}_digest")
    path = Path(raw["path"])
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ASSET_BYTES:
            raise EvidenceError(f"invalid_{label}_file")
        actual = digest_file(path)
    except EvidenceError:
        raise
    except Exception:
        raise EvidenceError(f"unreadable_{label}") from None
    if actual != raw["sha256"]:
        raise EvidenceError(f"{label}_digest_mismatch")
    return {"sha256": actual}, path.resolve(strict=True)


def _validate_workflow(value: Any, case_index: int) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 25:
        raise EvidenceError("unsupported_primary_workflow")
    validated: list[dict[str, Any]] = []
    for step in value:
        row = _object(step, {"action", "selector", "assertions"}, f"workflow_step_{case_index}", optional={"key"})
        if row["action"] not in ALLOWED_ACTIONS or not isinstance(row["selector"], str) or not row["selector"].strip() or len(row["selector"]) > 512 or "\x00" in row["selector"]:
            raise EvidenceError("unsupported_primary_action")
        if row["action"] == "press":
            if row.get("key") not in ALLOWED_KEYS:
                raise EvidenceError("unsupported_primary_key")
        elif "key" in row:
            raise EvidenceError("unsupported_primary_action_field")
        assertions = row["assertions"]
        if not isinstance(assertions, list) or not assertions or len(assertions) > 10:
            raise EvidenceError("primary_action_requires_assertions")
        for assertion in assertions:
            check = _object(assertion, {"kind", "selector"}, "workflow_assertion", optional={"value"})
            if check["kind"] not in ALLOWED_ASSERTIONS or not isinstance(check["selector"], str) or not check["selector"].strip() or len(check["selector"]) > 512 or "\x00" in check["selector"]:
                raise EvidenceError("unsupported_primary_assertion")
            if check["kind"] == "text_contains":
                if not isinstance(check.get("value"), str) or not check["value"] or len(check["value"]) > 512:
                    raise EvidenceError("invalid_text_assertion")
            elif check["kind"] == "count_is":
                if not isinstance(check.get("value"), int) or not 0 <= check["value"] <= 100_000:
                    raise EvidenceError("invalid_count_assertion")
            elif "value" in check:
                raise EvidenceError("unsupported_assertion_field")
        validated.append(row)
    return validated


def validate_manifest(document: Any, *, manifest_path: Path, manifest_digest: str) -> dict[str, Any]:
    raw = _object(
        document,
        {"schema_version", "run_id", "content_scope", "offline_asset_policy", "browser", "cases"},
        "manifest",
    )
    if raw["schema_version"] != 1 or not isinstance(raw["run_id"], str) or SAFE_ID.fullmatch(raw["run_id"]) is None:
        raise EvidenceError("unsupported_manifest_identity")
    if raw["content_scope"] != "synthetic_non_private":
        raise EvidenceError("private_artifacts_require_egress_isolation")
    if raw["offline_asset_policy"] != OFFLINE_POLICY:
        raise EvidenceError("unsupported_offline_policy")
    browser = _object(raw["browser"], {"executable", "arguments"}, "browser")
    if browser["executable"] not in ALLOWED_BROWSER_EXECUTABLES:
        raise EvidenceError("browser_executable_not_allowlisted")
    if browser["arguments"] != []:
        raise EvidenceError("browser_arguments_not_allowlisted")
    executable = Path(browser["executable"])
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise EvidenceError("browser_executable_unavailable")
    try:
        executable = executable.resolve(strict=True)
        executable_digest = digest_file(executable)
    except Exception:
        raise EvidenceError("browser_executable_unavailable") from None

    cases = raw["cases"]
    if not isinstance(cases, list) or not cases or len(cases) > 100:
        raise EvidenceError("unsupported_case_set")
    case_ids: set[str] = set()
    bindings: list[dict[str, Any]] = []
    resolved_cases: list[dict[str, Any]] = []
    input_paths: set[Path] = {manifest_path.resolve(strict=True)}
    for index, case in enumerate(cases):
        row = _object(case, {"case_id", "task_asset", "viewport", "variants"}, f"case_{index}", optional={"primary_workflow"})
        case_id = row["case_id"]
        if not isinstance(case_id, str) or SAFE_ID.fullmatch(case_id) is None or case_id in case_ids:
            raise EvidenceError("invalid_or_duplicate_case_id")
        case_ids.add(case_id)
        task_binding, task_path = _asset_ref(row["task_asset"], "task_asset")
        viewport = _object(row["viewport"], {"width", "height"}, "viewport")
        if any(type(viewport[key]) is not int for key in ("width", "height")) or not 320 <= viewport["width"] <= 2560 or not 240 <= viewport["height"] <= 2160:
            raise EvidenceError("invalid_viewport")
        variants = _object(row["variants"], {"baseline", "candidate"}, "variants")
        resolved_variants: dict[str, Any] = {}
        binding_variants: dict[str, Any] = {}
        for variant_name in ("baseline", "candidate"):
            variant = _object(variants[variant_name], {"html"}, f"{variant_name}_artifact", optional={"assets"})
            html_binding, html_path = _asset_ref(variant["html"], f"{variant_name}_html")
            if html_path.suffix.lower() not in {".html", ".htm"}:
                raise EvidenceError("artifact_must_be_local_html")
            if html_path.stat().st_size > MAX_INLINE_HTML_BYTES:
                raise EvidenceError("inline_html_too_large")
            assets_value = variant.get("assets", [])
            if not isinstance(assets_value, list) or assets_value:
                raise EvidenceError("unsupported_artifact_assets")
            if task_path == html_path:
                raise EvidenceError("shared_case_input_path")
            input_paths.update((task_path, html_path))
            binding_variants[variant_name] = {
                "html": html_binding,
                "assets": [],
            }
            resolved_variants[variant_name] = {
                "html": html_path,
                "binding": binding_variants[variant_name],
            }
        workflow = _validate_workflow(row.get("primary_workflow"), index)
        bindings.append({
            "case_id": case_id,
            "task_asset": task_binding,
            "baseline": binding_variants["baseline"],
            "candidate": binding_variants["candidate"],
        })
        resolved_cases.append({
            "case_id": case_id,
            "task_asset": task_path,
            "task_binding": task_binding,
            "viewport": viewport,
            "variants": resolved_variants,
            "primary_workflow": workflow,
        })

    return {
        "run_id": raw["run_id"],
        "manifest_digest": manifest_digest,
        "browser_executable": executable,
        "browser_digest": executable_digest,
        "collector_digest": digest_file(Path(__file__)),
        "helper_digests": _helper_digests(),
        "executor_policy_revision": EXECUTOR_POLICY_REVISION,
        "cases": resolved_cases,
        "input_bindings": bindings,
        "input_paths": input_paths,
    }


def load_manifest(path: Path, reviewed_digest: str) -> dict[str, Any]:
    if not isinstance(reviewed_digest, str) or HEX64.fullmatch(reviewed_digest) is None:
        raise EvidenceError("reviewed_manifest_digest_required")
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
            raise EvidenceError("invalid_manifest_file")
        payload = path.read_bytes()
    except EvidenceError:
        raise
    except Exception:
        raise EvidenceError("unreadable_manifest") from None
    actual_digest = digest_bytes(payload)
    if actual_digest != reviewed_digest:
        raise EvidenceError("reviewed_manifest_digest_mismatch")
    try:
        document = json.loads(payload.decode("utf-8"))
    except Exception:
        raise EvidenceError("invalid_manifest_json") from None
    return validate_manifest(document, manifest_path=path, manifest_digest=actual_digest)


def _secure_directory(path: Path, output_root: Path | None = None) -> None:
    try:
        if output_root is None:
            if path.is_symlink():
                raise EvidenceError("owner_local_symlink_detected")
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            current_paths = [path]
        else:
            relative = path.relative_to(output_root)
            current = output_root
            current_paths = [output_root]
            if current.is_symlink():
                raise EvidenceError("owner_local_symlink_detected")
            for component in relative.parts:
                current = current / component
                if current.is_symlink():
                    raise EvidenceError("owner_local_symlink_detected")
                if not current.exists():
                    current.mkdir(mode=0o700)
                current_paths.append(current)
        for current in current_paths:
            info = current.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise EvidenceError("owner_local_directory_invalid")
    except EvidenceError:
        raise
    except Exception:
        raise EvidenceError("owner_local_directory_unavailable") from None


def _prepare_output(path: Path) -> Path:
    target = path.expanduser()
    if not target.is_absolute():
        raise EvidenceError("output_directory_must_be_absolute")
    try:
        output_file, _ = _eval._owner_output(target / ".owner-local-directory.json")
        output_root = output_file.parent
    except Exception:
        raise EvidenceError("output_directory_not_owner_local") from None
    if output_root.is_symlink() or output_root == ROOT or ROOT in output_root.parents or output_root == Path.home().resolve():
        raise EvidenceError("output_directory_not_owner_local")
    # Permit only the standard macOS temp aliases; reject other symlinked ancestors.
    current = Path(output_root.anchor)
    for component in output_root.parts[1:]:
        current = current / component
        if current.is_symlink() and current not in {Path("/tmp"), Path("/var"), Path("/private")}:
            raise EvidenceError("owner_local_symlink_detected")
    _secure_directory(output_root)
    return output_root


def _acquire_execution_lock(output_root: Path) -> int:
    """Keep a live collector exclusive even if its database lease expires."""
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(output_root / ".execution.lock", flags, 0o600)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise EvidenceError("workflow_execution_lock_invalid")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise EvidenceError("workflow_execution_locked") from None
        return descriptor
    except EvidenceError:
        if "descriptor" in locals():
            os.close(descriptor)
        raise
    except OSError:
        if "descriptor" in locals():
            os.close(descriptor)
        raise EvidenceError("workflow_execution_lock_unavailable") from None


def _release_execution_lock(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _verify_private_file(path: Path, output_root: Path) -> str:
    try:
        _secure_directory(path.parent, output_root)
        path.relative_to(output_root)
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise EvidenceError("owner_local_artifact_invalid")
        return digest_file(path)
    except EvidenceError:
        raise
    except Exception:
        raise EvidenceError("owner_local_artifact_unavailable") from None


def _write_new_private(path: Path, output_root: Path, payload: bytes) -> str:
    try:
        _secure_directory(path.parent, output_root)
        path.relative_to(output_root)
        _eval._write_idempotent(path, payload)
    except EvidenceError:
        raise
    except Exception:
        raise EvidenceError("owner_local_artifact_write_failed") from None
    return _verify_private_file(path, output_root)


def _new_screenshot_path(path: Path, output_root: Path) -> None:
    _secure_directory(path.parent, output_root)
    try:
        path.relative_to(output_root)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        os.close(descriptor)
    except Exception:
        raise EvidenceError("screenshot_output_unavailable") from None


class BrowserAdapter:
    """Narrow direct CLI adapter; callers may inject a subprocess-compatible runner."""

    def __init__(self, executable: Path, run: Callable[..., Any] = subprocess.run, timeout: int = 60,
                 before_command: Callable[[], None] | None = None, expected_digest: str | None = None):
        self.executable = executable
        self.run = run
        self.timeout = timeout
        self.before_command = before_command
        self.expected_digest = expected_digest
        self.home_context: tempfile.TemporaryDirectory[str] | None = None
        self.profile_home: Path | None = None
        self.config_path: Path | None = None
        self.session = ""
        self.env: dict[str, str] = {}

    def __enter__(self) -> "BrowserAdapter":
        # macOS AF_UNIX paths are limited to 104 bytes. Its default per-user
        # temp path plus a long session name can prevent daemon startup.
        self.home_context = tempfile.TemporaryDirectory(prefix="stack-eval-", dir="/tmp")
        self.profile_home = Path(self.home_context.name)
        self.config_path = self.profile_home / "agent-browser.json"
        descriptor = os.open(self.config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(descriptor, b"{}\n")
        os.close(descriptor)
        self.session = f"sd-{os.getpid()}-{os.urandom(5).hex()}"
        self.env = {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(self.profile_home),
            "TMPDIR": str(self.profile_home),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "AGENT_BROWSER_CONFIG": str(self.config_path),
        }
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.home_context is not None:
            self.home_context.cleanup()

    def command(self, *args: str) -> bytes:
        if self.profile_home is None:
            raise EvidenceError("browser_session_not_initialized")
        # Session close must remain possible after ownership is lost.
        if args != ("close",) and self.before_command is not None:
            self.before_command()
        try:
            if self.executable.is_symlink() or (self.expected_digest is not None and digest_file(self.executable) != self.expected_digest):
                raise EvidenceError("browser_executable_drift")
        except OSError:
            raise EvidenceError("browser_executable_unavailable") from None
        # Do not resend launch overrides to an already-running daemon. The
        # caller's environment/config is empty, and private inputs are denied;
        # page-request routing below is not whole-process egress isolation.
        argv = [str(self.executable), "--config", str(self.config_path), "--session", self.session, *args]
        try:
            result = self.run(argv, capture_output=True, check=False, timeout=self.timeout, env=dict(self.env), shell=False, cwd=str(self.profile_home))
        except (subprocess.TimeoutExpired, OSError):
            raise EvidenceError("browser_command_unavailable") from None
        if result.returncode != 0:
            raise EvidenceError("browser_command_failed")
        output = result.stdout
        if isinstance(output, str):
            output = output.encode("utf-8")
        if not isinstance(output, bytes):
            raise EvidenceError("browser_evidence_missing")
        return output


def _decode(output: bytes) -> str:
    try:
        return output.decode("utf-8")
    except UnicodeDecodeError:
        raise EvidenceError("browser_evidence_encoding_invalid") from None


def _snapshot(browser: BrowserAdapter, path: Path, output_root: Path, ensure_lease: Callable[[], None]) -> dict[str, Any]:
    payload = browser.command("snapshot")
    if not payload.strip():
        raise EvidenceError("accessibility_snapshot_missing")
    ensure_lease()
    digest = _write_new_private(path, output_root, payload)
    return {"path": path.relative_to(output_root).as_posix(), "sha256": digest}


def _assertion(browser: BrowserAdapter, assertion: Mapping[str, Any]) -> bool | None:
    kind = assertion["kind"]
    selector = assertion["selector"]
    if kind in {"visible", "enabled", "checked"}:
        try:
            value = _decode(browser.command("is", kind, selector)).strip().lower()
        except EvidenceError:
            return None
        if value in {"true", "yes"}:
            return True
        if value in {"false", "no"}:
            return False
        return None
    command = "get text" if kind == "text_contains" else "get count"
    try:
        actual = _decode(browser.command(*command.split(), selector))
    except EvidenceError:
        return None
    if kind == "text_contains":
        return assertion["value"] in actual
    try:
        return int(actual.strip()) == assertion["value"]
    except ValueError:
        return None


def _inline_page_url(html: bytes) -> str:
    if len(html) > MAX_INLINE_HTML_BYTES or b"\x00" in html:
        raise EvidenceError("inline_html_invalid")
    try:
        html.decode("utf-8")
    except UnicodeDecodeError:
        raise EvidenceError("inline_html_invalid") from None
    doctype = re.match(rb"(?i)<!doctype\s+html[^>]*>", html)
    offset = doctype.end() if doctype else 0
    page = html[:offset] + CSP_META + html[offset:]
    return "data:text/html;charset=utf-8;base64," + base64.b64encode(page).decode("ascii")


def _expected_page_url(output: bytes, expected: str) -> bool:
    try:
        return _decode(output).strip() == expected
    except EvidenceError:
        return False


def _run_variant(
    *, browser_executable: Path, browser_digest: str, command_runner: Callable[..., Any],
    case: Mapping[str, Any], variant_name: str, variant: Mapping[str, Any], attempt: int,
    output_root: Path, ensure_lease: Callable[[], None],
) -> dict[str, Any]:
    ensure_lease()
    case_id = str(case["case_id"])
    base = output_root / "artifacts" / case_id / variant_name / f"attempt-{attempt:04d}"
    _secure_directory(base, output_root)
    html_path: Path = variant["html"]
    viewport = case["viewport"]
    snapshot_path = base / "accessibility.txt"
    screenshot_path = base / "viewport.png"

    def verify_inputs() -> None:
        if digest_file(case["task_asset"]) != case["task_binding"]["sha256"]:
            raise EvidenceError("task_asset_digest_mismatch")
        if digest_file(html_path) != variant["binding"]["html"]["sha256"]:
            raise EvidenceError("html_asset_digest_mismatch")

    verify_inputs()
    try:
        html_bytes = html_path.read_bytes()
    except OSError:
        raise EvidenceError("html_asset_unreadable") from None
    if digest_bytes(html_bytes) != variant["binding"]["html"]["sha256"]:
        raise EvidenceError("html_asset_digest_mismatch")
    page_url = _inline_page_url(html_bytes)
    observations: dict[str, Any] = {
        "case_id": case_id,
        "variant": variant_name,
        "attempt": attempt,
        "viewport": dict(viewport),
        "task_asset_sha256": digest_file(case["task_asset"]),
        "html_sha256": digest_file(html_path),
        "asset_sha256": [],
        "artifacts": {},
        "page_errors": {"status": "unknown"},
        "overflow": {"status": "unknown"},
        "primary_workflow_actions": {"status": "not_specified" if not case["primary_workflow"] else "unknown", "assertions": []},
        "browser_request_routing": {"status": "abort_routes_installed_before_fixture_navigation", "routes": list(REQUEST_ABORT_ROUTES), "action": "abort"},
    }
    action_failed = False
    action_unknown = False
    with BrowserAdapter(browser_executable, command_runner, before_command=ensure_lease, expected_digest=browser_digest) as browser:
        try:
            browser.command("open")
            # The HTML is loaded from its digest-bound data URL. Abort external
            # requests before navigation; the injected CSP also denies them.
            for route in REQUEST_ABORT_ROUTES:
                browser.command("network", "route", route, "--abort")
            browser.command("set", "viewport", str(viewport["width"]), str(viewport["height"]))
            browser.command("open", page_url)
            if not _expected_page_url(browser.command("get", "url"), page_url):
                raise EvidenceError("browser_left_manifest_assets")
            action_results: list[dict[str, Any]] = []
            for step_index, step in enumerate(case["primary_workflow"], start=1):
                action = step["action"]
                command = [action, step["selector"]]
                if action == "press":
                    browser.command("focus", step["selector"])
                    command = ["press", step["key"]]
                try:
                    browser.command(*command)
                    if not _expected_page_url(browser.command("get", "url"), page_url):
                        raise EvidenceError("browser_left_manifest_assets")
                except EvidenceError:
                    action_results.append({"step": step_index, "action_observed": False, "assertions": []})
                    action_failed = True
                    break
                assertion_results = []
                for assertion_index, assertion in enumerate(step["assertions"], start=1):
                    observed = _assertion(browser, assertion)
                    assertion_results.append({
                        "assertion": assertion_index,
                        "kind": assertion["kind"],
                        "observed": observed,
                    })
                    if observed is not True:
                        action_failed = action_failed or observed is False
                        action_unknown = action_unknown or observed is None
                action_results.append({"step": step_index, "action_observed": True, "assertions": assertion_results})
                if action_failed:
                    break
            if case["primary_workflow"]:
                all_observed = all(
                    item["action_observed"] and all(check["observed"] is True for check in item["assertions"])
                    for item in action_results
                )
                if action_failed:
                    status = "failed"
                elif action_unknown:
                    status = "unknown"
                elif all_observed:
                    status = "observed"
                else:
                    status = "unknown"
                observations["primary_workflow_actions"] = {"status": status, "assertions": action_results}

            ensure_lease()
            _new_screenshot_path(screenshot_path, output_root)
            browser.command("screenshot", str(screenshot_path))
            ensure_lease()
            if not screenshot_path.is_file() or screenshot_path.stat().st_size < 8:
                raise EvidenceError("screenshot_missing")
            try:
                os.chmod(screenshot_path, 0o600, follow_symlinks=False)
            except Exception:
                raise EvidenceError("screenshot_permissions_invalid") from None
            with screenshot_path.open("rb") as screenshot:
                signature = screenshot.read(8)
            if signature != b"\x89PNG\r\n\x1a\n":
                raise EvidenceError("screenshot_format_invalid")
            observations["artifacts"]["screenshot"] = {
                "path": screenshot_path.relative_to(output_root).as_posix(),
                "sha256": _verify_private_file(screenshot_path, output_root),
            }
            observations["artifacts"]["accessibility_snapshot"] = _snapshot(browser, snapshot_path, output_root, ensure_lease)
            raw_measurement = _decode(browser.command(
                "eval",
                "({viewport_width:innerWidth,viewport_height:innerHeight,scroll_width:Math.max(document.documentElement.scrollWidth,document.body?.scrollWidth||0),scroll_height:Math.max(document.documentElement.scrollHeight,document.body?.scrollHeight||0)})",
            ))
            try:
                measurement = json.loads(raw_measurement)
                keys = {"viewport_width", "viewport_height", "scroll_width", "scroll_height"}
                if not isinstance(measurement, dict) or set(measurement) != keys or any(type(measurement[key]) is not int for key in keys):
                    raise ValueError
                if measurement["viewport_width"] <= 0 or measurement["viewport_height"] <= 0 or measurement["scroll_width"] < 0 or measurement["scroll_height"] < 0:
                    raise ValueError
            except Exception:
                raise EvidenceError("overflow_measurement_missing") from None
            observations["overflow"] = {
                "status": "observed",
                "viewport_width": measurement["viewport_width"],
                "scroll_width": measurement["scroll_width"],
                "horizontal_overflow_pixels": max(0, measurement["scroll_width"] - measurement["viewport_width"]),
                "viewport_height": measurement["viewport_height"],
                "scroll_height": measurement["scroll_height"],
            }
            error_output = browser.command("errors", "--clear")
            observations["page_errors"] = {
                "status": "observed",
                "nonempty_line_count": sum(bool(line.strip()) for line in _decode(error_output).splitlines()),
            }
            if not _expected_page_url(browser.command("get", "url"), page_url):
                raise EvidenceError("browser_left_manifest_assets")
            verify_inputs()
        finally:
            try:
                browser.command("close")
            except EvidenceError:
                if sys.exc_info()[0] is None:
                    raise
    return observations


def _private_json(path: Path, output_root: Path) -> dict[str, Any]:
    _verify_private_file(path, output_root)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raise EvidenceError("owner_local_receipt_invalid") from None
    if not isinstance(value, dict):
        raise EvidenceError("owner_local_receipt_invalid")
    return value


def _checkpoint_rows(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    child = next((row for row in snapshot.get("children", []) if row.get("child_id") == "browser-evidence"), None)
    if child is None:
        raise EvidenceError("workflow_state_invalid")
    rows = []
    for encoded in child.get("checkpoints", []):
        try:
            row = json.loads(encoded)
        except Exception:
            raise EvidenceError("workflow_checkpoint_invalid") from None
        if not isinstance(row, dict) or row.get("kind") not in {"binding", "attempt_started", "evidence", "final"}:
            raise EvidenceError("workflow_checkpoint_invalid")
        rows.append(row)
    return rows


def _verify_checkpoint_artifacts(
    snapshot: Mapping[str, Any], output_root: Path, manifest: Mapping[str, Any],
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Any] | None]:
    rows = _checkpoint_rows(snapshot)
    evidence: dict[tuple[str, str], dict[str, Any]] = {}
    final: dict[str, Any] | None = None
    binding_count = 0
    case_bindings = {case["case_id"]: case for case in manifest["input_bindings"]}
    for row in rows:
        if row["kind"] == "binding":
            binding_count += 1
            path = output_root / "run-binding.json"
            if row.get("path") != "run-binding.json" or _verify_private_file(path, output_root) != row.get("sha256"):
                raise EvidenceError("run_binding_tampered")
            saved = _private_json(path, output_root)
            if saved != _make_run_binding(manifest):
                raise EvidenceError("run_input_drift")
        elif row["kind"] == "evidence":
            rel = row.get("path")
            if not isinstance(rel, str) or Path(rel).is_absolute() or ".." in Path(rel).parts:
                raise EvidenceError("evidence_receipt_tampered")
            path = output_root / rel
            if _verify_private_file(path, output_root) != row.get("sha256"):
                raise EvidenceError("evidence_receipt_tampered")
            item = _private_json(path, output_root)
            case_id, variant = item.get("case_id"), item.get("variant")
            if variant not in {"baseline", "candidate"} or case_id not in case_bindings:
                raise EvidenceError("evidence_receipt_tampered")
            key = (case_id, variant)
            if key in evidence:
                raise EvidenceError("duplicate_evidence_receipt")
            expected_case = case_bindings[case_id]
            expected = expected_case[variant]
            if item.get("task_asset_sha256") != expected_case["task_asset"]["sha256"] or item.get("html_sha256") != expected["html"]["sha256"] or item.get("asset_sha256") != [asset["sha256"] for asset in expected["assets"]]:
                raise EvidenceError("evidence_input_drift")
            artifacts = item.get("artifacts")
            if not isinstance(artifacts, dict) or set(artifacts) != {"accessibility_snapshot", "screenshot"}:
                raise EvidenceError("evidence_artifact_missing")
            for artifact in artifacts.values():
                artifact_rel = artifact.get("path") if isinstance(artifact, dict) else None
                if not isinstance(artifact_rel, str) or Path(artifact_rel).is_absolute() or ".." in Path(artifact_rel).parts:
                    raise EvidenceError("evidence_artifact_invalid")
                if _verify_private_file(output_root / artifact_rel, output_root) != artifact.get("sha256"):
                    raise EvidenceError("evidence_artifact_tampered")
            evidence[key] = item
        elif row["kind"] == "final":
            path = output_root / "run-receipt.json"
            if row.get("path") != "run-receipt.json" or _verify_private_file(path, output_root) != row.get("sha256"):
                raise EvidenceError("final_receipt_tampered")
            final = _private_json(path, output_root)
            if (final.get("manifest_digest") != manifest["manifest_digest"]
                    or final.get("collector_sha256") != manifest["collector_digest"]
                    or final.get("helper_sha256") != manifest["helper_digests"]
                    or final.get("executor_policy_revision") != manifest["executor_policy_revision"]):
                raise EvidenceError("run_input_drift")
    if binding_count > 1:
        raise EvidenceError("duplicate_run_binding")
    if binding_count == 0 and rows:
        raise EvidenceError("run_binding_missing")
    return evidence, final


def _make_run_binding(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "run_id": manifest["run_id"],
        "manifest_digest": manifest["manifest_digest"],
        "input_bindings": manifest["input_bindings"],
        "browser_sha256": manifest["browser_digest"],
        "collector_sha256": manifest["collector_digest"],
        "helper_sha256": manifest["helper_digests"],
        "executor_policy_revision": manifest["executor_policy_revision"],
    }


def _write_receipt(path: Path, output_root: Path, payload: dict[str, Any]) -> str:
    return _write_new_private(path, output_root, canonical_json(payload).encode("utf-8"))


def _empty_planned_run(snapshot: Mapping[str, Any], output_root: Path) -> bool:
    expected_gates = {gate: {"status": "pending", "evidence": None} for gate in _run_state.GATES}
    expected_files = {"workflow.sqlite3", "workflow.sqlite3-wal", "workflow.sqlite3-shm", ".execution.lock"}
    return (
        snapshot.get("project_identity") == "stack-design-intelligence-evaluation"
        and snapshot.get("owner") == f"uid:{os.getuid()}"
        and snapshot.get("workspace") == str(ROOT)
        and snapshot.get("worktree") is None
        and snapshot.get("max_children") == 1
        and snapshot.get("approval_required") is False
        and snapshot.get("approval_state") == "not_required"
        and snapshot.get("status") == "planned"
        and snapshot.get("children") == []
        and snapshot.get("gates") == expected_gates
        and snapshot.get("receipt") is None
        and all(path.name in expected_files for path in output_root.iterdir())
    )


def run_evaluation(
    manifest_path: Path,
    reviewed_manifest_sha256: str,
    output_dir: Path | None = None,
    *,
    command_runner: Callable[..., Any] = subprocess.run,
    lease_seconds: int = LEASE_SECONDS,
    keepalive: Callable[[], None] | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path, reviewed_manifest_sha256)
    output_root = _prepare_output(output_dir or (DEFAULT_OUTPUT / manifest["run_id"]))
    if any(path == output_root or output_root in path.parents for path in manifest["input_paths"]):
        raise EvidenceError("output_overlaps_input")
    binding_path = output_root / "run-binding.json"
    receipt_path = output_root / "run-receipt.json"
    database = output_root / "workflow.sqlite3"
    lease_owner = f"design-evidence:{os.getpid()}:{os.urandom(4).hex()}"
    lock_descriptor = _acquire_execution_lock(output_root)
    try:
        store = _run_state.WorkflowStore(database)
    except Exception:
        _release_execution_lock(lock_descriptor)
        raise EvidenceError("workflow_state_unavailable") from None
    try:
        try:
            snapshot = store.snapshot(manifest["run_id"])
        except _run_state.RunStateError:
            snapshot = None
        if snapshot is None:
            if binding_path.exists() or receipt_path.exists():
                raise EvidenceError("orphaned_owner_local_artifacts")
            store.create_run(
                manifest["run_id"],
                "stack-design-intelligence-evaluation",
                f"uid:{os.getuid()}",
                str(ROOT),
                max_children=1,
                approval_required=False,
            )
            store.add_child(manifest["run_id"], "browser-evidence", "workflow", "deterministic-local-runner", f"uid:{os.getuid()}", str(ROOT))
            snapshot = store.snapshot(manifest["run_id"])
        assert snapshot is not None
        if (snapshot.get("workspace") != str(ROOT)
                or snapshot.get("project_identity") != "stack-design-intelligence-evaluation"
                or snapshot.get("owner") != f"uid:{os.getuid()}"
                or snapshot.get("worktree") is not None
                or snapshot.get("max_children") != 1
                or snapshot.get("approval_required") is not False
                or snapshot.get("approval_state") != "not_required"):
            raise EvidenceError("workflow_state_identity_mismatch")
        if not snapshot.get("children"):
            if not _empty_planned_run(snapshot, output_root):
                raise EvidenceError("workflow_state_invalid")
            store.add_child(manifest["run_id"], "browser-evidence", "workflow", "deterministic-local-runner", f"uid:{os.getuid()}", str(ROOT))
            snapshot = store.snapshot(manifest["run_id"])
        previous_evidence, final_receipt = _verify_checkpoint_artifacts(snapshot, output_root, manifest)
        child = next((row for row in snapshot.get("children", []) if row.get("child_id") == "browser-evidence"), None)
        if child is None or len(snapshot["children"]) != 1 or child.get("owner") != f"uid:{os.getuid()}" or child.get("workspace") != str(ROOT) or child.get("worktree") is not None or child.get("role") != "workflow" or child.get("model_role") != "deterministic-local-runner":
            raise EvidenceError("workflow_state_invalid")
        if snapshot.get("status") == "blocked":
            store.resume(manifest["run_id"])
            snapshot = store.snapshot(manifest["run_id"])
            previous_evidence, final_receipt = _verify_checkpoint_artifacts(snapshot, output_root, manifest)
        elif snapshot.get("status") in {"cancelled", "receipted", "shipped"}:
            if final_receipt is None:
                raise EvidenceError("workflow_run_terminal_without_receipt")
            return final_receipt
        elif child.get("status") == "completed":
            if final_receipt is None:
                raise EvidenceError("workflow_completed_without_receipt")
            return final_receipt
        if not store.claim_child(manifest["run_id"], "browser-evidence", lease_owner, lease_seconds=lease_seconds):
            raise EvidenceError("workflow_child_lease_unavailable")

        def ensure_lease() -> None:
            if keepalive is not None:
                try:
                    keepalive()
                except Exception:
                    raise EvidenceError("parent_workflow_lease_lost") from None
            if _helper_digests() != manifest["helper_digests"]:
                raise EvidenceError("execution_helper_drift")
            if not store.renew_child_lease(manifest["run_id"], "browser-evidence", lease_owner, lease_seconds=lease_seconds):
                raise EvidenceError("workflow_child_lease_lost")

        def checkpoint(marker: Mapping[str, Any]) -> None:
            ensure_lease()
            store.checkpoint(manifest["run_id"], "browser-evidence", lease_owner, canonical_json(marker))

        try:
            checkpoint_rows = _checkpoint_rows(store.snapshot(manifest["run_id"]))
            binding_digest = _make_run_binding(manifest)
            if not any(row["kind"] == "binding" for row in checkpoint_rows):
                if binding_path.exists():
                    existing = _private_json(binding_path, output_root)
                    if existing != binding_digest:
                        raise EvidenceError("run_input_drift")
                    digest = _verify_private_file(binding_path, output_root)
                else:
                    digest = _write_receipt(binding_path, output_root, binding_digest)
                checkpoint({"kind": "binding", "path": "run-binding.json", "sha256": digest})

            if final_receipt is not None:
                ensure_lease()
                store.finish_child(manifest["run_id"], "browser-evidence", lease_owner, failed=final_receipt.get("status") != "evidence_collected", failure="evidence_status_blocked" if final_receipt.get("status") != "evidence_collected" else None)
                return final_receipt

            checkpoints = _checkpoint_rows(store.snapshot(manifest["run_id"]))
            attempts_used = sum(1 for row in checkpoints if row["kind"] == "attempt_started")
            observations = dict(previous_evidence)
            for case in manifest["cases"]:
                for variant_name in ("baseline", "candidate"):
                    key = (case["case_id"], variant_name)
                    if key in observations:
                        continue
                    attempts_used += 1
                    attempt = attempts_used
                    marker = {"kind": "attempt_started", "case_id": case["case_id"], "variant": variant_name, "attempt": attempt}
                    checkpoint(marker)
                    item = _run_variant(
                        browser_executable=manifest["browser_executable"],
                        browser_digest=manifest["browser_digest"],
                        command_runner=command_runner,
                        case=case,
                        variant_name=variant_name,
                        variant=case["variants"][variant_name],
                        attempt=attempt,
                        output_root=output_root,
                        ensure_lease=ensure_lease,
                    )
                    rel = Path("evidence") / case["case_id"] / f"{variant_name}-attempt-{attempt:04d}.json"
                    ensure_lease()
                    receipt_digest = _write_receipt(output_root / rel, output_root, item)
                    checkpoint({"kind": "evidence", "path": rel.as_posix(), "sha256": receipt_digest})
                    observations[key] = item

            ordered_observations = [
                observations[(case["case_id"], variant)]
                for case in manifest["cases"]
                for variant in ("baseline", "candidate")
            ]
            action_failed = any(item["primary_workflow_actions"]["status"] in {"failed", "unknown"} for item in ordered_observations)
            status = "blocked" if action_failed else "evidence_collected"
            receipt = {
                "schema_version": 2,
                "run_id": manifest["run_id"],
                "manifest_digest": manifest["manifest_digest"],
                "browser_digest": manifest["browser_digest"],
                "collector_sha256": manifest["collector_digest"],
                "helper_sha256": manifest["helper_digests"],
                "executor_policy_revision": manifest["executor_policy_revision"],
                "input_bindings": manifest["input_bindings"],
                "status": status,
                "evaluation_status": "not_evaluated",
                "human_task_usefulness": "pending",
                "limits": ["whole_browser_egress_isolation_not_attested", "visual_quality_not_assessed", "full_accessibility_not_assessed", "privacy_not_assessed", "citation_correctness_not_assessed"],
                "observations": ordered_observations,
            }
            ensure_lease()
            receipt_digest = _write_receipt(receipt_path, output_root, receipt)
            checkpoint({"kind": "final", "path": "run-receipt.json", "sha256": receipt_digest})
            ensure_lease()
            store.finish_child(manifest["run_id"], "browser-evidence", lease_owner, failed=status != "evidence_collected", failure="primary_workflow_assertion_failed" if status != "evidence_collected" else None)
            return receipt
        except BaseException as error:
            # Preserve verified checkpoints so a later invocation can resume safely.
            try:
                current = store.snapshot(manifest["run_id"])
                child = next(row for row in current["children"] if row["child_id"] == "browser-evidence")
                if child["status"] == "leased":
                    code = error.code if isinstance(error, EvidenceError) else "interrupted"
                    store.finish_child(manifest["run_id"], "browser-evidence", lease_owner, failed=True, failure=code)
            except Exception:
                pass
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise EvidenceError("run_interrupted") from None
            if isinstance(error, EvidenceError):
                raise
            raise EvidenceError("evidence_run_failed") from None
    except EvidenceError:
        raise
    except Exception:
        raise EvidenceError("workflow_state_failed") from None
    finally:
        try:
            store.close()
        finally:
            _release_execution_lock(lock_descriptor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--reviewed-manifest-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, help="absolute owner-local run directory; defaults under ~/.local/state/stack/design-intelligence/evidence-runs/<run_id>")
    args = parser.parse_args(argv)
    try:
        receipt = run_evaluation(args.manifest, args.reviewed_manifest_sha256, args.output_dir)
    except EvidenceError as error:
        print(json.dumps({"status": "blocked", "error": error.code}, sort_keys=True))
        return 2
    print(json.dumps({
        "status": receipt["status"],
        "run_id": receipt["run_id"],
        "observation_count": len(receipt["observations"]),
        "human_task_usefulness": receipt["human_task_usefulness"],
        "evaluation_status": receipt["evaluation_status"],
    }, sort_keys=True))
    return 0 if receipt["status"] == "evidence_collected" else 2


if __name__ == "__main__":
    raise SystemExit(main())
