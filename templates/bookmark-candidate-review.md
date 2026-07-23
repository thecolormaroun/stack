# Bookmark Candidate Review Packet

Run: `{{run_id}}`
Policy digest: `{{policy_digest}}`
Decision cap: `{{decision_cap}}`

## Required human gates

1. Provenance review confirms source trust, license, and immutable pin.
2. Evaluation review confirms the sandbox artifact and applicable evaluation target.
3. Publication review is required separately; this packet cannot activate a catalog entry or runtime.

## Decisions

| Rank | Opaque intake ID | Disposition | Score | Gate |
| --- | --- | --- | --- | --- |
{{candidate_rows}}

## Deferred for later review

| Rank | Opaque intake ID | Disposition | Score |
| --- | --- | --- | --- |
{{deferred_rows}}

## Safety boundary

This public packet intentionally excludes source URLs, titles, notes, excerpts, local paths, credentials, and raw bookmark content. Evaluation is immutable-pin, sandboxed, network-denied, credential-free, temporary-workspace-only, and artifact-only.
