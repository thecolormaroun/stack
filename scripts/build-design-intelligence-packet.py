#!/usr/bin/env python3
"""Build an owner-local, quarantined U16 design-intelligence packet.

The input boundary is deliberately small: a U15 public observation may be
paired with an owner-local raw companion.  Raw content is used only to make a
source-faithful card and is never copied into the packet's evidence manifest.
The default analyzer is deterministic and local.  There is no provider
client, network fallback, or implicit model call in this module.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
CODE_VERSION = "design-intelligence-packet-v1"
DEFAULT_MODEL = "local-deterministic-v1"
DEFAULT_PROMPT = "design-intelligence-card-v1"
OPAQUE_RE = re.compile(r"^[a-z][a-z0-9-]{1,32}:[a-f0-9]{16,64}$")
DIGEST_RE = re.compile(r"^[a-f0-9]{64}$")
SAFE_SOURCE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
VOLATILE_KEYS = {
    "generated_at", "run_started_at", "run_finished_at", "observed_at",
    "created_at", "updated_at", "capture_time", "captured_at",
}
PRIVATE_TERMS = {
    "medical", "health", "diagnosis", "medication", "mom", "mother",
    "dad", "father", "family", "private", "personal", "password",
    "credential", "bank", "finance", "financial", "ssn", "relationship",
    "wedding", "child", "children", "patient", "therapy", "insurance",
}
DESIGN_TERMS = {
    "accessibility", "animation", "a11y", "component", "css", "design",
    "figma", "frontend", "icon", "interaction", "interface", "layout",
    "mobile", "motion", "product", "responsive", "screen", "style",
    "table", "typography", "ui", "ux", "visual", "web", "software",
}
PROMPT_INJECTION_RE = re.compile(
    r"(?:ignore\s+(?:all|the|previous|prior)\s+instructions?|system\s+prompt|"
    r"developer\s+message|delete\s+(?:all\s+)?files?|wipe\s+the\s+repo|"
    r"publish\s+(?:this|the)\s+(?:packet|prompt|content)|use\s+tools?|"
    r"approve\s+(?:this|the)\s+(?:change|candidate))",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
PATH_RE = re.compile(r"(?:^|\s)/(?:Users|home|tmp|var|private)/[^\s]+")

ANALYSIS_FIELDS = (
    "visible_facts", "interpretation_critique", "reusable_principle",
    "suitable_contexts", "anti_pattern_failure_mode", "accessibility",
    "motion", "responsive_behavior", "implementation_cue", "uncertainty",
    "interface_problem", "design_behavior",
)
LIST_FIELDS = {
    "visible_facts", "interpretation_critique", "reusable_principle",
    "suitable_contexts", "anti_pattern_failure_mode", "implementation_cue",
}
STRUCTURED_FIELDS = {"accessibility", "motion", "responsive_behavior"}


class DesignIntelligenceError(ValueError):
    """A fail-closed packet or owner-local output error."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _stable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _stable_value(child)
            for key, child in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_stable_value(child) for child in value]
    if isinstance(value, tuple):
        return [_stable_value(child) for child in value]
    return value


def digest(value: Any, *, stable: bool = True) -> str:
    material = _stable_value(value) if stable else value
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def opaque(prefix: str, value: Any, length: int = 64) -> str:
    return f"{prefix}:{digest(value)[:length]}"


def _digest_value(value: Any, fallback: Any = None) -> str:
    if isinstance(value, str) and DIGEST_RE.fullmatch(value):
        return value
    return digest(value if value is not None else fallback)


def _safe_opaque(value: Any, prefix: str) -> str:
    if isinstance(value, str) and OPAQUE_RE.fullmatch(value):
        return value
    return opaque(prefix, value)


def _safe_source_id(value: Any) -> str:
    text = str(value or "unknown")
    if SAFE_SOURCE_RE.fullmatch(text):
        return text
    return "source-" + digest(text)[:24]


def owner_local_path(path: Path, label: str = "owner-local output") -> Path:
    """Resolve a path and reject the public Stack checkout."""

    resolved = Path(path).expanduser().resolve(strict=False)
    try:
        resolved.relative_to(ROOT)
    except ValueError:
        return resolved
    raise DesignIntelligenceError(f"{label} must be outside the repository checkout")


def write_packet(path: Path, packet: dict[str, Any]) -> Path:
    target = owner_local_path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(target.parent, 0o700)
        encoded = json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        target.write_text(encoded, encoding="utf-8")
        os.chmod(target, 0o600)
    except OSError as exc:
        raise DesignIntelligenceError(f"unable to write owner-local packet: {exc}") from exc
    return target


def write_markdown(path: Path, markdown: str) -> Path:
    target = owner_local_path(path, "owner-local markdown output")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(target.parent, 0o700)
        target.write_text(markdown, encoding="utf-8")
        os.chmod(target, 0o600)
    except OSError as exc:
        raise DesignIntelligenceError(f"unable to write owner-local markdown: {exc}") from exc
    return target


def hydrate_from_owner_ledger(input_doc: dict[str, Any], ledger_path: Path) -> dict[str, Any]:
    """Join a public U15 snapshot to its exact owner-local raw rows read-only."""

    ledger = owner_local_path(ledger_path, "owner-local U15 ledger")
    if not ledger.is_file():
        raise DesignIntelligenceError("owner-local U15 ledger is unavailable")
    observations = input_doc.get("observations", [])
    if not isinstance(observations, list):
        raise DesignIntelligenceError("packet observations must be an array")
    direct = [item for item in observations if isinstance(item, dict) and isinstance(item.get("evidence_id"), str)]
    evidence_ids = sorted({item["evidence_id"] for item in direct})
    raw_by_evidence: dict[str, dict[str, Any]] = {}
    try:
        connection = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
        try:
            if evidence_ids:
                placeholders = ",".join("?" for _ in evidence_ids)
                rows = connection.execute(
                    f"SELECT evidence_id, raw_json FROM source_observations WHERE evidence_id IN ({placeholders})",
                    evidence_ids,
                )
                for evidence_id, raw_json in rows:
                    value = json.loads(raw_json)
                    if not isinstance(value, dict):
                        raise DesignIntelligenceError("owner-local U15 raw row must be an object")
                    raw_by_evidence[str(evidence_id)] = value
        finally:
            connection.close()
    except (sqlite3.Error, OSError, json.JSONDecodeError) as exc:
        raise DesignIntelligenceError("owner-local U15 ledger contract is invalid") from exc
    hydrated: list[Any] = []
    for item in observations:
        if not isinstance(item, dict) or not isinstance(item.get("evidence_id"), str):
            hydrated.append(item)
            continue
        raw = raw_by_evidence.get(item["evidence_id"])
        hydrated.append({
            "observation": item,
            "raw": raw if raw is not None else {"owner_local_record_state": "missing"},
        })
    result = dict(input_doc)
    result["observations"] = hydrated
    return result


def _canonical_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    host = parts.hostname.lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return None
    host = {"www.twitter.com": "x.com", "twitter.com": "x.com", "www.x.com": "x.com"}.get(host, host)
    path = re.sub(r"/+", "/", parts.path).rstrip("/") or "/"
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}]
    return urlunsplit(("https", host, path, urlencode(sorted(query)), ""))


def _contains_prompt_injection(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_prompt_injection(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_prompt_injection(child) for child in value)
    return isinstance(value, str) and bool(PROMPT_INJECTION_RE.search(value))


def _text(raw: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("text", "article_text", "article_title", "title", "description", "topics", "tags"):
        value = raw.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(str(child) for child in value if isinstance(child, (str, int, float)))
    return " ".join(values)


def _all_text(value: Any) -> str:
    """Flatten owner-local strings for privacy checks only."""

    values: list[str] = []
    if isinstance(value, dict):
        for child in value.values():
            text = _all_text(child)
            if text:
                values.append(text)
    elif isinstance(value, list):
        for child in value:
            text = _all_text(child)
            if text:
                values.append(text)
    elif isinstance(value, str):
        values.append(value)
    return " ".join(values)


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9-]+", value.lower()))


def _source_record(item: Any) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not isinstance(item, dict):
        return None, {}
    public: Any = item.get("observation") or item.get("public")
    if not isinstance(public, dict):
        public = item if isinstance(item.get("evidence_id"), str) else None
    raw = item.get("raw") or item.get("owner_local") or item.get("raw_observation")
    if not isinstance(raw, dict):
        # Direct synthetic fixtures may place the owner-local companion beside
        # the public projection.  Do not mistake the U15 metadata for content.
        raw = {
            key: value for key, value in item.items()
            if key not in {"observation", "public", "raw", "owner_local", "raw_observation"}
            and key not in {"schema_version", "evidence_id", "source_id", "source_identity",
                            "original_source_identity", "canonical_source_identity", "capture_time",
                            "revision_time", "revision_digest", "content_digest", "media",
                            "media_item_digests", "media_item_states", "link_capture", "folder_ids",
                            "completeness_state", "adapter_version", "derivation"}
        }
    elif isinstance(raw.get("row"), dict):
        # ``bookmark_private_corpus.normalize_observation`` stores the actual
        # U15 row under ``row`` beside its private media/link projections.
        # Flatten only for local analysis; the row is never copied to output.
        flattened = dict(raw)
        flattened.update(raw["row"])
        raw = flattened
    return public, raw


def _identity(public: dict[str, Any], key: str, prefix: str) -> str:
    return _safe_opaque(public.get(key), prefix)


def _evidence_citation(public: dict[str, Any]) -> dict[str, Any]:
    media = public.get("media") if isinstance(public.get("media"), dict) else {}
    links = public.get("link_capture") if isinstance(public.get("link_capture"), dict) else {}
    content_digest = _digest_value(public.get("content_digest"), public)
    revision_digest = _digest_value(public.get("revision_digest"), content_digest)
    media_digest = _digest_value(media.get("digest"), public.get("media_item_digests", []))
    link_digest = _digest_value(links.get("set_digest"), public.get("link_capture", {}))
    return {
        "evidence_id": _identity(public, "evidence_id", "evidence"),
        "source_id": _safe_source_id(public.get("source_id")),
        "source_identity": _identity(public, "source_identity", "source"),
        "original_source_identity": _identity(public, "original_source_identity", "source-native"),
        "canonical_source_identity": _identity(public, "canonical_source_identity", "bookmark"),
        "capture_time": str(public.get("capture_time", "")),
        "revision_time": str(public.get("revision_time", "")),
        "content_digest": content_digest,
        "revision_digest": revision_digest,
        "media_digest": media_digest,
        "media_item_digests": sorted(
            value for value in public.get("media_item_digests", []) if isinstance(value, str) and DIGEST_RE.fullmatch(value)
        ),
        "link_digest": link_digest,
        "link_digests": sorted(
            value for value in links.get("digests", []) if isinstance(value, str) and DIGEST_RE.fullmatch(value)
        ),
        "completeness_state": str(public.get("completeness_state", "unknown")),
        "adapter_version": str(public.get("adapter_version", "unknown")),
        "lineage_digest": _digest_value(
            public.get("derivation", {}).get("lineage_digest")
            if isinstance(public.get("derivation"), dict) else None,
            public,
        ),
    }


def _lineage_key(public: dict[str, Any], raw: dict[str, Any]) -> str:
    for key in ("lineage_key", "article_url", "canonical_article_url"):
        value = raw.get(key)
        canonical = _canonical_url(value)
        if canonical:
            return "url:" + canonical
    links = raw.get("links") or raw.get("links_json")
    if isinstance(links, str):
        try:
            links = json.loads(links)
        except json.JSONDecodeError:
            links = []
    if isinstance(links, list):
        for value in links:
            canonical = _canonical_url(value)
            if canonical:
                return "url:" + canonical
    for key in ("canonical_url", "url", "original_url", "thread_url", "link"):
        value = raw.get(key)
        canonical = _canonical_url(value)
        if canonical:
            return "url:" + canonical
    return "identity:" + _identity(public, "canonical_source_identity", "bookmark")


def _claim_key(public: dict[str, Any], raw: dict[str, Any]) -> tuple[str, bool]:
    claim = raw.get("claim") or raw.get("claim_text") or raw.get("assertion") or raw.get("conflicting_claim")
    if isinstance(claim, str) and claim.strip():
        return "claim:" + digest(re.sub(r"\s+", " ", claim.strip()).lower()), True
    if raw.get("conflict") is True or raw.get("conflicting") is True:
        text = raw.get("text") or raw.get("article_text") or raw.get("title") or ""
        if isinstance(text, str) and text.strip():
            return "conflict-text:" + digest(re.sub(r"\s+", " ", text.strip()).lower()), True
    for key in ("visible_facts", "reusable_principle", "interpretation_critique"):
        value = raw.get(key)
        if isinstance(value, list) and value:
            return key + ":" + digest([str(item).strip() for item in value]), True
    return "content:" + _digest_value(public.get("content_digest"), public), False


def _eligibility(public: dict[str, Any] | None, raw: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(public, dict):
        return "quarantined", "malformed_observation"
    identity_fields = (
        "evidence_id", "source_identity", "original_source_identity",
        "canonical_source_identity",
    )
    digest_fields = ("content_digest", "revision_digest")
    if (
        any(not isinstance(public.get(key), str) or not OPAQUE_RE.fullmatch(public[key]) for key in identity_fields)
        or any(not isinstance(public.get(key), str) or not DIGEST_RE.fullmatch(public[key]) for key in digest_fields)
        or not isinstance(public.get("source_id"), str)
        or not SAFE_SOURCE_RE.fullmatch(public["source_id"])
    ):
        return "quarantined", "malformed_observation"
    state = str(public.get("completeness_state", "unknown"))
    if state not in {"accepted", "revised"}:
        if state in {"deleted", "missing", "rejected", "unavailable"}:
            return "no_candidate", f"source_{state}"
        return "quarantined", "incomplete_observation"
    if raw.get("owner_local_record_state") == "missing":
        return "quarantined", "owner_local_record_missing"
    if raw.get("private") is True or raw.get("sensitive") is True:
        return "no_candidate", "private_or_sensitive"
    source_text = _text(raw)
    private_hits = _tokens(_all_text(raw)) & PRIVATE_TERMS
    if private_hits:
        return "no_candidate", "personal_or_sensitive_topic"
    if _contains_prompt_injection(raw):
        return "quarantined", "prompt_injection_quoted"
    explicit_relevance = raw.get("software_design_relevant") is True or raw.get("design_relevant") is True
    explicit_facts = raw.get("visible_facts")
    has_media = isinstance(public.get("media"), dict) and int(public.get("media", {}).get("count", 0) or 0) > 0
    if not explicit_relevance and not (_tokens(source_text) & DESIGN_TERMS) and not (has_media and explicit_facts):
        return "no_candidate", "outside_software_design_scope"
    return "carded", "eligible"


def _as_strings(value: Any, *, limit: int = 8) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = [child for child in value if isinstance(child, str)]
    else:
        values = []
    result: list[str] = []
    for value in values:
        text = re.sub(r"\s+", " ", value).strip()
        if not text or URL_RE.search(text) or PATH_RE.search(text) or PROMPT_INJECTION_RE.search(text):
            continue
        result.append(text[:400])
    return result[:limit]


def _structured(value: Any, *, unknown: list[str]) -> dict[str, list[str]]:
    if isinstance(value, dict):
        observed = _as_strings(value.get("observed"))
        notes = _as_strings(value.get("notes"))
        supplied_unknown = _as_strings(value.get("unknown"))
        return {"observed": observed, "unknown": supplied_unknown or unknown, "notes": notes}
    values = _as_strings(value)
    return {"observed": values, "unknown": [] if values else unknown, "notes": []}


def _default_analysis(public: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    source_text = _text(raw)
    tokens = _tokens(source_text)
    explicit_facts = _as_strings(raw.get("visible_facts"))
    has_screenshot = bool(raw.get("media")) or (
        isinstance(public.get("media"), dict) and int(public.get("media", {}).get("count", 0) or 0) > 0
    )
    if explicit_facts:
        facts = explicit_facts
    elif has_screenshot:
        facts = ["A visual or screenshot reference is present in the supplied evidence."]
    else:
        facts = ["The source explicitly discusses software or interface design."]
    explicit_accessibility = raw.get("accessibility") or raw.get("accessibility_notes")
    accessibility = _structured(
        explicit_accessibility,
        unknown=["Accessibility behavior is not verifiable from the supplied evidence."]
        if not (tokens & {"accessibility", "a11y", "contrast", "keyboard", "screen", "reader"}) else [],
    )
    explicit_motion = raw.get("motion") or raw.get("motion_notes")
    motion = _structured(
        explicit_motion,
        unknown=["Motion behavior was not observable from the supplied evidence."]
        if has_screenshot and not (tokens & {"motion", "animation", "animated", "transition", "hover"}) else [],
    )
    explicit_responsive = raw.get("responsive_behavior") or raw.get("responsive")
    responsive = _structured(
        explicit_responsive,
        unknown=["Responsive behavior was not observable from the supplied evidence."]
        if has_screenshot and not (tokens & {"responsive", "mobile", "viewport", "breakpoint"}) else [],
    )
    if tokens & {"table", "density", "dense"}:
        interface_problem, design_behavior = "information-density", "comparative-hierarchy"
    elif tokens & {"responsive", "mobile", "viewport", "breakpoint"}:
        interface_problem, design_behavior = "responsive-composition", "priority-recomposition"
    elif tokens & {"motion", "animation", "animated", "transition", "hover"}:
        interface_problem, design_behavior = "state-communication", "purposeful-transition"
    elif tokens & {"typography", "type", "hierarchy"}:
        interface_problem, design_behavior = "content-hierarchy", "typographic-hierarchy"
    else:
        interface_problem, design_behavior = "interface-composition", "visible-hierarchy"
    interpretation = _as_strings(raw.get("interpretation_critique") or raw.get("critique"))
    if not interpretation:
        interpretation = ["Interpret the visible hierarchy in the context of the active product task; do not copy treatment by default."]
    principle = _as_strings(raw.get("reusable_principle") or raw.get("principle"))
    if not principle:
        principle = ["Make the primary hierarchy and state boundaries legible before adding decorative treatment."]
    contexts = _as_strings(raw.get("suitable_contexts") or raw.get("contexts")) or ["software interface work"]
    anti_pattern = _as_strings(raw.get("anti_pattern_failure_mode") or raw.get("anti_pattern") or raw.get("failure_mode"))
    if not anti_pattern:
        anti_pattern = ["Avoid importing the treatment without validating hierarchy, accessibility, and task fit."]
    cue = _as_strings(raw.get("implementation_cue") or raw.get("implementation"))
    if not cue:
        cue = ["Encode the observed hierarchy as explicit states, tokens, and responsive constraints before implementation."]
    uncertainty = _as_strings(raw.get("uncertainty"))
    if has_screenshot:
        uncertainty.append("Screenshot evidence cannot establish unseen behavior, interaction, or responsive change.")
    if not uncertainty:
        uncertainty = ["The card preserves only claims supported by the supplied source evidence."]
    return {
        "visible_facts": facts,
        "interpretation_critique": interpretation,
        "reusable_principle": principle,
        "suitable_contexts": contexts,
        "anti_pattern_failure_mode": anti_pattern,
        "accessibility": accessibility,
        "motion": motion,
        "responsive_behavior": responsive,
        "implementation_cue": cue,
        "uncertainty": uncertainty,
        "interface_problem": interface_problem,
        "design_behavior": design_behavior,
    }


def _analysis_context(
    public: dict[str, Any], raw: dict[str, Any], allowed_fields: list[str] | None = None,
) -> dict[str, Any]:
    # Keep the injected analyzer on a safe, non-operational context.  In
    # particular, no URL, path, or instruction-bearing source text is passed.
    context = {
        "evidence_id": _identity(public, "evidence_id", "evidence"),
        "source_id": _safe_source_id(public.get("source_id")),
        "source_identity": _identity(public, "source_identity", "source"),
        "content_digest": _digest_value(public.get("content_digest"), public),
        "visible_facts": _as_strings(raw.get("visible_facts")),
        "topic_terms": sorted(_tokens(_text(raw)) & DESIGN_TERMS),
        "media_present": bool(raw.get("media")) or bool(public.get("media", {}).get("count", 0) if isinstance(public.get("media"), dict) else False),
    }
    if allowed_fields is None:
        return context
    return {field: context[field] for field in allowed_fields if field in context}


def _provider_contract(input_doc: dict[str, Any], derivation: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str]:
    """Validate the explicit egress contract without creating a provider client."""

    given = derivation if isinstance(derivation, dict) else {}
    candidate = given.get("provider_contract") or input_doc.get("provider_contract")
    if candidate is None and isinstance(input_doc.get("policy"), dict):
        candidate = input_doc["policy"].get("provider_contract")
    if candidate is None:
        return None, "default_deny"
    if not isinstance(candidate, dict):
        return None, "invalid_provider_contract"
    required = {"state", "provider", "allowed_fields", "redaction", "retention", "training", "log_redaction"}
    if set(candidate) != required:
        return None, "invalid_provider_contract"
    if candidate.get("state") != "approved" or not isinstance(candidate.get("provider"), str):
        return None, "invalid_provider_contract"
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{1,63}", candidate["provider"]):
        return None, "invalid_provider_contract"
    allowed = candidate.get("allowed_fields")
    context_fields = {"evidence_id", "source_id", "source_identity", "content_digest", "visible_facts", "topic_terms", "media_present"}
    if not isinstance(allowed, list) or not allowed or not all(isinstance(field, str) and field in context_fields for field in allowed):
        return None, "invalid_provider_contract"
    if len(set(allowed)) != len(allowed):
        return None, "invalid_provider_contract"
    required_posture = {
        "redaction": "opaque-identities-and-digests-only",
        "retention": "none",
        "training": "none",
        "log_redaction": "opaque-only",
    }
    for key, expected in required_posture.items():
        if candidate.get(key) != expected:
            return None, "invalid_provider_contract"
    return {
        "state": "approved",
        "provider": candidate["provider"],
        "allowed_fields": list(allowed),
        "redaction": candidate["redaction"],
        "retention": candidate["retention"],
        "training": candidate["training"],
        "log_redaction": candidate["log_redaction"],
    }, "approved_contract"


def _merge_analysis(default: dict[str, Any], candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        return default
    merged = dict(default)
    for field in ANALYSIS_FIELDS:
        if field not in candidate:
            continue
        if field in LIST_FIELDS:
            values = _as_strings(candidate[field])
            if values:
                merged[field] = values
        elif field in STRUCTURED_FIELDS:
            merged[field] = _structured(candidate[field], unknown=default[field].get("unknown", []))
        elif field in {"interface_problem", "design_behavior"}:
            value = candidate[field]
            if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9-]{1,63}", value):
                merged[field] = value
    return merged


def _derivation_config(input_doc: dict[str, Any], derivation: dict[str, Any] | None) -> dict[str, str]:
    given = derivation if isinstance(derivation, dict) else {}
    policy = given.get("policy", input_doc.get("policy", {"provider_egress": "deny"}))
    config = given.get("config", input_doc.get("config", {"analyzer": "local-deterministic"}))
    sampling = given.get("sampling", input_doc.get("sampling", {"temperature": 0, "seed": 0}))
    return {
        "policy_digest": _digest_value(given.get("policy_digest"), policy),
        "config_digest": _digest_value(given.get("config_digest"), config),
        "code_digest": _digest_value(given.get("code_digest"), CODE_VERSION),
        "prompt_digest": _digest_value(given.get("prompt_digest"), given.get("prompt", DEFAULT_PROMPT)),
        "model_digest": _digest_value(given.get("model_digest"), given.get("model", DEFAULT_MODEL)),
        "sampling_digest": _digest_value(given.get("sampling_digest"), sampling),
    }


def _input_state(source_manifest: Any, delta: Any, observations: list[Any]) -> str:
    manifest_state = source_manifest.get("state") if isinstance(source_manifest, dict) else None
    if not manifest_state and isinstance(source_manifest, dict):
        manifest_state = source_manifest.get("completeness_state")
    if not manifest_state and isinstance(source_manifest, dict) and source_manifest.get("failure"):
        manifest_state = "failed"
    normalized = str(manifest_state or "complete").lower()
    if normalized in {"failed", "error"}:
        return "failed"
    if normalized in {"partial", "incomplete"}:
        return "partial"
    if normalized in {"unknown", "unavailable", "not_configured"}:
        return "failed"
    if normalized in {"empty", "no_input"} or not observations:
        return "empty"
    return "complete"


def _delta_state(delta: Any, input_state: str, cards: list[dict[str, Any]]) -> str:
    if isinstance(delta, dict):
        state = str(delta.get("state", "")).lower()
        if state in {"failed", "partial", "empty", "unchanged", "complete", "changed"}:
            return state
        if delta.get("changed") is False:
            return "unchanged"
    if input_state == "failed":
        return "failed"
    if input_state == "partial":
        return "partial"
    if input_state == "empty" or not cards:
        return "empty"
    return "changed"


def _source_manifest_summary(source_manifest: Any, observation_count: int, input_state: str, delta_digest: str) -> dict[str, Any]:
    manifest = source_manifest if isinstance(source_manifest, dict) else {}
    sources = manifest.get("sources")
    source_count = len(sources) if isinstance(sources, list) else int(manifest.get("source_count", 0) or 0)
    return {
        "manifest_id": opaque("manifest", {"digest": digest(manifest), "state": input_state}),
        "digest": digest(manifest),
        "state": input_state,
        "source_count": max(0, source_count),
        "observation_count": observation_count,
        "delta_digest": delta_digest,
        "owner_local": True,
    }


def _previous_revisions(input_doc: dict[str, Any]) -> dict[str, list[str]]:
    previous = input_doc.get("previous_packet") or input_doc.get("prior_packet")
    if not isinstance(previous, dict):
        return {}
    result: dict[str, list[str]] = {}
    for card in previous.get("cards", []):
        if not isinstance(card, dict):
            continue
        lineage = card.get("lineage_id")
        revision = card.get("revision_id") or card.get("card_id")
        if isinstance(lineage, str) and isinstance(revision, str):
            result.setdefault(lineage, []).append(revision)
    return {key: sorted(set(value)) for key, value in result.items()}


def _card(
    public_records: list[dict[str, Any]],
    analysis: dict[str, Any],
    lineage_id: str,
    claim_key: str,
    config: dict[str, str],
    prior_revisions: list[str],
) -> dict[str, Any]:
    citations = sorted((_evidence_citation(public) for public in public_records), key=lambda value: value["evidence_id"])
    evidence_ids = [citation["evidence_id"] for citation in citations]
    claim_digest = digest(claim_key)
    parent_digests = sorted({citation["content_digest"] for citation in citations})
    revision_material = {
        "schema_version": SCHEMA_VERSION,
        "lineage_id": lineage_id,
        "claim_digest": claim_digest,
        "analysis": analysis,
        "evidence_ids": evidence_ids,
        "derivation": config,
        "supersedes_revisions": prior_revisions,
    }
    revision_id = opaque("revision", revision_material)
    card_id = opaque("card", revision_material)
    provenance = {
        "evidence_ids": evidence_ids,
        "original_source_identities": sorted({citation["original_source_identity"] for citation in citations}),
        "canonical_source_identities": sorted({citation["canonical_source_identity"] for citation in citations}),
        "content_digests": parent_digests,
        "media_digests": sorted({citation["media_digest"] for citation in citations}),
        "link_digests": sorted({citation["link_digest"] for citation in citations}),
        "policy_digest": config["policy_digest"],
        "config_digest": config["config_digest"],
        "code_digest": config["code_digest"],
        "prompt_digest": config["prompt_digest"],
        "model_digest": config["model_digest"],
        "sampling_digest": config["sampling_digest"],
        "parent_digest": digest(parent_digests),
        "parent_digests": parent_digests,
        "derivation_lineage": {
            "was_derived_from": evidence_ids,
            "was_generated_by": opaque("activity", {"code_digest": config["code_digest"], "revision_id": revision_id}),
            "lineage_digest": digest({"lineage_id": lineage_id, "evidence_ids": evidence_ids, "derivation": config}),
        },
        "supersedes_revisions": prior_revisions,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "card_id": card_id,
        "lineage_id": lineage_id,
        "revision_id": revision_id,
        "status": "quarantined",
        "approval_state": "unapproved",
        "interface_problem": analysis["interface_problem"],
        "design_behavior": analysis["design_behavior"],
        "visible_facts": analysis["visible_facts"],
        "interpretation_critique": analysis["interpretation_critique"],
        "reusable_principle": analysis["reusable_principle"],
        "suitable_contexts": analysis["suitable_contexts"],
        "anti_pattern_failure_mode": analysis["anti_pattern_failure_mode"],
        "accessibility": analysis["accessibility"],
        "motion": analysis["motion"],
        "responsive_behavior": analysis["responsive_behavior"],
        "implementation_cue": analysis["implementation_cue"],
        "uncertainty": analysis["uncertainty"],
        "claim_digest": claim_digest,
        "evidence_citations": citations,
        "provenance": provenance,
    }


def _leak_paths(value: Any, prefix: str = "") -> list[str]:
    leaks: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            location = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in {"url", "urls", "path", "paths", "raw", "text", "title", "excerpt", "content", "prompt"}:
                leaks.append(location)
            leaks.extend(_leak_paths(child, location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            leaks.extend(_leak_paths(child, f"{prefix}[{index}]"))
    elif isinstance(value, str) and (URL_RE.search(value) or PATH_RE.search(value)):
        leaks.append(prefix or "value")
    return leaks


def _cluster(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for card in cards:
        key = (card["interface_problem"], card["design_behavior"])
        groups.setdefault(key, []).append(card)
    result = []
    for (problem, behavior), values in sorted(groups.items()):
        result.append({
            "cluster_id": opaque("cluster", {"problem": problem, "behavior": behavior}),
            "interface_problem": problem,
            "design_behavior": behavior,
            "card_ids": sorted(card["card_id"] for card in values),
            "count": len(values),
        })
    return result


def _lineage_graph(cards_by_lineage: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    result = []
    for lineage_id, cards in sorted(cards_by_lineage.items()):
        citations = [citation for card in cards for citation in card["evidence_citations"]]
        unique = {citation["evidence_id"]: citation for citation in citations}
        evidence_ids = sorted(unique)
        edges = []
        conflicting = len({card["claim_digest"] for card in cards}) > 1
        for left, right in zip(evidence_ids, evidence_ids[1:]):
            edges.append({"from_evidence_id": left, "to_evidence_id": right, "relation": "conflict" if conflicting else "duplicate_or_related"})
        result.append({
            "lineage_id": lineage_id,
            "evidence_ids": evidence_ids,
            "source_identities": sorted({citation["source_identity"] for citation in unique.values()}),
            "original_source_identities": sorted({citation["original_source_identity"] for citation in unique.values()}),
            "canonical_source_identities": sorted({citation["canonical_source_identity"] for citation in unique.values()}),
            "card_ids": sorted(card["card_id"] for card in cards),
            "edges": edges,
        })
    return result


def _contradictions(cards_by_lineage: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    result = []
    for lineage_id, cards in sorted(cards_by_lineage.items()):
        claim_groups = {}
        for card in cards:
            claim_groups.setdefault(card["claim_digest"], []).append(card)
        if len(claim_groups) < 2:
            continue
        result.append({
            "contradiction_id": opaque("contradiction", {"lineage": lineage_id, "claims": sorted(claim_groups)}),
            "lineage_id": lineage_id,
            "claim_digests": sorted(claim_groups),
            "card_ids": sorted(card["card_id"] for card in cards),
            "evidence_ids": sorted({citation["evidence_id"] for card in cards for citation in card["evidence_citations"]}),
            "uncertainty": "Conflicting claims remain distinct; the source evidence does not authorize a single resolution.",
        })
    return result


def _candidate_changes(cards: list[dict[str, Any]], status: str) -> list[dict[str, Any]]:
    if not cards or status == "no_action":
        return []
    return [
        {
            "change_id": opaque("candidate", {"card": card["card_id"], "revision": card["revision_id"]}),
            "state": "candidate_quarantined",
            "card_id": card["card_id"],
            "revision_id": card["revision_id"],
            "evidence_ids": [citation["evidence_id"] for citation in card["evidence_citations"]],
            "target": "review-gated design reference or skill proposal",
            "promotion": "blocked_pending_human_review_and_eval",
        }
        for card in cards
    ]


def _retrieval_updates(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "update_id": opaque("retrieval", {"card": card["card_id"], "revision": card["revision_id"]}),
            "state": "pending_quarantined",
            "card_id": card["card_id"],
            "revision_id": card["revision_id"],
            "evidence_ids": [citation["evidence_id"] for citation in card["evidence_citations"]],
            "retrieval_truth": False,
        }
        for card in cards
    ]


def build_packet(
    input_doc: dict[str, Any] | list[Any],
    *,
    analyzer: Callable[[dict[str, Any]], Any] | None = None,
    derivation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic packet; injected analyzers are explicitly opt-in."""

    if isinstance(input_doc, list):
        input_doc = {"observations": input_doc}
    if not isinstance(input_doc, dict):
        raise DesignIntelligenceError("packet input must be an object or observation list")
    raw_items = input_doc.get("observations", [])
    if not isinstance(raw_items, list):
        raise DesignIntelligenceError("packet observations must be an array")
    source_manifest = input_doc.get("source_manifest", {})
    delta = input_doc.get("delta", {})
    input_state = _input_state(source_manifest, delta, raw_items)
    config = _derivation_config(input_doc, derivation)
    provider_contract, provider_state = _provider_contract(input_doc, derivation)
    analyzer_allowed = analyzer is not None and provider_contract is not None
    analyzer_call_count = 0
    public_records: list[tuple[dict[str, Any], dict[str, Any], str, str, str]] = []
    dispositions: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items):
        public, raw = _source_record(item)
        state, reason = _eligibility(public, raw)
        citation = _evidence_citation(public) if isinstance(public, dict) else None
        evidence_id = citation["evidence_id"] if citation else opaque("evidence", {"index": index, "item": "malformed"})
        disposition: dict[str, Any] = {"evidence_id": evidence_id, "state": "carded" if state == "carded" else state, "reason": reason}
        if citation:
            disposition["source_identity"] = citation["source_identity"]
            disposition["canonical_source_identity"] = citation["canonical_source_identity"]
        dispositions.append(disposition)
        if state != "carded" or not isinstance(public, dict):
            continue
        lineage_key = _lineage_key(public, raw)
        claim_key, explicit_claim = _claim_key(public, raw)
        public_records.append((public, raw, lineage_key, claim_key, "explicit" if explicit_claim else "implicit"))

    # Preserve source evidence while collapsing duplicate lineage.  Explicit
    # claim keys partition a lineage only when there is more than one claim;
    # implicit observations merge even when adapters supplied different raw
    # envelopes for the same canonical source.
    grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any], str, str, str]]] = {}
    for record in public_records:
        grouped.setdefault(record[2], []).append(record)
    cards: list[dict[str, Any]] = []
    cards_by_lineage: dict[str, list[dict[str, Any]]] = {}
    prior = _previous_revisions(input_doc)
    for lineage_key, records in sorted(grouped.items()):
        explicit_keys = sorted({record[3] for record in records if record[4] == "explicit"})
        if len(explicit_keys) > 1:
            partitions = {key: [record for record in records if record[3] == key] for key in explicit_keys}
            # Unspecified duplicate evidence stays attached to the first claim
            # rather than creating a fabricated third claim.
            unspecified = [record for record in records if record[4] != "explicit"]
            if unspecified:
                partitions[explicit_keys[0]].extend(unspecified)
        elif explicit_keys:
            partitions = {explicit_keys[0]: records}
        else:
            partitions = {"merged": records}
        lineage_id = opaque("lineage", lineage_key)
        for claim_key, partition in sorted(partitions.items()):
            public_values = [record[0] for record in partition]
            raw_values = [record[1] for record in partition]
            analysis = _default_analysis(public_values[0], raw_values[0])
            if len(explicit_keys) > 1:
                conflict_uncertainty = "Conflicting claims remain distinct; do not treat this card as settled guidance."
                if conflict_uncertainty not in analysis["uncertainty"]:
                    analysis["uncertainty"].append(conflict_uncertainty)
            if analyzer_allowed:
                try:
                    analyzer_call_count += 1
                    analysis = _merge_analysis(
                        analysis,
                        analyzer(_analysis_context(public_values[0], raw_values[0], provider_contract["allowed_fields"])),
                    )
                except Exception as exc:  # injected analyzers cannot break the safety envelope
                    raise DesignIntelligenceError("injected analyzer failed closed") from exc
            card = _card(public_values, analysis, lineage_id, claim_key, config, prior.get(lineage_id, []))
            cards.append(card)
            cards_by_lineage.setdefault(lineage_id, []).append(card)
    contradictions = _contradictions(cards_by_lineage)
    cards.sort(key=lambda card: (card["lineage_id"], card["claim_digest"], card["revision_id"]))
    graph = _lineage_graph(cards_by_lineage)
    clusters = _cluster(cards)
    observation_digest_material = [
        {"public": public, "raw": raw, "lineage": lineage, "claim": claim}
        for public, raw, lineage, claim, _ in public_records
    ]
    manifest_digest = digest(source_manifest)
    delta_digest = _digest_value(
        delta.get("digest") if isinstance(delta, dict) else None,
        delta if isinstance(delta, dict) and delta else observation_digest_material,
    )
    input_digest_value = digest({
        "source_manifest_digest": manifest_digest,
        "delta_digest": delta_digest,
        "observations": observation_digest_material,
        "derivation": config,
    })
    delta_state = _delta_state(delta, input_state, cards)
    status = (
        "failed" if input_state == "failed" or delta_state == "failed"
        else "partial" if input_state == "partial" or delta_state == "partial"
        else "no_action" if delta_state in {"empty", "unchanged"}
        else "prepared"
    )
    candidate_changes = _candidate_changes(cards, status)
    packet: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "packet_id": opaque("packet", input_digest_value),
        "status": status,
        "approval_state": "unapproved",
        "input_digest": {
            "state": input_state,
            "digest": input_digest_value,
            "source_manifest_digest": manifest_digest,
            "delta_digest": delta_digest,
            "delta_state": delta_state,
        },
        "source_manifest": _source_manifest_summary(source_manifest, len(raw_items), input_state, delta_digest),
        "cards": cards,
        "dispositions": sorted(dispositions, key=lambda value: value["evidence_id"]),
        "lineage_graph": graph,
        "clusters": clusters,
        "contradictions": contradictions,
        "reusable_patterns": [
            {
                "pattern_id": opaque("pattern", {"problem": cluster["interface_problem"], "behavior": cluster["design_behavior"]}),
                "interface_problem": cluster["interface_problem"],
                "design_behavior": cluster["design_behavior"],
                "card_ids": cluster["card_ids"],
                "state": "quarantined",
            }
            for cluster in clusters
        ],
        "retrieval_updates": _retrieval_updates(cards),
        "candidate_changes": candidate_changes,
        "egress": {
            "default_deny": True,
            "provider_contract": provider_contract["provider"] if provider_contract else "none",
            "provider_contract_digest": digest(provider_contract) if provider_contract else digest({"state": "denied"}),
            "analyzer_state": "approved_contract" if analyzer_allowed else "denied" if analyzer is not None else "not_requested",
            "denial_reason": None if analyzer_allowed or analyzer is None else provider_state,
            "analyzer_calls": analyzer_call_count,
            "provider_calls": 0,
            "analyzer": "injected-fake" if analyzer_allowed else "local-deterministic",
            "network": "not_attempted",
        },
        "derivation": config,
        "privacy": {
            "raw_inputs_owner_local": True,
            "unapproved_outputs_quarantined": True,
            "retrieval_truth": False,
            "public_leak_scan": "pending",
            "prompt_instructions_are_data": True,
        },
    }
    packet["weekly_markdown"] = render_weekly_markdown(packet)
    if _leak_paths(packet):
        raise DesignIntelligenceError("packet privacy scan failed")
    packet["privacy"]["public_leak_scan"] = "passed"
    packet["packet_digest"] = digest(packet)
    return packet


def _markdown_list(values: Any, fallback: str = "Not supplied.") -> str:
    items = _as_strings(values)
    return "\n".join(f"- {item}" for item in items) if items else f"- {fallback}"


def render_weekly_markdown(packet: dict[str, Any], template_path: Path | None = None) -> str:
    """Render Output A/B/C without URLs, paths, or raw source prose."""

    template = template_path or ROOT / "templates/weekly-design-intelligence.md"
    try:
        body = template.read_text(encoding="utf-8")
    except OSError:
        body = (
            "# Weekly Design Intelligence - {{WINDOW_LABEL}}\n\n"
            "## Execution Log\n\n- Status: {{STATUS}}\n\n"
            "## Output A - Design Digest\n{{OUTPUT_A}}\n\n"
            "## Output B - Zettelkasten Candidates\n{{OUTPUT_B}}\n\n"
            "## Output C - Studio Skill Update Candidates\n{{OUTPUT_C}}\n"
        )
    cards = packet.get("cards", []) if isinstance(packet.get("cards"), list) else []
    output_a: list[str] = []
    for index, card in enumerate(cards, start=1):
        citations = ", ".join(citation["evidence_id"] for citation in card.get("evidence_citations", []))
        output_a.append(
            f"### {index}. {card.get('interface_problem', 'interface-composition')} / {card.get('design_behavior', 'visible-hierarchy')}\n\n"
            f"- What: {_markdown_list(card.get('visible_facts'))}\n"
            f"- Why it matters: {_markdown_list(card.get('reusable_principle'))}\n"
            f"- Evidence IDs: {citations or 'none'}\n"
            f"- Apply this: {_markdown_list(card.get('implementation_cue'))}"
        )
    candidate_changes = packet.get("candidate_changes", []) if isinstance(packet.get("candidate_changes"), list) else []
    output_b = "- No candidate note: no approved or durable note change was authorized." if not candidate_changes else "\n".join(
        f"- Candidate for quarantined review: {item.get('card_id', 'opaque-card')} (evidence-backed; do not write by default)."
        for item in candidate_changes[:3]
    )
    output_c = "- No skill update candidate: review and eval gates remain closed." if not candidate_changes else "\n".join(
        f"- Candidate remains quarantined: {item.get('change_id', 'opaque-candidate')}; target: review-gated design reference or skill proposal."
        for item in candidate_changes[:3]
    )
    replacements = {
        "{{WINDOW_LABEL}}": "owner-local weekly run",
        "{{STATUS}}": str(packet.get("status", "failed")),
        "{{SOURCE_STATUS}}": str(packet.get("input_digest", {}).get("state", "failed")),
        "{{OUTPUT_A}}": "\n\n".join(output_a) if output_a else "- No eligible design cards.",
        "{{OUTPUT_B}}": output_b,
        "{{OUTPUT_C}}": output_c,
        "{{SHORT_SUMMARY}}": "- Cards remain owner-local and quarantined pending review and evaluation.",
    }
    for marker, value in replacements.items():
        body = body.replace(marker, value)
    return body.rstrip() + "\n"


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DesignIntelligenceError(f"invalid packet input: {path}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="owner-local U15 observation envelope")
    parser.add_argument("--out", type=Path, required=True, help="owner-local packet JSON path")
    parser.add_argument("--ledger", type=Path, help="owner-local U15 observation ledger for public snapshot hydration")
    parser.add_argument("--markdown-out", type=Path, help="optional owner-local weekly markdown path")
    parser.add_argument("--policy", type=Path, help="optional deterministic policy document")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--code-digest")
    parser.add_argument("--sampling", default='{"temperature":0,"seed":0}')
    args = parser.parse_args(argv)
    try:
        input_doc = load_json(args.input)
        if args.ledger:
            if not isinstance(input_doc, dict):
                raise DesignIntelligenceError("ledger hydration requires an object input")
            input_doc = hydrate_from_owner_ledger(input_doc, args.ledger)
        policy = load_json(args.policy) if args.policy else {"provider_egress": "deny"}
        try:
            sampling = json.loads(args.sampling)
        except json.JSONDecodeError as exc:
            raise DesignIntelligenceError("--sampling must be JSON") from exc
        packet = build_packet(
            input_doc,
            derivation={
                "model": args.model,
                "prompt": args.prompt,
                "code_digest": args.code_digest or CODE_VERSION,
                "sampling": sampling,
                "policy": policy,
            },
        )
        write_packet(args.out, packet)
        if args.markdown_out:
            write_markdown(args.markdown_out, packet["weekly_markdown"])
    except (OSError, TypeError, ValueError, DesignIntelligenceError) as exc:
        print(f"design-intelligence packet failed closed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
