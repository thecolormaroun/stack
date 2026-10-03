#!/usr/bin/env python3
"""Produce quarantined HTML from public synthetic tasks and reviewed Stack bytes.

This is a preparation lane, not design-learning evaluation or promotion evidence.
No live adapter imports it. A reviewed manifest digest and --execute are required
before a Codex model call. Tool and host isolation are requested, not attested.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
MATERIALIZER = SCRIPT_DIR / "materialize-capability-change.py"
EVALUATOR = SCRIPT_DIR / "evaluate-design-intelligence-candidate.py"
COLLECTOR = SCRIPT_DIR / "run-design-intelligence-evaluation.py"
RUN_STATE = SCRIPT_DIR / "stack-run-state.py"
POLICY = ROOT / "config" / "capability-activation-policy.json"
HELPERS = {"materializer": MATERIALIZER, "evaluator": EVALUATOR,
           "collector": COLLECTOR, "workflow_store": RUN_STATE, "policy": POLICY}
CODEX_COMMAND = Path("/opt/homebrew/bin/codex")
CODEX_LAUNCHER = Path("/opt/homebrew/lib/node_modules/@openai/codex/bin/codex.js")
CODEX_NATIVE = Path("/opt/homebrew/lib/node_modules/@openai/codex/node_modules/@openai/codex-darwin-arm64/vendor/aarch64-apple-darwin/bin/codex")
NODE_COMMAND = Path("/opt/homebrew/bin/node")
SENSITIVE_TEXT = re.compile(r"/(?:Users|home|private|var)/|\b(?:api[_ -]?key|access[_ -]?token|secret|password|credential|patient|medical|diagnosis|ssn)\b|[\w.+-]+@[\w.-]+\.[a-z]{2,}", re.I)
MAX_MANIFEST = 1_000_000
MAX_JSONL = 1_000_000
MAX_HTML = 64_000
MAX_PROMPT = 256_000
LEASE_SECONDS = 900
POLICY_REVISION = "public-synthetic-codex-html-v2"
HTML_POLICY_REVISION = "static-network-denied-html-v1"
HTML_CSP = "default-src 'none'; script-src 'none'; connect-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; object-src 'none'"
HTML_CSP_META = '<meta http-equiv="Content-Security-Policy" content="' + HTML_CSP + '">'
OUTPUT_SCHEMA = {"type": "object", "properties": {"html": {"type": "string"}},
                 "required": ["html"], "additionalProperties": False}
SAFE_REJECTION_REASONS = frozenset({
    "provider_stream_error", "provider_turn_failed", "provider_item_error",
    "tool_item", "multiple_agent_messages", "invalid_agent_message_lifecycle",
    "unknown_item", "unknown_event_or_order",
})
TOOL_ITEM_TYPES = frozenset({
    "command_execution", "file_change", "mcp_tool_call", "collab_tool_call",
    "web_search", "todo_list",
})


class GenerationError(ValueError):
    def __init__(self, code: str, *, reason: str | None = None):
        super().__init__(code)
        self.code = code
        self.reason = reason if isinstance(reason, str) and reason in SAFE_REJECTION_REASONS else None


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise GenerationError("helper_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_mat = _load_module("_stack_generation_materializer", MATERIALIZER)
_eval = _load_module("_stack_generation_evaluator", EVALUATOR)
_collector = _load_module("_stack_generation_collector", COLLECTOR)
_store = _load_module("_stack_generation_workflow_store", RUN_STATE)
HEX64 = _collector.HEX64
SAFE_ID = _collector.SAFE_ID
_sha = _eval.digest_bytes
LOADED_HELPERS = {name: _mat.digest_bytes(path.read_bytes()) for name, path in HELPERS.items()}
LOADED_CODE = _mat.digest_bytes(Path(__file__).read_bytes())


def _json_bytes(value: Any) -> bytes:
    return _eval.canonical_json(value).encode("utf-8")


def _object(value: Any, keys: set[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise GenerationError(code)
    return value


def _load_json(data: bytes, code: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result
    try:
        decoded = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeError, ValueError):
        raise GenerationError(code) from None
    if not isinstance(decoded, dict):
        raise GenerationError(code)
    return decoded


def _private_ref(value: Any, code: str, *, maximum: int = MAX_MANIFEST) -> tuple[Path, bytes]:
    ref = _object(value, {"path", "sha256"}, code)
    if not isinstance(ref["path"], str) or not Path(ref["path"]).is_absolute() or not isinstance(ref["sha256"], str) or not HEX64.fullmatch(ref["sha256"]):
        raise GenerationError(code)
    path = Path(ref["path"])
    if ".." in path.parts or "." in path.parts:
        raise GenerationError(code)
    try:
        current = Path(path.anchor)
        for component in path.parts[1:-1]:
            current = current / component
            if current.is_symlink() and current not in {Path("/tmp"), Path("/var"), Path("/private")}:
                raise GenerationError(code)
        details = path.lstat()
        if (not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid()
                or stat.S_IMODE(details.st_mode) != 0o600 or details.st_size > maximum):
            raise GenerationError(code)
        content = path.read_bytes()
    except OSError:
        raise GenerationError(code) from None
    if _sha(content) != ref["sha256"]:
        raise GenerationError(f"{code}_digest_mismatch")
    return path, content


def _git_bytes(repository: Path, args: list[str], *, allow_absent: bool = False) -> bytes | None:
    try:
        result = subprocess.run(["git", "-C", str(repository), *args],
                                env={"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
                                     "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
                                     "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"},
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=60, check=False, shell=False)
    except (OSError, subprocess.TimeoutExpired):
        raise GenerationError("git_unavailable") from None
    if result.returncode != 0:
        if allow_absent:
            return None
        raise GenerationError("git_verification_failed")
    return result.stdout


def _verify_checkout(repository: Path, base: str) -> bytes:
    if not repository.is_absolute() or repository.is_symlink() or not repository.is_dir():
        raise GenerationError("repository_invalid")
    root = _git_bytes(repository, ["rev-parse", "--show-toplevel"])
    head = _git_bytes(repository, ["rev-parse", "HEAD"])
    if root is None or Path(root.decode("utf-8").strip()).resolve() != repository.resolve() or head is None or head.decode("ascii").strip() != base:
        raise GenerationError("repository_base_mismatch")
    return _git_bytes(repository, ["status", "--porcelain=v1", "--untracked-files=all"]) or b""


def _prompt(task: Mapping[str, Any], instructions: list[bytes]) -> str:
    parts = ["Create one complete, self-contained static HTML document with explicit html, head and body elements for this public synthetic task.",
             "Return only the JSON object required by the output schema. Use inline CSS only. Do not use tools, scripts, HTML comments, SVG, MathML, external assets, network calls, forms, or frames.",
             "Task:\n" + task["text"],
             f"Viewport: {task['viewport']['width']} by {task['viewport']['height']} pixels."]
    for index, content in enumerate(instructions, 1):
        parts.append(f"Instruction {index}:\n" + content.decode("utf-8"))
    return "\n\n".join(parts) + "\n"


def _public_text(value: str) -> bool:
    return "\x00" not in value and SENSITIVE_TEXT.search(value) is None and not _mat.privacy_scan(value)


def _helper_digests() -> dict[str, str]:
    try:
        current = {name: _sha(path.read_bytes()) for name, path in HELPERS.items()}
        code = _sha(Path(__file__).read_bytes())
    except OSError:
        raise GenerationError("helper_unavailable") from None
    if current != LOADED_HELPERS or code != LOADED_CODE:
        raise GenerationError("helper_drift")
    return current


def prepare_generation(manifest_path: Path, reviewed_manifest_sha256: str, repository: Path) -> dict[str, Any]:
    """Prove exact inputs and prepare prompts without invoking a model or writing state."""
    if not isinstance(reviewed_manifest_sha256, str) or not HEX64.fullmatch(reviewed_manifest_sha256):
        raise GenerationError("reviewed_manifest_digest_required")
    manifest_path = Path(manifest_path)
    _, raw_manifest = _private_ref({"path": str(manifest_path), "sha256": reviewed_manifest_sha256}, "manifest")
    manifest = _object(_load_json(raw_manifest, "manifest_invalid"),
                       {"schema_version", "run_id", "content_scope", "task", "model", "codex", "candidate_packet", "materialization", "patch", "target", "instruction_paths"},
                       "manifest_shape_invalid")
    if manifest["schema_version"] != 1 or manifest["content_scope"] != "synthetic_non_private" or not isinstance(manifest["run_id"], str) or not SAFE_ID.fullmatch(manifest["run_id"]):
        raise GenerationError("manifest_scope_invalid")
    task = _object(manifest["task"], {"case_id", "text", "viewport"}, "task_invalid")
    if not isinstance(task["case_id"], str) or not SAFE_ID.fullmatch(task["case_id"]) or not isinstance(task["text"], str) or not 1 <= len(task["text"].encode("utf-8")) <= 8192 or not _public_text(task["text"]):
        raise GenerationError("task_not_public_synthetic")
    viewport = _object(task["viewport"], {"width", "height"}, "viewport_invalid")
    if any(type(viewport[key]) is not int for key in viewport) or not 320 <= viewport["width"] <= 2560 or not 240 <= viewport["height"] <= 2160:
        raise GenerationError("viewport_invalid")
    model = _object(manifest["model"], {"name", "reasoning_effort"}, "model_invalid")
    if (model["name"], model["reasoning_effort"]) not in {("gpt-6-luna", "max"), ("gpt-6-sol", "high"), ("gpt-6-sol", "max")}:
        raise GenerationError("model_not_allowlisted")
    codex = _object(manifest["codex"], {"executable", "launcher_sha256", "native_sha256", "node_sha256"}, "codex_invalid")
    if codex["executable"] != str(CODEX_COMMAND):
        raise GenerationError("codex_not_allowlisted")
    executable = CODEX_COMMAND
    try:
        if executable.resolve(strict=True) != CODEX_LAUNCHER.resolve(strict=True) or not NODE_COMMAND.resolve(strict=True).is_file():
            raise GenerationError("codex_binary_invalid")
        if (_sha(CODEX_LAUNCHER.read_bytes()) != codex["launcher_sha256"]
                or _sha(CODEX_NATIVE.read_bytes()) != codex["native_sha256"]
                or _sha(NODE_COMMAND.read_bytes()) != codex["node_sha256"]
                or not all(os.access(path, os.X_OK) for path in (executable, CODEX_NATIVE, NODE_COMMAND))):
            raise GenerationError("codex_binary_invalid")
    except OSError:
        raise GenerationError("codex_binary_invalid") from None
    packet_path, packet_bytes = _private_ref(manifest["candidate_packet"], "packet", maximum=2_000_000)
    _, receipt_bytes = _private_ref(manifest["materialization"], "materialization", maximum=1_000_000)
    _, patch_bytes = _private_ref(manifest["patch"], "patch", maximum=2_000_000)
    packet = _load_json(packet_bytes, "packet_invalid")
    receipt = _load_json(receipt_bytes, "materialization_invalid")
    repo = Path(repository)
    status_before = _verify_checkout(repo, packet.get("base_commit"))
    try:
        policy = _mat.load_object(POLICY, "materialization policy")
        automatic = _mat._is_automatic_weekly_campaign(packet, receipt.get("authorization", {}))
        if _mat.privacy_scan(packet):
            raise GenerationError("packet_privacy_scan_failed")
        _mat._validate_packet(packet, repo, policy, automatic_weekly=automatic, packet_dir=packet_path.parent)
        packet_digest, _ = _eval._validate_packet(packet)
        _eval._validate_materialization(receipt, packet, packet_digest)
    except GenerationError:
        raise
    except Exception:
        raise GenerationError("packet_or_materialization_invalid") from None
    if manifest["target"] != packet["target"] or receipt.get("edits") != [
        {key: edit[key] for key in ("path", "role", "operation", "before_digest", "after_digest")}
        for edit in packet["edits"]
    ]:
        raise GenerationError("edit_binding_mismatch")
    target_path = packet["target"]["capability_path"]
    scoped_paths = sorted({target_path, *(row["path"] for row in packet["edits"])})
    if _git_bytes(repo, ["status", "--porcelain=v1", "--untracked-files=all", "--", *scoped_paths]):
        raise GenerationError("target_dirty")
    target_info = (repo / target_path).lstat()
    if not stat.S_ISREG(target_info.st_mode) or stat.S_IMODE(target_info.st_mode) & 0o111:
        raise GenerationError("target_not_regular_markdown")
    if receipt.get("patch_filename") != "capability-change.patch" or receipt.get("patch_digest") != _sha(patch_bytes) or manifest["patch"]["sha256"] != receipt["patch_digest"]:
        raise GenerationError("patch_digest_mismatch")
    if not isinstance(manifest["instruction_paths"], list):
        raise GenerationError("instruction_paths_invalid")
    selected = [row for row in packet["edits"] if row["role"] in {"skill", "reference"}]
    selected_paths = {target_path, *(row["path"] for row in selected)}
    if not selected:
        raise GenerationError("target_instruction_missing")
    declared: dict[str, dict[str, Any]] = {}
    for row in manifest["instruction_paths"]:
        entry = _object(row, {"path", "before_sha256", "after_sha256"}, "instruction_paths_invalid")
        if entry["path"] in declared or entry["path"] not in selected_paths:
            raise GenerationError("instruction_paths_invalid")
        declared[entry["path"]] = entry
    if set(declared) != selected_paths:
        raise GenerationError("instruction_paths_incomplete")
    baseline: dict[str, bytes] = {}
    candidate: dict[str, bytes] = {}
    for edit in packet["edits"]:
        relative = _mat.safe_relative(edit["path"])
        before = _git_bytes(repo, ["show", f"{packet['base_commit']}:{relative.as_posix()}"], allow_absent=edit["operation"] == "create")
        if edit["operation"] == "create":
            if before is not None or edit["before_digest"] is not None:
                raise GenerationError("base_blob_mismatch")
        elif before is None or _sha(before) != edit["before_digest"]:
            raise GenerationError("base_blob_mismatch")
        if "content" in edit:
            after = edit["content"].encode("utf-8")
        else:
            try:
                after = _mat._content_file(edit, packet_path.parent).read_bytes()
            except Exception:
                raise GenerationError("candidate_content_invalid") from None
        if _sha(after) != edit["after_digest"]:
            raise GenerationError("candidate_content_digest_mismatch")
        if edit["path"] in selected_paths:
            entry = declared[edit["path"]]
            if entry["before_sha256"] != edit["before_digest"] or entry["after_sha256"] != edit["after_digest"]:
                raise GenerationError("instruction_digest_mismatch")
            for content in (before, after):
                if content is not None:
                    try:
                        text = content.decode("utf-8")
                    except UnicodeError:
                        raise GenerationError("instruction_encoding_invalid") from None
                    if not _public_text(text):
                        raise GenerationError("instruction_not_public")
            if before is not None:
                baseline[edit["path"]] = before
            candidate[edit["path"]] = after
    if target_path not in candidate:
        target_bytes = _git_bytes(repo, ["show", f"{packet['base_commit']}:{target_path}"])
        if target_bytes is None:
            raise GenerationError("target_instruction_missing")
        target_sha = _sha(target_bytes)
        if declared[target_path]["before_sha256"] != target_sha or declared[target_path]["after_sha256"] != target_sha:
            raise GenerationError("instruction_digest_mismatch")
        try:
            target_text = target_bytes.decode("utf-8")
        except UnicodeError:
            raise GenerationError("instruction_encoding_invalid") from None
        if not _public_text(target_text):
            raise GenerationError("instruction_not_public")
        baseline[target_path] = target_bytes
        candidate[target_path] = target_bytes
    ordered = [target_path, *sorted(selected_paths - {target_path})]
    with tempfile.TemporaryDirectory(prefix="stack-generation-patch-") as temporary:
        checkout = _mat._clone_exact(repo, packet["base_commit"], Path(temporary))
        _mat._apply_edits(checkout, [{**row, "path": _mat.safe_relative(row["path"])} for row in packet["edits"]], packet_path.parent)
        changed = _mat._run_git(checkout, ["diff", "--cached", "--name-only", "--no-ext-diff"]).splitlines()
        actual_patch = _mat._run_git(checkout, ["diff", "--cached", "--binary", "--no-ext-diff", "--no-color"], timeout=60).encode("utf-8")
    if sorted(changed) != sorted(row["path"] for row in packet["edits"]) or actual_patch != patch_bytes:
        raise GenerationError("isolated_patch_mismatch")
    if _verify_checkout(repo, packet["base_commit"]) != status_before:
        raise GenerationError("repository_changed_during_prepare")
    prompts = {name: _prompt(task, [contents[path] for path in ordered if path in contents])
               for name, contents in (("baseline", baseline), ("candidate", candidate))}
    if any(len(prompt.encode("utf-8")) > MAX_PROMPT for prompt in prompts.values()):
        raise GenerationError("prompt_too_large")
    helpers = _helper_digests()
    binding = {"schema_version": 1, "run_id": manifest["run_id"], "manifest_sha256": reviewed_manifest_sha256,
               "repository": str(repo.resolve()), "base_commit": packet["base_commit"], "packet_sha256": manifest["candidate_packet"]["sha256"],
               "materialization_sha256": manifest["materialization"]["sha256"], "patch_sha256": manifest["patch"]["sha256"],
               "instruction_paths": [declared[path] for path in ordered], "task_sha256": _sha(_json_bytes(task)),
               "prompt_sha256": {name: _sha(prompt.encode("utf-8")) for name, prompt in prompts.items()},
               "model": model, "codex_sha256": codex, "producer_sha256": LOADED_CODE,
               "helper_sha256": helpers, "output_schema_sha256": _sha(_json_bytes(OUTPUT_SCHEMA)), "policy_revision": POLICY_REVISION}
    return {"manifest": manifest, "binding": binding, "prompts": prompts, "executable": executable,
            "repository": repo.resolve(), "checkout_status": status_before,
            "input_paths": {manifest_path.resolve(), packet_path.resolve(), Path(manifest["materialization"]["path"]).resolve(), Path(manifest["patch"]["path"]).resolve()}}


class _HTMLSafety(HTMLParser):
    FORBIDDEN = {"base", "form", "input", "iframe", "frame", "frameset", "object", "embed", "portal", "link", "script", "svg", "math"}
    URL_ATTRS = {"src", "href", "srcset", "action", "formaction", "poster", "data", "xlink:href", "ping", "manifest"}

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source = source
        self.unsafe = False
        self.root_started = False
        self.head_insert_at: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.head_insert_at is None:
            if not self.root_started and tag == "html" and all(key in {"lang", "dir", "class", "data-theme"} for key, _ in attrs):
                self.root_started = True
            elif self.root_started and tag == "head" and not attrs:
                line, column = self.getpos()
                offset = sum(len(part) + 1 for part in self.source.split("\n")[:line - 1]) + column
                self.head_insert_at = offset + len(self.get_starttag_text())
            else:
                self.unsafe = True
        if tag in self.FORBIDDEN:
            self.unsafe = True
        for key, value in attrs:
            value = value or ""
            lowered = value.strip().lower()
            if key.startswith("on") or key in {"srcdoc", "integrity"}:
                self.unsafe = True
            if key in self.URL_ATTRS and lowered and not (key == "href" and lowered.startswith("#")) and not (tag == "img" and key == "src" and re.fullmatch(r"data:image/(?:png|jpeg|gif|webp);base64,[a-z0-9+/=]+", lowered)):
                self.unsafe = True
            if key == "style" and re.search(r"url\s*\(|@import|expression\s*\(", value, re.I):
                self.unsafe = True
            if tag == "meta" and key == "http-equiv" and (lowered != "content-security-policy" or dict(attrs).get("content") != HTML_CSP):
                self.unsafe = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"html", "head"}:
            self.unsafe = True
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self.head_insert_at is None and data.strip():
            self.unsafe = True

    def handle_endtag(self, tag: str) -> None:
        if self.head_insert_at is None:
            self.unsafe = True

    def handle_decl(self, decl: str) -> None:
        if decl.strip().lower() != "doctype html":
            self.unsafe = True

    def handle_comment(self, data: str) -> None:
        self.unsafe = True

    def handle_pi(self, data: str) -> None:
        self.unsafe = True

    def unknown_decl(self, data: str) -> None:
        self.unsafe = True


def _validate_html(html: Any) -> bytes:
    if not isinstance(html, str) or "\x00" in html:
        raise GenerationError("html_invalid")
    data = html.encode("utf-8")
    if not data or len(data) > MAX_HTML or re.search(r"<html(?:\s|>)", html, re.I) is None or re.search(r"</html\s*>", html, re.I) is None:
        raise GenerationError("html_invalid")
    parser = _HTMLSafety(html)
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        raise GenerationError("html_invalid") from None
    if parser.unsafe or parser.head_insert_at is None or "<!--" in html or re.search(r"(?:https?://|file://|//[^\s<]|@import\b|url\s*\(|\bfetch\s*\(|XMLHttpRequest|WebSocket|EventSource|sendBeacon|window\.open|location\s*=|import\s*\(|document\.write)", html, re.I):
        raise GenerationError("html_unsafe")
    position = parser.head_insert_at
    guarded = html if html[position:].startswith(HTML_CSP_META) else html[:position] + HTML_CSP_META + html[position:]
    data = guarded.encode("utf-8")
    if len(data) > MAX_HTML:
        raise GenerationError("html_invalid")
    return data


def _parse_events(stdout: bytes) -> tuple[bytes, dict[str, int] | None, str]:
    if not isinstance(stdout, bytes) or not stdout or len(stdout) > MAX_JSONL:
        raise GenerationError("provider_events_invalid")
    thread = started = completed = False
    output: bytes | None = None
    provider_html_sha256: str | None = None
    usage: dict[str, int] | None = None
    for line in stdout.splitlines():
        if len(line) > MAX_JSONL or not line.strip():
            raise GenerationError("provider_events_invalid")
        event = _load_json(line, "provider_events_invalid")
        kind = event.get("type")
        if kind in {"error", "turn.failed"}:
            raise GenerationError("provider_tool_or_output_rejected", reason=(
                "provider_stream_error" if kind == "error" else "provider_turn_failed"))
        if kind == "thread.started" and not thread and not started and isinstance(event.get("thread_id"), str):
            thread = True
        elif kind == "turn.started" and thread and not started:
            started = True
        elif kind in {"item.started", "item.updated", "item.completed"} and started and not completed:
            item = event.get("item")
            if not isinstance(item, dict):
                raise GenerationError("provider_events_invalid")
            item_type = item.get("type")
            if item_type == "reasoning":
                continue  # Reasoning is deliberately neither persisted nor returned.
            if item_type in TOOL_ITEM_TYPES or item_type == "error":
                raise GenerationError("provider_tool_or_output_rejected", reason=(
                    "provider_item_error" if item_type == "error" else "tool_item"))
            if kind == "item.started" and item_type == "agent_message" and output is None:
                continue
            if kind != "item.completed" or item_type != "agent_message" or output is not None or not isinstance(item.get("text"), str):
                reason = ("unknown_item" if item_type != "agent_message" else
                          "multiple_agent_messages" if output is not None else
                          "invalid_agent_message_lifecycle")
                raise GenerationError("provider_tool_or_output_rejected", reason=reason)
            message = _load_json(item["text"].encode("utf-8"), "provider_output_invalid")
            _object(message, {"html"}, "provider_output_invalid")
            output = _validate_html(message["html"])
            provider_html_sha256 = _sha(message["html"].encode("utf-8"))
        elif kind == "turn.completed" and started and not completed and output is not None:
            completed = True
            value = event.get("usage")
            if value is not None:
                if not isinstance(value, dict) or any(type(amount) is not int or amount < 0 for amount in value.values()):
                    raise GenerationError("provider_events_invalid")
                usage = {key: value[key] for key in ("input_tokens", "cached_input_tokens", "output_tokens") if key in value}
        else:
            raise GenerationError("provider_tool_or_output_rejected", reason="unknown_event_or_order")
    if not thread or not started or not completed or output is None or provider_html_sha256 is None:
        raise GenerationError("provider_events_incomplete")
    return output, usage, provider_html_sha256


DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "multi_agent", "apps", "hooks", "plugins",
    "shell_snapshot", "shell_snapshot_v2", "shell_zsh_fork",
    "browser_use", "browser_use_external", "browser_use_full_cdp_access",
    "computer_use", "view_image", "memories", "chronicle", "code_mode",
    "code_mode_host", "image_generation", "skill_search", "standalone_web_search",
    "skill_mcp_dependency_install", "workspace_dependencies", "daemon_auto_start",
)


def _codex_argv(executable: Path, model: Mapping[str, str], schema: Path, cwd: Path) -> list[str]:
    argv = [str(executable), "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
            "--skip-git-repo-check", "--strict-config", "--sandbox", "read-only", "--json",
            "--output-schema", str(schema), "--cd", str(cwd), "--model", model["name"],
            "--enable", "skip_host_skill_discovery"]
    for feature in DISABLED_FEATURES:
        argv += ["--disable", feature]
    argv += ["-c", f'model_reasoning_effort="{model["reasoning_effort"]}"',
             "-c", 'model_provider="openai"', "-c", "mcp_servers={}",
             "-c", "skills.bundled.enabled=false", "-c", "skills.include_instructions=false",
             "-c", "project_doc_max_bytes=0", "-c", "tools.update_plan.enabled=false",
             "-c", "allow_login_shell=false",
             "-c", 'web_search="disabled"', "-c", "include_environment_context=false",
             "-c", "include_apps_instructions=false", "-c", "include_collaboration_mode_instructions=false",
             "-c", 'developer_instructions="Use no tools. Return only the required JSON object containing one self-contained HTML document."',
             "-"]
    return argv


def _safe_env() -> dict[str, str]:
    return {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


def _call_runner(runner: Callable[..., Any], argv: list[str], *, prompt: bytes | None,
                 cwd: Path, timeout: int, ensure_lease: Callable[[], None]) -> Any:
    env = _safe_env()
    if runner is not subprocess.run:
        try:
            return runner(argv, input=prompt, capture_output=True, check=False,
                          timeout=timeout, env=env, cwd=str(cwd), shell=False)
        except (OSError, subprocess.TimeoutExpired):
            raise GenerationError("provider_command_unavailable") from None
    if prompt is None:
        try:
            return subprocess.run(argv, input=None, capture_output=True, check=False,
                                  timeout=timeout, env=env, cwd=str(cwd), shell=False)
        except (OSError, subprocess.TimeoutExpired):
            raise GenerationError("auth_status_unavailable") from None
    try:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=str(cwd), env=env, shell=False,
                                   start_new_session=True)
    except OSError:
        raise GenerationError("provider_command_unavailable") from None
    deadline = time.monotonic() + timeout
    stdout = bytearray()
    stderr_size = 0
    pending = memoryview(prompt)
    selector = selectors.DefaultSelector()
    try:
        assert process.stdin and process.stdout and process.stderr
        for handle, event in ((process.stdin, selectors.EVENT_WRITE),
                              (process.stdout, selectors.EVENT_READ),
                              (process.stderr, selectors.EVENT_READ)):
            os.set_blocking(handle.fileno(), False)
            selector.register(handle, event)
        last_renewal = 0.0
        while True:
            now = time.monotonic()
            if now >= deadline:
                raise GenerationError("provider_timeout")
            if now - last_renewal >= 20:
                ensure_lease()
                last_renewal = now
            for key, _ in selector.select(timeout=min(1, deadline - now)):
                handle = key.fileobj
                if handle is process.stdin:
                    try:
                        written = os.write(handle.fileno(), pending[:65536]) if pending else 0
                    except BlockingIOError:
                        continue
                    pending = pending[written:]
                    if not pending:
                        selector.unregister(handle)
                        handle.close()
                else:
                    try:
                        chunk = os.read(handle.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(handle)
                        handle.close()
                    elif handle is process.stdout:
                        stdout.extend(chunk)
                        if len(stdout) > MAX_JSONL:
                            raise GenerationError("provider_output_limit")
                    else:
                        stderr_size += len(chunk)
                        if stderr_size > 65536:
                            raise GenerationError("provider_output_limit")
            if process.poll() is not None and not selector.get_map():
                ensure_lease()
                return subprocess.CompletedProcess(argv, process.returncode, bytes(stdout), b"")
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except Exception:
            pass
        raise
    finally:
        selector.close()
        for handle in (process.stdin, process.stdout, process.stderr):
            if handle is not None and not handle.closed:
                handle.close()


def _auth_chatgpt(executable: Path, cwd: Path, runner: Callable[..., Any], ensure_lease: Callable[[], None]) -> None:
    ensure_lease()
    result = _call_runner(runner, [str(executable), "login", "status"], prompt=None,
                          cwd=cwd, timeout=15, ensure_lease=ensure_lease)
    stdout, stderr = result.stdout, result.stderr
    if isinstance(stdout, str):
        stdout = stdout.encode("utf-8")
    if isinstance(stderr, str):
        stderr = stderr.encode("utf-8")
    status = stdout if stdout else stderr
    if (result.returncode != 0 or not isinstance(status, bytes) or len(status) > 4096
            or (stdout and stderr) or re.fullmatch(rb"\s*Logged in using ChatGPT\s*", status, re.I) is None):
        raise GenerationError("chatgpt_auth_required")


def _invoke_codex(context: Mapping[str, Any], variant: str, schema: Path, cwd: Path,
                  runner: Callable[..., Any], ensure_lease: Callable[[], None]) -> tuple[bytes, dict[str, int] | None, str]:
    prompt = context["prompts"][variant].encode("utf-8")
    argv = _codex_argv(context["executable"], context["manifest"]["model"], schema, cwd)
    ensure_lease()
    result = _call_runner(runner, argv, prompt=prompt, cwd=cwd, timeout=240, ensure_lease=ensure_lease)
    if result.returncode != 0:
        raise GenerationError("provider_nonzero_exit")
    stdout = result.stdout
    if isinstance(stdout, str):
        stdout = stdout.encode("utf-8")
    return _parse_events(stdout)


def _checkpoint_rows(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    children = snapshot.get("children")
    if not isinstance(children, list) or len(children) != 1:
        raise GenerationError("workflow_state_foreign")
    child = children[0]
    if (child.get("child_id") != "html-producer" or child.get("role") != "workflow"
            or child.get("model_role") != "codex-public-synthetic"
            or child.get("owner") != f"uid:{os.getuid()}" or child.get("workspace") != str(ROOT)
            or child.get("worktree") is not None):
        raise GenerationError("workflow_state_foreign")
    rows = []
    for encoded in child.get("checkpoints", []):
        try:
            row = _load_json(encoded.encode("utf-8"), "workflow_checkpoint_invalid")
        except (AttributeError, UnicodeError):
            raise GenerationError("workflow_checkpoint_invalid") from None
        shape = {"binding": {"kind", "sha256"},
                 "attempt_started": {"kind", "variant", "prompt_sha256"},
                 "variant_output": {"kind", "variant", "sha256"},
                 "final": {"kind", "sha256"}}.get(row.get("kind"))
        if shape is None or set(row) != shape:
            raise GenerationError("workflow_checkpoint_invalid")
        rows.append(row)
    return rows


def _private_json(path: Path, output_root: Path) -> dict[str, Any]:
    _collector._verify_private_file(path, output_root)
    return _load_json(path.read_bytes(), "owner_local_artifact_invalid")


def _validate_saved(snapshot: Mapping[str, Any], output_root: Path,
                    binding: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None, bool]:
    rows = _checkpoint_rows(snapshot)
    bound = False
    started: set[str] = set()
    outputs: dict[str, dict[str, Any]] = {}
    final: dict[str, Any] | None = None
    allowed = {"workflow.sqlite3", "workflow.sqlite3-wal", "workflow.sqlite3-shm", ".execution.lock",
               "run-binding.json", "html-output-schema.json", "run-receipt.json"}
    for row in rows:
        kind = row["kind"]
        if kind == "binding":
            if bound or rows[0] is not row or _collector._verify_private_file(output_root / "run-binding.json", output_root) != row["sha256"] or _private_json(output_root / "run-binding.json", output_root) != binding:
                raise GenerationError("run_binding_tampered_or_drifted")
            bound = True
        elif kind == "attempt_started":
            variant = row["variant"]
            if not bound or final is not None or variant not in {"baseline", "candidate"} or variant in started or row["prompt_sha256"] != binding["prompt_sha256"][variant] or (variant == "candidate" and "baseline" not in outputs):
                raise GenerationError("workflow_checkpoint_invalid")
            started.add(variant)
        elif kind == "variant_output":
            variant = row["variant"]
            if variant not in started or variant in outputs or final is not None:
                raise GenerationError("workflow_checkpoint_invalid")
            receipt_path = output_root / "artifacts" / f"{variant}-receipt.json"
            html_path = output_root / "artifacts" / f"{variant}.html"
            if _collector._verify_private_file(receipt_path, output_root) != row["sha256"]:
                raise GenerationError("variant_receipt_tampered")
            item = _private_json(receipt_path, output_root)
            if (set(item) != {"schema_version", "run_id", "variant", "prompt_sha256", "html_sha256", "provider_html_sha256", "html_policy_revision", "requested_model", "observed_model", "usage", "status"}
                    or item["schema_version"] != 1 or item["run_id"] != binding["run_id"]
                    or item["variant"] != variant or item["prompt_sha256"] != binding["prompt_sha256"][variant]
                    or item["requested_model"] != binding["model"] or item["observed_model"] is not None
                    or not isinstance(item["provider_html_sha256"], str) or not HEX64.fullmatch(item["provider_html_sha256"])
                    or item["html_policy_revision"] != HTML_POLICY_REVISION
                    or item["status"] != "generated_quarantined"
                    or _collector._verify_private_file(html_path, output_root) != item["html_sha256"]):
                raise GenerationError("variant_receipt_tampered")
            html_bytes = html_path.read_bytes()
            if _validate_html(html_bytes.decode("utf-8")) != html_bytes:
                raise GenerationError("variant_html_policy_mismatch")
            outputs[variant] = item
            allowed.add("artifacts")
        elif kind == "final":
            if final is not None or set(outputs) != {"baseline", "candidate"} or _collector._verify_private_file(output_root / "run-receipt.json", output_root) != row["sha256"]:
                raise GenerationError("final_receipt_tampered")
            final = _private_json(output_root / "run-receipt.json", output_root)
            if (set(final) != {"schema_version", "run_id", "status", "binding_sha256", "outputs", "evaluation_status", "tool_isolation", "provider_prompt_closure", "activation"}
                    or final["schema_version"] != 1 or final["run_id"] != binding["run_id"]
                    or final["binding_sha256"] != _sha(_json_bytes(binding))
                    or final["outputs"] != [outputs["baseline"], outputs["candidate"]]
                    or final["status"] != "generated_quarantined"
                    or final["evaluation_status"] != "not_evaluated"
                    or final["tool_isolation"] != "requested_not_attested"
                    or final["provider_prompt_closure"] != "unverified"
                    or final["activation"] != {"active_pointer": False, "install": False, "publish": False, "promotion": False}):
                raise GenerationError("final_receipt_tampered")
    if rows and not bound:
        raise GenerationError("run_binding_missing")
    if started - set(outputs):
        raise GenerationError("attempt_started_reconciliation_required")
    if (output_root / "run-binding.json").exists() and not bound:
        if _private_json(output_root / "run-binding.json", output_root) != binding:
            raise GenerationError("run_binding_tampered_or_drifted")
    if (output_root / "html-output-schema.json").exists():
        if _private_json(output_root / "html-output-schema.json", output_root) != OUTPUT_SCHEMA:
            raise GenerationError("output_schema_tampered")
    # The lock and SQLite files are managed by the existing collector/store.
    if any(child.name not in allowed for child in output_root.iterdir()):
        raise GenerationError("foreign_owner_local_artifact")
    artifact_dir = output_root / "artifacts"
    if artifact_dir.exists():
        expected = {f"{variant}.html" for variant in outputs} | {f"{variant}-receipt.json" for variant in outputs}
        if not artifact_dir.is_dir() or artifact_dir.is_symlink() or {item.name for item in artifact_dir.iterdir()} != expected:
            raise GenerationError("foreign_owner_local_artifact")
    return outputs, final, bound


def execute_generation(manifest_path: Path, reviewed_manifest_sha256: str, repository: Path,
                       output_dir: Path, *, runner: Callable[..., Any] = subprocess.run,
                       lease_seconds: int = LEASE_SECONDS) -> dict[str, Any]:
    context = prepare_generation(manifest_path, reviewed_manifest_sha256, repository)
    if lease_seconds <= 0:
        raise GenerationError("lease_invalid")
    try:
        output_root = _collector._prepare_output(Path(output_dir))
    except Exception:
        raise GenerationError("owner_local_output_invalid") from None
    if output_root == context["repository"] or context["repository"] in output_root.parents or any(
        path == output_root or output_root in path.parents or path.parent == output_root or path.parent in output_root.parents
        for path in context["input_paths"]
    ):
        raise GenerationError("output_overlaps_input_or_repository")
    try:
        lock = _collector._acquire_execution_lock(output_root)
    except Exception:
        raise GenerationError("workflow_execution_locked_or_invalid") from None
    try:
        try:
            store = _store.WorkflowStore(output_root / "workflow.sqlite3")
        except Exception:
            raise GenerationError("workflow_state_unavailable") from None
        try:
            run_id = context["manifest"]["run_id"]
            if store.conn.execute("SELECT count(*) FROM runs WHERE run_id <> ?", (run_id,)).fetchone()[0]:
                raise GenerationError("workflow_state_foreign")
            snapshot = store.conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if snapshot is None:
                if any(path.name not in {"workflow.sqlite3", "workflow.sqlite3-wal", "workflow.sqlite3-shm", ".execution.lock"} for path in output_root.iterdir()):
                    raise GenerationError("foreign_owner_local_artifact")
                store.create_run(run_id, "stack-design-intelligence-generation", f"uid:{os.getuid()}",
                                 str(ROOT), max_children=1, approval_required=False)
                store.add_child(run_id, "html-producer", "workflow", "codex-public-synthetic",
                                f"uid:{os.getuid()}", str(ROOT))
            snapshot = store.snapshot(run_id)
            if (snapshot.get("project_identity") != "stack-design-intelligence-generation"
                    or snapshot.get("owner") != f"uid:{os.getuid()}" or snapshot.get("workspace") != str(ROOT)
                    or snapshot.get("worktree") is not None or snapshot.get("max_children") != 1
                    or snapshot.get("approval_required") is not False or snapshot.get("approval_state") != "not_required"):
                raise GenerationError("workflow_state_foreign")
            outputs, final, bound = _validate_saved(snapshot, output_root, context["binding"])
            if snapshot["status"] in {"cancelled", "receipted", "shipped"}:
                raise GenerationError("workflow_state_inconsistent")
            if final is not None:
                if snapshot["children"][0]["status"] != "completed":
                    if snapshot["status"] == "blocked":
                        store.resume(run_id)
                    recovery_owner = f"html-producer-recovery:{os.getpid()}:{os.urandom(4).hex()}"
                    if not store.claim_child(run_id, "html-producer", recovery_owner, lease_seconds=lease_seconds):
                        raise GenerationError("workflow_child_lease_unavailable")
                    store.finish_child(run_id, "html-producer", recovery_owner)
                return final
            if snapshot["status"] in {"cancelled", "receipted", "shipped"} or snapshot["children"][0]["status"] == "completed":
                raise GenerationError("workflow_state_inconsistent")
            if snapshot["status"] == "blocked":
                store.resume(run_id)
            lease_owner = f"html-producer:{os.getpid()}:{os.urandom(4).hex()}"
            if not store.claim_child(run_id, "html-producer", lease_owner, lease_seconds=lease_seconds):
                raise GenerationError("workflow_child_lease_unavailable")

            def ensure_lease() -> None:
                if _helper_digests() != context["binding"]["helper_sha256"]:
                    raise GenerationError("helper_drift")
                if _verify_checkout(context["repository"], context["binding"]["base_commit"]) != context["checkout_status"]:
                    raise GenerationError("repository_changed")
                if not store.renew_child_lease(run_id, "html-producer", lease_owner, lease_seconds=lease_seconds):
                    raise GenerationError("workflow_child_lease_lost")

            def checkpoint(row: Mapping[str, Any]) -> None:
                ensure_lease()
                store.checkpoint(run_id, "html-producer", lease_owner, _eval.canonical_json(row))

            try:
                if not bound:
                    digest = _collector._write_new_private(output_root / "run-binding.json", output_root,
                                                           _json_bytes(context["binding"]))
                    checkpoint({"kind": "binding", "sha256": digest})
                _collector._write_new_private(output_root / "html-output-schema.json", output_root,
                                              _json_bytes(OUTPUT_SCHEMA))
                for variant in ("baseline", "candidate"):
                    if variant in outputs:
                        continue
                    with tempfile.TemporaryDirectory(prefix="stack-public-html-", dir=output_root) as scratch_text:
                        scratch = Path(scratch_text)
                        os.chmod(scratch, 0o700)
                        current = prepare_generation(manifest_path, reviewed_manifest_sha256, repository)
                        if current["binding"] != context["binding"]:
                            raise GenerationError("run_input_drift")
                        _auth_chatgpt(context["executable"], scratch, runner, ensure_lease)
                        checkpoint({"kind": "attempt_started", "variant": variant,
                                    "prompt_sha256": context["binding"]["prompt_sha256"][variant]})
                        html, usage, provider_html_sha256 = _invoke_codex(context, variant, output_root / "html-output-schema.json",
                                                    scratch, runner, ensure_lease)
                    current = prepare_generation(manifest_path, reviewed_manifest_sha256, repository)
                    if current["binding"] != context["binding"]:
                        raise GenerationError("run_input_drift")
                    ensure_lease()
                    html_digest = _collector._write_new_private(output_root / "artifacts" / f"{variant}.html", output_root, html)
                    item = {"schema_version": 1, "run_id": run_id, "variant": variant,
                            "prompt_sha256": context["binding"]["prompt_sha256"][variant],
                            "html_sha256": html_digest, "requested_model": context["manifest"]["model"],
                            "provider_html_sha256": provider_html_sha256, "html_policy_revision": HTML_POLICY_REVISION,
                            "observed_model": None, "usage": usage, "status": "generated_quarantined"}
                    receipt_digest = _collector._write_new_private(output_root / "artifacts" / f"{variant}-receipt.json", output_root, _json_bytes(item))
                    checkpoint({"kind": "variant_output", "variant": variant, "sha256": receipt_digest})
                    outputs[variant] = item
                receipt = {"schema_version": 1, "run_id": run_id, "status": "generated_quarantined",
                           "binding_sha256": _sha(_json_bytes(context["binding"])),
                           "outputs": [outputs["baseline"], outputs["candidate"]],
                           "evaluation_status": "not_evaluated", "tool_isolation": "requested_not_attested",
                           "provider_prompt_closure": "unverified",
                           "activation": {"active_pointer": False, "install": False, "publish": False, "promotion": False}}
                receipt_digest = _collector._write_new_private(output_root / "run-receipt.json", output_root, _json_bytes(receipt))
                checkpoint({"kind": "final", "sha256": receipt_digest})
                ensure_lease()
                store.finish_child(run_id, "html-producer", lease_owner)
                return receipt
            except BaseException as error:
                try:
                    child = store.snapshot(run_id)["children"][0]
                    if child["status"] == "leased" and child["lease_owner"] == lease_owner:
                        store.finish_child(run_id, "html-producer", lease_owner, failed=True,
                                           failure=error.code if isinstance(error, GenerationError) else "interrupted")
                except Exception:
                    pass
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    raise GenerationError("run_interrupted") from None
                if isinstance(error, GenerationError):
                    raise
                raise GenerationError("generation_failed") from None
        finally:
            store.close()
    except GenerationError:
        raise
    except Exception:
        raise GenerationError("generation_failed") from None
    finally:
        _collector._release_execution_lock(lock)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--reviewed-manifest-sha256", required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", "--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.prepare:
            result = prepare_generation(args.manifest, args.reviewed_manifest_sha256, args.repository)
            print(json.dumps({"status": "prepared_public_synthetic", "run_id": result["manifest"]["run_id"],
                              "manifest_sha256": args.reviewed_manifest_sha256,
                              "prompt_sha256": result["binding"]["prompt_sha256"], "provider_calls": 0}, sort_keys=True))
        else:
            receipt = execute_generation(args.manifest, args.reviewed_manifest_sha256,
                                         args.repository, args.output_dir)
            print(json.dumps({"status": receipt["status"], "run_id": receipt["run_id"],
                              "html_sha256": [row["html_sha256"] for row in receipt["outputs"]],
                              "evaluation_status": receipt["evaluation_status"]}, sort_keys=True))
        return 0
    except GenerationError as error:
        result = {"status": "blocked", "code": error.code}
        if error.reason is not None:
            result["reason"] = error.reason
        print(json.dumps(result, sort_keys=True))
        return 2
    except Exception:
        print(json.dumps({"status": "blocked", "code": "generation_failed"}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
