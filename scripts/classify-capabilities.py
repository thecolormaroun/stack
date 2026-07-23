#!/usr/bin/env python3
"""Classify the reviewed Stack estate and write a deterministic reconciliation.

This script intentionally changes metadata only.  It neither moves skills nor
publishes them to a runtime; an empty runtime target configuration keeps every
retained entry blocked from activation.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("capability_registry", ROOT / "scripts" / "build-capability-registry.py")
assert SPEC and SPEC.loader
REGISTRY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REGISTRY)

FAMILIES = ("core", "product", "planning", "design", "engineering", "orchestration", "review", "qa", "delivery", "knowledge", "platform")
COMMANDS = {"core": "stack", "product": "stack.explore", "planning": "stack.plan", "design": "stack.design", "engineering": "stack.build", "orchestration": "stack.orchestrate", "review": "stack.review", "qa": "stack.qa", "delivery": "stack.ship", "knowledge": "stack.learn", "platform": "stack.maintain"}
MERGES = {"cdo-deslop": "deslop", "cdo-rams": "rams", "cdo-react-doctor": "react-doctor", "taste-skill-suite-taste-skill": "cdo-taste-skill"}
LEGACY_ROUTERS = {
    "agent-operating-stack": "core-stack",
    "mega-workflow": "core-run",
    "departments": "core-run",
    "ideate": "cpo",
}
ALIASES = {**MERGES, **LEGACY_ROUTERS}
COMMAND_OVERRIDES = {
    "core-stack": "stack",
    "core-run": "stack.run",
    "agent-operating-stack": "stack",
    "mega-workflow": "stack.run",
    "departments": "stack.run",
    "ideate": "stack.explore",
}
PRIMARY_CAPABILITIES = {"core-stack", "core-run", "cpo"}
PURPOSE_OVERRIDES = {
    "agent-operating-stack": "Deprecated compatibility alias for the canonical Stack root router.",
    "mega-workflow": "Deprecated compatibility alias for the canonical full Stack workflow run.",
    "departments": "Deprecated compatibility alias for the canonical Stack planning run.",
    "ideate": "Deprecated compatibility alias for canonical Stack exploration.",
}
PRIMARY_TARGETS = {
    "claude": ".claude/skills/stack",
    "codex": ".codex/skills/stack",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def provider_for(path: str) -> tuple[str, str]:
    for provider in ("matt", "david", "impeccable", "studio", "ui", "emil", "taste-skill-suite", "other"):
        if path.startswith(f"skills/imported/{provider}/"):
            return provider, "imported-skills"
    for prefix, provider in (("skills/matt-", "matt"), ("skills/david-", "david"), ("skills/impeccable/", "impeccable"), ("skills/studio/", "studio"), ("skills/ui-skills/", "ui"), ("skills/emil-", "emil"), ("skills/taste-skill-suite/", "impeccable")):
        if path.startswith(prefix):
            return provider, "imported-skills"
    return "stack", "stack"


def family_for(name: str, path: str) -> str:
    for family in FAMILIES:
        if path.startswith(f"skills/{family}/"):
            return family
    if name in {"agent-operating-stack", "mega-workflow", "departments"}:
        return "core"
    if path.startswith("skills/orchestration/") or name in {"goal-validation-threads", "david-codex-subagent", "david-cmux", "david-handoff", "david-goal-loop", "david-agent-self-scheduling", "matt-handoff", "david-run-deep-swe"}:
        return "orchestration"
    if path.startswith("skills/studio/product/") or name in {"cpo", "ideate", "matt-to-spec", "matt-to-tickets", "matt-triage", "matt-wayfinder"}:
        return "product"
    if path.startswith("skills/studio/research/") or name in {"field-theory-bookmark-synthesis", "fieldbook-source-split", "david-deep-research", "david-research-prompt", "david-youtube-transcript", "matt-research", "muller-brockmann-grid-systems", "userinterface-wiki"}:
        return "knowledge"
    if path.startswith(("skills/studio/design/", "skills/impeccable/", "skills/ui-skills/", "skills/cdo/")) or name in {"cdo", "emil-design-eng", "illo", "better-icons", "review-animations", "ui-design-brain", "make-interfaces-feel-better", "design-intelligence", "rams", "deslop", "taste-skill-suite-soft-skill", "taste-skill-suite-redesign-skill", "cdo-taste-skill"}:
        return "design"
    if name in {"tdd", "matt-tdd", "matt-implement", "matt-prototype", "matt-diagnosing-bugs", "matt-codebase-design", "matt-domain-modeling", "matt-improve-codebase-architecture", "matt-ask-matt", "react-doctor", "simplify", "knip", "fix-sentry-issues", "gemini-review"}:
        return "engineering"
    if name in {"matt-code-review", "david-cyber-audit", "david-google-safe-browsing", "scratch-eval-promotion-gate", "agent-verification-ladder"}:
        return "review"
    if name in {"david-browser-harness", "live-site-health-check", "review-animations", "fixing-accessibility", "fixing-metadata", "fixing-motion-performance"} or "accessibility" in name:
        return "qa"
    if path.startswith("skills/studio/ship/") or name in {"stack-refresh-pr-mode", "david-push-skill-to-github"}:
        return "delivery"
    if name in {"local-tracker-dashboard", "reclaude", "david-setup-help", "david-effective-agent-skills", "david-distribute-skill-to-all-agents", "david-folder-specific-claude-and-agents-md", "david-pi-custom-model"}:
        return "platform"
    return "planning" if name.startswith("matt-") else "engineering"


def role_for(name: str, path: str, family: str) -> str:
    if name in ALIASES:
        return "alias"
    if name == "core-stack":
        return "router"
    if name == "core-run":
        return "workflow"
    if name in {"cdo", "cpo", "menu", "illo", "matt-ask-matt"}:
        return "router"
    if family in {"orchestration", "delivery", "planning"}:
        return "workflow"
    return "leaf"


def command_for(name: str, family: str) -> str:
    return COMMAND_OVERRIDES.get(name, COMMANDS[family])


def trust_for(family: str, name: str) -> str:
    if name in {"core-run", "mega-workflow", "departments"}:
        return "local-mutation"
    if family == "delivery":
        return "external-mutation"
    if family in {"engineering", "orchestration", "platform"}:
        return "local-mutation"
    return "read-only"


def write_manifest(path: Path, value: dict[str, Any]) -> None:
    path.write_text(canonical_json(value), encoding="utf-8")


def primary_targets_configured(targets: list[Any]) -> bool:
    """Return true only for the two safe, namespaced primary destinations."""
    if len(targets) != len(PRIMARY_TARGETS):
        return False
    seen: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            return False
        name, runtime, destination = target.get("name"), target.get("runtime"), target.get("destination")
        if not all(isinstance(value, str) and value for value in (name, runtime, destination)):
            return False
        if name != runtime or name not in PRIMARY_TARGETS or destination != PRIMARY_TARGETS[name] or name in seen:
            return False
        verifier = target.get("post_switch_verifier")
        if not isinstance(verifier, list) or not verifier or not all(isinstance(value, str) and value for value in verifier):
            return False
        seen.add(name)
    return seen == set(PRIMARY_TARGETS)


def classify(root: Path) -> dict[str, Any]:
    REGISTRY.seed_missing_manifests(root)
    runtime_targets = json.loads((root / "config" / "runtime-targets.json").read_text(encoding="utf-8"))["targets"]
    targets_ready = primary_targets_configured(runtime_targets)
    runtime_block = "Configure structurally valid Claude and Codex primary runtime targets before activation."
    manifests: list[tuple[Path, dict[str, Any]]] = []
    for manifest_path in REGISTRY.manifest_paths(root):
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
        source_path = value["source"].get("skill_path", manifest_path.parent.relative_to(root).as_posix() + "/SKILL.md")
        name = value["canonical_name"]
        family = family_for(name, source_path)
        provider, package = provider_for(source_path)
        alias_target = ALIASES.get(name)
        role = role_for(name, source_path, family)
        value.update({
            "purpose": PURPOSE_OVERRIDES.get(name, value["purpose"]),
            "domain": family,
            "family": family,
            "role": role,
            "visibility": "compatibility" if alias_target else ("primary" if name in PRIMARY_CAPABILITIES else "extended"),
            "commands": [command_for(name, family)],
            "ownership": {"provider": provider, "package": package, "source_path": source_path},
            "context": {"inputs": ["request", "workspace-context"], "outputs": ["capability-result"]},
            "trust_class": trust_for(family, name),
            "validation_class": "high-risk" if trust_for(family, name) == "external-mutation" else "representative-route",
            "audit_status": "reviewed",
            "runtimes": {"supported": ["claude", "codex"], "publish_targets": ["claude", "codex"]},
        })
        if alias_target:
            disposition = "demote" if name in LEGACY_ROUTERS else "merge"
            value.update({"lifecycle": "deprecated", "disposition": {"status": disposition, "evidence_gap": None, "next_review_trigger": "Remove only after compatibility retirement review."}, "validation": {"status": "validated", "evidence": ["reviewed-estate-refactor", "structural-classification"]}, "alias_of": alias_target})
        elif targets_ready:
            value.update({"lifecycle": "active", "disposition": {"status": "keep", "evidence_gap": None, "next_review_trigger": "Reassess on source, export, or runtime-target change."}, "validation": {"status": "validated", "evidence": ["reviewed-estate-refactor", "structural-classification", "primary-runtime-parity"]}})
        else:
            value.pop("alias_of", None)
            value.update({"lifecycle": "candidate", "disposition": {"status": "hold-pending-evidence", "evidence_gap": runtime_block, "next_review_trigger": "Configure Claude and Codex runtime targets, then compile and verify."}, "validation": {"status": "blocked", "evidence": ["reviewed-estate-refactor", "structural-classification", "runtime-targets-empty"]}})
        manifests.append((manifest_path, value))
    targets = {target: value for _, value in manifests for target in [value.get("alias_of")] if target}
    for _, value in manifests:
        if value["canonical_name"] in targets:
            value["compatibility_aliases"] = sorted(key for key, target in ALIASES.items() if target == value["canonical_name"])
        elif value.get("compatibility_aliases"):
            value.pop("compatibility_aliases")
    for path, value in manifests:
        write_manifest(path, value)
    return reconcile(root, runtime_targets)


def reconcile(root: Path, runtime_targets: list[Any]) -> dict[str, Any]:
    skills = sorted(path.relative_to(root).as_posix() for path in (root / "skills").glob("**/SKILL.md"))
    manifests = {json.loads(path.read_text(encoding="utf-8"))["source"]["skill_path"]: path.relative_to(root).as_posix() for path in REGISTRY.manifest_paths(root)}
    packages = []
    for path in sorted((root / "packages").glob("*/package.json")):
        value = json.loads(path.read_text(encoding="utf-8")); packages.append({"path": path.relative_to(root).as_posix(), "provider": value["provider"], "exports": value.get("exports", [])})
    inventory = json.loads((root / "registry" / "inventory-sources.json").read_text(encoding="utf-8"))
    missing = sorted(set(skills) - set(manifests))
    package_exports = [
        {"provider": package["provider"], "export": export, "status": "external-native-owner", "reason": "Published through the pinned package and represented by a Stack route adapter."}
        for package in packages for export in package["exports"]
    ]
    private_declarations = sorted(path.relative_to(root).as_posix() for path in (root / "registry").glob("private-*.json"))
    status = "primary-parity-ready" if primary_targets_configured(runtime_targets) else ("not-configured" if not runtime_targets else "invalid-primary-targets")
    return {"schema_version": 1, "kind": "phase1-capability-reconciliation", "allowlisted_roots": inventory["allowlisted_roots"], "reviewed_exclusions": inventory["reviewed_exclusions"], "callable_skills": {"discovered": skills, "classified": manifests, "missing": missing}, "packages": packages, "package_exports": package_exports, "runtime_injections": {"configured": runtime_targets, "status": status}, "private_declarations": {"discovered": private_declarations, "status": "schema-only-no-declared-overlays"}, "counts": {"callable_skills": len(skills), "manifests": len(manifests), "unclassified": len(missing), "package_exports": len(package_exports), "private_declarations": len(private_declarations)}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(); root = args.root.resolve()
    reconciliation = reconcile(root, json.loads((root / "config" / "runtime-targets.json").read_text())["targets"]) if args.check else classify(root)
    output = root / "artifacts" / "audits" / "phase1-architecture" / "capability-reconciliation.json"
    expected = canonical_json(reconciliation)
    if args.check:
        return 0 if output.is_file() and output.read_text(encoding="utf-8") == expected and not reconciliation["callable_skills"]["missing"] else 1
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(expected, encoding="utf-8")
    print(f"classified {reconciliation['counts']['manifests']} manifests; reconciled {reconciliation['counts']['callable_skills']} callable skills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
