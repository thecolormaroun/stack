#!/usr/bin/env python3
"""Resolve Stack requests through the canonical command and routing registries.

The resolver is deliberately small and deterministic.  It selects a logical
command; it never invokes a skill, writes a receipt, or changes a runtime.
Claude and Codex adapters can characterize this same result before delegating
to their runtime-specific invocation.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
COMMANDS_PATH = ROOT / "registry/commands.json"
ROUTING_PATH = ROOT / "registry/routing-rules.json"

CONTRACT_VERSION = "stack-command-resolution-v1"
CONTRACT_FIELDS = [
    "logical_command",
    "subcommand",
    "match_reason",
    "candidates",
    "trust_class",
    "effect_vector",
    "evidence_context",
    "approval_state",
]
EFFECT_FIELDS = [
    "source_read",
    "owner_local_write",
    "project_write",
    "external_write",
    "costly_use",
    "irreversible_action",
]
TRUST_CLASSES = {"read-only", "local-mutation", "external-mutation", "costly", "irreversible"}
APPROVAL_STATES = {"not_required", "pending", "approved", "denied"}


class ResolverError(ValueError):
    """The command or routing registry cannot be consumed safely."""


def canonical_json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ResolverError(f"invalid registry JSON: {path}") from error
    if not isinstance(value, dict):
        raise ResolverError(f"registry must contain an object: {path}")
    return value


def _normalize_text(value: str) -> str:
    value = value.strip().lower()
    value = value.replace("/", " ").replace("_", " ")
    value = re.sub(r"[^a-z0-9.\-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", value.lower()) if token]


def _copy_context(context: Mapping[str, Any] | None) -> dict[str, Any]:
    if context is None:
        return {}
    if not isinstance(context, Mapping):
        raise ResolverError("context must be an object")
    try:
        value = copy.deepcopy(dict(context))
        json.dumps(value)
    except (TypeError, ValueError) as error:
        raise ResolverError("context must be JSON-serializable") from error
    return value


def _context_values(context: Mapping[str, Any]) -> set[str]:
    """Return normalized context signals without inspecting arbitrary prose."""

    values: set[str] = set()
    for key, raw in context.items():
        key_text = _normalize_text(str(key))
        if key_text:
            values.add(key_text)
        if isinstance(raw, bool):
            if raw:
                values.add(key_text)
            continue
        if isinstance(raw, str):
            values.update(_tokens(raw))
            continue
        if isinstance(raw, (list, tuple, set)):
            for item in raw:
                if isinstance(item, str):
                    values.update(_tokens(item))
    return values


def _has_context(context: Mapping[str, Any], requirement: str) -> bool:
    requirement = _normalize_text(requirement)
    values = _context_values(context)
    if requirement in values:
        return True
    if requirement in {"task context", "task-context"}:
        return bool(
            values
            & {
                "project",
                "repository",
                "repo",
                "route",
                "component",
                "viewport",
                "device",
                "brief",
                "code",
                "markup",
                "screenshot",
            }
        )
    if requirement in {"code or architecture artifact", "code-or-architecture-artifact"}:
        return bool(
            values
            & {
                "code",
                "architecture",
                "diff",
                "source",
                "repository",
                "repo",
                "artifact",
                "codeartifact",
                "architectureartifact",
            }
        )
    if requirement in {"design artifact", "design-artifact"}:
        return bool(
            values
            & {
                "design",
                "visual",
                "screenshot",
                "mockup",
                "wireframe",
                "prototype",
                "image",
                "viewport",
            }
        )
    return False


def _effect_vector(command: Mapping[str, Any]) -> tuple[dict[str, bool] | None, str | None]:
    value = command.get("effect_vector")
    if not isinstance(value, Mapping):
        return None, "effect_vector is missing"
    if set(value) != set(EFFECT_FIELDS):
        missing = sorted(set(EFFECT_FIELDS) - set(value))
        extra = sorted(set(value) - set(EFFECT_FIELDS))
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unsupported " + ", ".join(extra))
        return None, "effect_vector metadata is incomplete" + (f" ({'; '.join(details)})" if details else "")
    if not all(isinstance(value[field], bool) for field in EFFECT_FIELDS):
        return None, "effect_vector values must be booleans"
    return {field: bool(value[field]) for field in EFFECT_FIELDS}, None


def _command_metadata_error(command: Mapping[str, Any]) -> str | None:
    command_id = command.get("id", "<unknown>")
    required = ("id", "family", "subcommands", "owner", "visibility", "trust_class", "inputs", "outputs", "delegates", "runtimes", "aliases")
    missing = [field for field in required if field not in command]
    if missing:
        return f"command {command_id} metadata is incomplete: missing {', '.join(missing)}"
    if not isinstance(command.get("id"), str) or not command["id"]:
        return f"command {command_id} metadata is incomplete: invalid id"
    if command.get("visibility") not in {"primary", "extended"}:
        return f"command {command_id} metadata is incomplete: invalid visibility"
    if command.get("trust_class") not in TRUST_CLASSES:
        return f"command {command_id} metadata is incomplete: invalid trust_class"
    if not isinstance(command.get("subcommands"), list) or not all(isinstance(item, str) and item for item in command["subcommands"]):
        return f"command {command_id} metadata is incomplete: invalid subcommands"
    runtimes = command.get("runtimes")
    if not isinstance(runtimes, Mapping) or any(not isinstance(runtimes.get(runtime), str) or not runtimes[runtime] for runtime in ("claude", "codex")):
        return f"command {command_id} metadata is incomplete: Claude/Codex runtime parity is missing"
    effect, error = _effect_vector(command)
    del effect
    if error:
        return f"command {command_id} metadata is incomplete: {error}"
    return None


class CommandResolver:
    """Deterministic resolver over one command and routing registry pair."""

    def __init__(self, commands: Mapping[str, Any], routing: Mapping[str, Any]):
        self.commands_data = copy.deepcopy(dict(commands))
        self.routing_data = copy.deepcopy(dict(routing))
        self.commands: list[dict[str, Any]] = []
        self.by_id: dict[str, dict[str, Any]] = {}
        self.aliases: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        self.rules: list[dict[str, Any]] = []
        self.metadata_errors: dict[str, str] = {}
        self.registry_errors: list[str] = []
        self._load()

    @classmethod
    def from_paths(cls, commands_path: Path | str = COMMANDS_PATH, routing_path: Path | str = ROUTING_PATH) -> "CommandResolver":
        return cls(read_json(Path(commands_path)), read_json(Path(routing_path)))

    def _load(self) -> None:
        if self.commands_data.get("schema_version") != 1 or not isinstance(self.commands_data.get("commands"), list):
            self.registry_errors.append("command registry requires schema_version 1 and a commands list")
        else:
            for command in self.commands_data["commands"]:
                if not isinstance(command, dict):
                    self.registry_errors.append("command registry contains a non-object entry")
                    continue
                command_id = command.get("id")
                if not isinstance(command_id, str) or not command_id:
                    self.registry_errors.append("command registry contains a command without an id")
                    continue
                if command_id in self.by_id:
                    self.registry_errors.append(f"duplicate command {command_id}")
                    continue
                self.commands.append(command)
                self.by_id[command_id] = command
                error = _command_metadata_error(command)
                if error:
                    self.metadata_errors[command_id] = error
                aliases = command.get("aliases", [])
                if isinstance(aliases, list):
                    for alias in aliases:
                        if not isinstance(alias, dict) or not isinstance(alias.get("name"), str) or not alias["name"]:
                            self.registry_errors.append(f"command {command_id} has malformed alias metadata")
                            continue
                        key = _normalize_text(alias["name"])
                        if key in self.aliases:
                            self.registry_errors.append(f"duplicate alias {alias['name']}")
                            continue
                        self.aliases[key] = (command, alias)

        if self.routing_data.get("schema_version") != 1 or not isinstance(self.routing_data.get("rules"), list):
            self.registry_errors.append("routing registry requires schema_version 1 and a rules list")
            return
        for rule in self.routing_data["rules"]:
            if not isinstance(rule, dict) or not isinstance(rule.get("command"), str):
                self.registry_errors.append("routing registry contains an invalid rule")
                continue
            command_id = rule["command"]
            if command_id not in self.by_id:
                self.registry_errors.append(f"routing rule references unknown command {command_id}")
                continue
            intents = rule.get("intents")
            if not isinstance(intents, list) or not all(isinstance(item, str) and item.strip() for item in intents):
                self.registry_errors.append(f"routing rule for {command_id} has incomplete intents")
                continue
            requires = rule.get("requires_context", [])
            if not isinstance(requires, list) or not all(isinstance(item, str) and item.strip() for item in requires):
                self.registry_errors.append(f"routing rule for {command_id} has incomplete context metadata")
                continue
            normalized = dict(rule)
            normalized["subcommand"] = rule.get("subcommand")
            normalized["requires_context"] = list(requires)
            self.rules.append(normalized)

    @property
    def contract(self) -> dict[str, Any]:
        return {
            "version": CONTRACT_VERSION,
            "fields": list(CONTRACT_FIELDS),
            "effect_vector_fields": list(EFFECT_FIELDS),
            "approval_states": sorted(APPROVAL_STATES),
            "precedence": list(self.routing_data.get("precedence", ["canonical-id", "alias", "intent", "context"])),
        }

    def characterize(self, request: str, runtime: str, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if runtime not in {"claude", "codex"}:
            raise ResolverError("runtime must be claude or codex")
        resolution = self.resolve(request, context)
        invocation = None
        command_id = resolution.get("logical_command")
        if isinstance(command_id, str):
            command = self.by_id.get(command_id)
            if command and isinstance(command.get("runtimes"), Mapping):
                invocation = command["runtimes"].get(runtime)
        return {
            "runtime": runtime,
            "invocation": invocation,
            "contract": self.contract,
            "resolution": resolution,
        }

    def resolve(self, request: str, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        context_value = _copy_context(context)
        normalized = _normalize_text(request) if isinstance(request, str) else ""
        if not normalized:
            return self._base_result(context_value, status="unknown", reason="unknown", denial_reason="request is empty")
        if self.registry_errors and not self.by_id:
            return self._base_result(context_value, status="denied", reason="metadata-incomplete", denial_reason="; ".join(self.registry_errors))

        direct = self._direct_match(normalized)
        if direct is not None:
            command, subcommand, reason, alias = direct
            return self._finish(command, subcommand, reason, context_value, alias=alias)

        candidates = self._intent_candidates(normalized, context_value)
        candidates.extend(self._context_candidates(normalized, context_value))
        candidates = self._deduplicate(candidates)
        eligible = [candidate for candidate in candidates if candidate["eligible"]]
        if not eligible:
            incomplete = [candidate for candidate in candidates if candidate.get("missing")]
            if incomplete:
                candidate = sorted(incomplete, key=lambda item: (-item["score"], item["command_id"], item.get("subcommand") or ""))[0]
                command = self.by_id.get(candidate["command_id"])
                return self._denied(
                    context_value,
                    command,
                    candidate.get("subcommand"),
                    "metadata-incomplete",
                    "required evidence context is incomplete",
                    missing=candidate.get("missing", []),
                )
            if "review" in _tokens(normalized):
                return self._denied(context_value, None, None, "metadata-incomplete", "review routing requires code or design context")
            return self._base_result(context_value, status="unknown", reason="unknown", denial_reason="no canonical route matched")

        ranked = sorted(
            eligible,
            key=lambda item: (-item["score"], -item["priority"], item["command_id"], item.get("subcommand") or ""),
        )
        top = ranked[0]
        top_score = (top["score"], top["priority"])
        tied = [item for item in ranked if (item["score"], item["priority"]) == top_score]
        command_ids = sorted({item["command_id"] for item in tied})
        if len(command_ids) > 1:
            return self._ambiguous(context_value, command_ids, tied)
        command = self.by_id[top["command_id"]]
        return self._finish(command, top.get("subcommand"), top["reason"], context_value, candidates=command_ids)

    def _base_result(self, context: dict[str, Any], *, status: str, reason: str, denial_reason: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": status,
            "logical_command": None,
            "subcommand": None,
            "match_reason": reason,
            "candidates": [],
            "trust_class": None,
            "effect_vector": None,
            "evidence_context": self._evidence_context(None, context, []),
            "approval_state": "denied" if status == "denied" else "not_required",
            "approval_required": False,
            "decision": "ask" if status != "resolved" else "execute",
        }
        if denial_reason:
            result["denial_reason"] = denial_reason
        return result

    def _denied(self, context: dict[str, Any], command: Mapping[str, Any] | None, subcommand: str | None, reason: str, denial_reason: str, *, missing: list[str] | None = None) -> dict[str, Any]:
        if command is None:
            result = self._base_result(context, status="denied", reason=reason, denial_reason=denial_reason)
            if missing:
                result["evidence_context"]["missing"] = sorted(set(missing))
            return result
        result = self._base_result(context, status="denied", reason=reason, denial_reason=denial_reason)
        result["logical_command"] = command.get("id")
        result["subcommand"] = subcommand
        result["candidates"] = [command.get("id")] if isinstance(command.get("id"), str) else []
        result["evidence_context"] = self._evidence_context(command, context, missing or [])
        return result

    def _ambiguous(self, context: dict[str, Any], command_ids: list[str], details: list[dict[str, Any]]) -> dict[str, Any]:
        result = self._base_result(context, status="ambiguous", reason="ambiguous", denial_reason="materially competing routes remain")
        result["candidates"] = command_ids
        result["candidate_details"] = [
            {"logical_command": item["command_id"], "subcommand": item.get("subcommand"), "match_reason": item["reason"]}
            for item in sorted(details, key=lambda item: (item["command_id"], item.get("subcommand") or ""))
        ]
        return result

    def _finish(self, command: Mapping[str, Any], subcommand: str | None, reason: str, context: dict[str, Any], *, alias: Mapping[str, Any] | None = None, candidates: list[str] | None = None) -> dict[str, Any]:
        command_id = command.get("id")
        if not isinstance(command_id, str):
            return self._base_result(context, status="denied", reason="metadata-incomplete", denial_reason="matched command has no id")
        valid_subcommands = command.get("subcommands")
        if subcommand is not None and (not isinstance(valid_subcommands, list) or subcommand not in valid_subcommands):
            return self._denied(context, command, subcommand, "metadata-incomplete", f"unknown subcommand {subcommand!r}")
        metadata_error = self.metadata_errors.get(command_id)
        if metadata_error:
            return self._denied(context, command, subcommand, "metadata-incomplete", metadata_error)
        effect, effect_error = _effect_vector(command)
        if effect_error or effect is None:
            return self._denied(context, command, subcommand, "metadata-incomplete", effect_error or "effect vector is missing")
        trust = command.get("trust_class")
        approval_required = any(effect[field] for field in EFFECT_FIELDS if field != "source_read")
        supplied_approval = context.get("approval_state")
        approval_state = supplied_approval if supplied_approval in {"approved", "declined"} else ("pending" if approval_required else "not_required")
        if supplied_approval == "declined":
            approval_state = "denied"
        evidence = self._evidence_context(command, context, [])
        result: dict[str, Any] = {
            "status": "resolved",
            "logical_command": command_id,
            "subcommand": subcommand,
            "match_reason": reason,
            "candidates": candidates if candidates is not None else [command_id],
            "trust_class": trust,
            "effect_vector": effect,
            "evidence_context": evidence,
            "approval_state": approval_state,
            "approval_required": approval_required,
            "decision": "execute" if approval_state in {"not_required", "approved"} else "ask",
        }
        if alias is not None:
            result["matched_alias"] = alias.get("name")
            result["canonical_warning"] = bool(alias.get("canonical_warning"))
        return result

    def _evidence_context(self, command: Mapping[str, Any] | None, context: Mapping[str, Any], missing_extra: list[str]) -> dict[str, Any]:
        required: list[str] = []
        if command is not None and isinstance(command.get("inputs"), list):
            required.extend(item for item in command["inputs"] if isinstance(item, str))
        provided = sorted(str(key) for key in context)
        missing = [item for item in required if not _has_context(context, item)]
        missing.extend(item for item in missing_extra if item not in missing)
        return {
            "required": sorted(set(required)),
            "provided": provided,
            "missing": sorted(set(missing)),
            "values": copy.deepcopy(dict(context)),
        }

    def _direct_match(self, normalized: str) -> tuple[dict[str, Any], str | None, str, dict[str, Any] | None] | None:
        text = normalized
        candidates: list[tuple[str, dict[str, Any], str, dict[str, Any] | None]] = []
        for command_id, command in self.by_id.items():
            forms = {command_id, command_id.replace(".", " ")}
            runtimes = command.get("runtimes")
            if isinstance(runtimes, Mapping):
                forms.update(_normalize_text(value) for value in runtimes.values() if isinstance(value, str))
            for form in forms:
                if text == form or text.startswith(form + " "):
                    candidates.append((form, command, "canonical-id", None))
        for alias_key, (command, alias) in self.aliases.items():
            if text == alias_key or text.startswith(alias_key + " "):
                candidates.append((alias_key, command, "alias", alias))
        if not candidates:
            return None
        # Canonical IDs outrank aliases; longer forms prevent stack.design from
        # swallowing stack.design.intelligence.
        candidates.sort(key=lambda item: (0 if item[2] == "canonical-id" else 1, -len(item[0]), item[0]))
        form, command, reason, alias = candidates[0]
        suffix = text[len(form):].strip()
        subcommand = self._subcommand_from_suffix(command, suffix)
        # Alias convenience forms retain the documented legacy segment.
        alias_defaults = {"mega": "full", "mega-workflow": "full", "departments": "plan", "ideate": "ideate", "ce-plan": "technical", "ce-brainstorm": "brainstorm", "ce-work": "implement", "lfg": "implement"}
        if subcommand is None and alias is not None and alias.get("name") in alias_defaults and not suffix:
            subcommand = alias_defaults[alias["name"]]
        elif subcommand is None and suffix:
            subcommand = suffix.replace(" ", "-")
        return command, subcommand, reason, alias

    @staticmethod
    def _subcommand_from_suffix(command: Mapping[str, Any], suffix: str) -> str | None:
        if not suffix:
            return None
        declared = command.get("subcommands")
        if not isinstance(declared, list):
            return suffix.replace(" ", "-")
        suffix = suffix.replace("/", " ").strip()
        tokens = suffix.split()
        for count in range(len(tokens), 0, -1):
            value = "-".join(tokens[:count])
            if value in declared:
                return value
        return suffix.replace(" ", "-")

    def _intent_candidates(self, normalized: str, context: Mapping[str, Any]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        request_tokens = _tokens(normalized)
        request_token_set = set(request_tokens)
        for rule in self.rules:
            matched_score = 0
            for intent in rule.get("intents", []):
                intent_norm = _normalize_text(intent)
                intent_tokens = _tokens(intent_norm)
                # Root help/status words are explicit command affordances, not
                # broad natural-language intents that should compete with a
                # more specific family route.
                if rule.get("command") == "stack" and len(intent_tokens) == 1 and intent_norm != normalized:
                    continue
                if intent_norm and intent_norm in normalized:
                    matched_score = max(matched_score, 100 + len(intent_tokens) * 10)
                elif intent_tokens and set(intent_tokens).issubset(request_token_set):
                    matched_score = max(matched_score, 40 + len(intent_tokens) * 5)
            if not matched_score:
                continue
            command_id = rule["command"]
            requirements = list(rule.get("requires_context", []))
            missing = [item for item in requirements if not _has_context(context, item)]
            declared_subcommand = rule.get("subcommand")
            if not declared_subcommand:
                declared_subcommand = self._declared_subcommand_from_text(self.by_id[command_id], normalized)
            candidates.append({
                "command_id": command_id,
                "subcommand": declared_subcommand,
                "score": matched_score,
                "priority": 2,
                "reason": "intent",
                "missing": missing,
                "eligible": not missing,
            })
        return candidates

    @staticmethod
    def _declared_subcommand_from_text(command: Mapping[str, Any], text: str) -> str | None:
        declared = command.get("subcommands")
        if not isinstance(declared, list):
            return None
        tokens = set(_tokens(text))
        for subcommand in sorted((item for item in declared if isinstance(item, str)), key=lambda item: (-len(item), item)):
            if set(_tokens(subcommand)).issubset(tokens):
                return subcommand
        return None

    def _context_candidates(self, normalized: str, context: Mapping[str, Any]) -> list[dict[str, Any]]:
        if "review" not in _tokens(normalized):
            return []
        candidates: list[dict[str, Any]] = []
        code = _has_context(context, "code-or-architecture-artifact")
        design = _has_context(context, "design-artifact")
        if code and "stack.review" in self.by_id:
            candidates.append({"command_id": "stack.review", "subcommand": "code", "score": 100, "priority": 1, "reason": "context", "missing": [], "eligible": True})
        if design and "stack.design" in self.by_id:
            candidates.append({"command_id": "stack.design", "subcommand": "critique", "score": 100, "priority": 1, "reason": "context", "missing": [], "eligible": True})
        return candidates

    @staticmethod
    def _deduplicate(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: dict[tuple[str, str | None], dict[str, Any]] = {}
        for candidate in candidates:
            key = (candidate["command_id"], candidate.get("subcommand"))
            previous = deduped.get(key)
            if previous is None or (candidate["score"], candidate["priority"]) > (previous["score"], previous["priority"]):
                deduped[key] = candidate
        return list(deduped.values())


def resolve(request: str, context: Mapping[str, Any] | None = None, *, commands_path: Path | str = COMMANDS_PATH, routing_path: Path | str = ROUTING_PATH) -> dict[str, Any]:
    """Convenience function for adapters and tests."""

    return CommandResolver.from_paths(commands_path, routing_path).resolve(request, context)


def resolve_command(request: str, context: Mapping[str, Any] | None = None, *, commands_path: Path | str = COMMANDS_PATH, routing_path: Path | str = ROUTING_PATH) -> dict[str, Any]:
    return resolve(request, context, commands_path=commands_path, routing_path=routing_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", nargs="+", help="Natural-language request, canonical command, or alias")
    parser.add_argument("--context", default="{}", help="JSON task context object")
    parser.add_argument("--context-file", type=Path, help="Read task context from a JSON file")
    parser.add_argument("--runtime", choices=("claude", "codex"), help="Also emit a runtime characterization")
    parser.add_argument("--commands", type=Path, default=COMMANDS_PATH)
    parser.add_argument("--routing", type=Path, default=ROUTING_PATH)
    args = parser.parse_args(argv)
    try:
        context_text = args.context_file.read_text(encoding="utf-8") if args.context_file else args.context
        context = json.loads(context_text)
        if not isinstance(context, dict):
            raise ResolverError("context must be a JSON object")
        resolver = CommandResolver.from_paths(args.commands, args.routing)
        if args.runtime:
            result = resolver.characterize(" ".join(args.request), args.runtime, context)
        else:
            result = resolver.resolve(" ".join(args.request), context)
    except (OSError, json.JSONDecodeError, ResolverError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(canonical_json(result).rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
