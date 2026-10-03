# Public synthetic HTML generation

`scripts/generate-design-intelligence-artifacts.py` is a separate, quarantined preparation lane. It runs the installed Codex CLI once for baseline instructions and once for candidate instructions, producing real HTML files for the same public synthetic brief. It does not judge quality, create evaluation scores or human feedback, supply frozen fixture results, install a skill, publish a runtime, or change the weekly promotion adapter. The existing adapter's `candidate_evaluation_render_binding_unavailable` block remains in place.

This lane is available only for content deliberately reviewed as **public and synthetic**. Codex uses an authenticated provider. The generator screens obvious private data and requires owner-only inputs, but neither that screen nor the requested tool settings attest full prompt closure or process isolation. Do not submit private Field Theory content, household information, live user tasks, protected holdouts, or unpublished source material.

## Inputs and exact usage

The caller supplies an absolute, regular `0600` JSON manifest in an owner-only directory, its *raw-file* SHA-256 reviewed separately, an absolute Stack checkout path, and an absolute owner-only output directory outside the checkout and inputs. The packet, materialization receipt, and patch must also be absolute owner-owned `0600` files. The checkout HEAD must equal the packet base; selected edit and target paths must be clean. Unrelated dirty files are preserved.

Manifest schema (every field is required; unknown fields are rejected):

```json
{
  "schema_version": 1,
  "run_id": "public-synthetic-run-01",
  "content_scope": "synthetic_non_private",
  "task": {
    "case_id": "public-case-01",
    "text": "Build a public synthetic dashboard for fictional data.",
    "viewport": {"width": 1280, "height": 800}
  },
  "model": {"name": "gpt-6-luna", "reasoning_effort": "max"},
  "codex": {
    "executable": "/opt/homebrew/bin/codex",
    "launcher_sha256": "<64 lowercase hex>",
    "native_sha256": "<64 lowercase hex>",
    "node_sha256": "<64 lowercase hex>"
  },
  "candidate_packet": {"path": "/absolute/owner/packet.json", "sha256": "<64 lowercase hex>"},
  "materialization": {"path": "/absolute/owner/materialization-receipt.json", "sha256": "<64 lowercase hex>"},
  "patch": {"path": "/absolute/owner/capability-change.patch", "sha256": "<64 lowercase hex>"},
  "target": {
    "canonical_name": "reviewed-capability",
    "capability_path": "skills/design/reviewed-capability/SKILL.md",
    "provider": "stack",
    "package": "stack",
    "upstream_pin": null
  },
  "instruction_paths": [
    {"path": "skills/design/reviewed-capability/SKILL.md", "before_sha256": "<64 lowercase hex>", "after_sha256": "<64 lowercase hex>"}
  ]
}
```

`target` must exactly equal the packet target. `instruction_paths` must contain the target `SKILL.md` and every edited skill/reference Markdown path, with exact before and after hashes. For a reference-only change, the unchanged target has the same before and after hash. Other packet edits are verified against the patch but never put into the model prompt. The packet and materialization validators, pinned Git blobs, candidate content, and a freshly reconstructed isolated Git diff must all agree with the supplied patch file and SHA.

The allowlisted model pairs are `gpt-6-luna/max`, `gpt-6-sol/high`, and `gpt-6-sol/max`. The installed executable chain is pinned to the Homebrew Codex command, its JavaScript launcher, its arm64 native binary, and Node. Generate the hashes from those exact reviewed files. A package update requires a new manifest review.

```sh
python3 scripts/generate-design-intelligence-artifacts.py \
  --manifest /absolute/owner/generation.json \
  --reviewed-manifest-sha256 <raw-manifest-sha256> \
  --repository /absolute/stack-checkout \
  --output-dir /absolute/owner/generation-run \
  --prepare
```

`--prepare` verifies the bindings and prints only compact digest metadata. It makes zero model calls. After reviewing that exact manifest and accepting provider use for its public synthetic contents, replace `--prepare` with `--execute`. No implicit execute mode exists. `--execute` rechecks the same bindings and ChatGPT login status before each variant. It has no API-key fallback. Raw prompts, event streams, stderr, reasoning, and errors are never logged or printed by this script.

Rejected event streams may add a fixed-category `reason` to the compact error response. Categories distinguish provider errors, failed turns, tool items, multiple messages and unknown lifecycle shapes; model text, event names outside the fixed allowlist, tool arguments and error bodies are never included. The pinned [Codex JSONL converter](https://raw.githubusercontent.com/openai/codex/rust-v0.156.1/codex-rs/exec/src/event_processor_with_jsonl_output.rs) emits completed agent messages without phase metadata, while the [CLI output schema](https://raw.githubusercontent.com/openai/codex/rust-v0.156.1/codex-rs/exec/src/cli.rs) applies to the final response. This producer deliberately still rejects multiple or ambiguous messages: it does not guess which is final. A successful installed-CLI canary is required before using this lane in any integration. A rejected uncertain attempt stays blocked and must not be evaded with a different output directory.

## Artifacts and resumption

The output directory contains an owner-only WorkflowStore database, immutable run binding, output schema, `artifacts/baseline.html`, `artifacts/candidate.html`, per-variant receipts, and a final receipt. All artifact files are `0600`; directories are `0700`. A process lock, one child lease, renewal during model execution, and checkpoints prevent overlapping calls. A repeat of a verified completed run returns the receipt with zero new provider calls. If the final receipt was checkpointed before an interruption in child completion, it is verified and the expired or failed child is completed without calling the provider; a still-live lease blocks recovery. A completed baseline also survives interruption before the candidate attempt. An attempt checkpoint without its certified output receipt blocks automatic replay because the provider may already have charged for the call; it requires manual reconciliation. Changed inputs, helpers, executable bytes, output bytes, foreign state, or lock contention fail closed.

The model receives only the public synthetic task text, viewport, and exact selected instruction bytes, target first and other paths sorted. Source lineage, rationale, local paths, receipt metadata, variant names, expected outcomes, and bookmarks are omitted from the constructed stdin prompt. Markdown references and includes inside instruction text are **not followed or verified as a closure**. The Codex host may inject other instructions or expose tools despite requested CLI settings; `tool_isolation` is recorded as `requested_not_attested`, `provider_prompt_closure` as `unverified`, and observed model identity as `null` unless an authoritative runtime record is added later. The raw stdin SHA and requested model are bound; they do not prove the complete provider prompt or model actually used.

The returned HTML must be UTF-8, at most 64 KB after guarding, and static. Scripts, event handlers, HTML comments, SVG, MathML, forms, frames, external assets, and ambiguous content before the explicit `head` are rejected. All HTML comments are excluded because Python and browser parsers can disagree on malformed comment boundaries, hiding active markup from a validator. Immediately after that opening `head`, the producer inserts this policy before any model-authored resource:

```text
default-src 'none'; script-src 'none'; connect-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; object-src 'none'
```

This [early document Content Security Policy](https://www.w3.org/TR/CSP/#meta-element) adds browser-enforced denial of scripts and network resources; it is not a browser-process sandbox or a complete substitute for offline browser controls. Inline CSS and raster data images are allowed. The per-variant `provider_html_sha256` binds the original model-authored HTML before the policy is inserted; `html_sha256` binds the guarded bytes actually saved, and `html_policy_revision` identifies the transformation. Original event streams and unguarded HTML are not persisted. Resumption verifies both the saved digest and the guarded form.

These documents support static layout comparisons only. Interactive task behavior needs a separate verified execution lane; do not treat an inert button as a completed interaction. The collector still supplies its own offline browser controls if these artifacts are later examined. Generation receipts remain `not_evaluated` and cannot authorize a score, promotion, or activation.
