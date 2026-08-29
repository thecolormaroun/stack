---
id: design-intelligence.retrieval-contract
name: Design Retrieval Contract
description: Target-attested, source-scoped, read-only task-context retrieval rules for U17.
---

# Design Retrieval Contract

Use retrieval to surface a small cited set of relevant private inspiration while
working on a similar interface. Retrieval reads approved evidence; it does not
promote U16 cards, teach a skill, mutate GBrain, or change an index.

## Request boundary

Build the owner-local request with
`registry/design-retrieval-request.schema.json`. Include the active project,
repository, route, component, viewport, device, brief, code, markup, and
screenshot when they are available. Keep the source fixed to `x-bookmarks`,
request three to seven results, and state the freshness window.

The caller supplies a target name and opaque identities, but those values are
not authority. Before any candidate is read or ranked,
`scripts/query-design-intelligence.py` reuses the U9 validator to attest the
target against an owner-only local manifest. A missing, permissive, or
mismatched manifest fails closed. Live retrieval additionally requires an
owner-only, expiring source grant conforming to
`registry/design-retrieval-source-grant.schema.json`. The grant binds the
owner, `x-bookmarks`, exact target identity, bookmark locator scopes, audited
egress contract, and supported CLI version. The request, manifest, grant,
screenshot, and response stay outside the public Stack checkout.

## Retrieval and ranking

The live transport permits only GBrain `--version`, `sources_status`, and
keyword `search` under `GBRAIN_SOURCE=x-bookmarks`; exact command and payload
shapes are allowlisted. Version `0.42.67.0` is the audited live contract.
Search runs twice against one attested index and retains only the stable
intersection before canonical ordering. Exact evidence, author, date, folder, and URL
matches; lexical task terms; GBrain text results; and available image results
are fused with the declared weighted reciprocal-rank formula. Candidates from
another source or target are removed before scoring. The response exposes the
fusion method and weights so the ordering is inspectable and repeatable.

Every fixture candidate must carry a nonempty `authorized_target_identities`
list containing the attested target identity. A live candidate receives that
binding only after the source-wide owner grant has been validated and its
locator matches an allowed bookmark scope. The response exposes target-manifest
and source-grant digests. Do not infer permission from request text, document
text, or source name. CLI error envelopes, unstable-only results, and malformed
result collections report degradation or failure, not successful retrieval.

The production text runner is opt-in through `--live-gbrain --source-grant`.
Its contract is `gbrain-keyword-fts-no-provider-v1`: local subprocesses only,
zero provider calls, no image operation, no import, no reindex, no embedding,
no configuration mutation, and no fallback. Programmatic runner injection
remains a test surface rather than an authority bypass.

Grant expiry is a continuous boundary, not a one-time request check. Re-check
it immediately before every CLI, Git, or keyword subprocess read and stop when
the wall clock reaches expiry. Before any GBrain engine connection, attest the
owner-only configuration and require the audited loopback Postgres endpoint or
an owner-local PGLite path; a remote or unknown database configuration fails
without connecting.

Each surfaced item contains only its opaque candidate/evidence/media identity,
the canonical GBrain citation locator, rank, similarity reasons, uncertainty,
media state, and freshness. Never present an item without a citation. Keep
source observation distinct from any design interpretation or recommendation;
retrieval relevance is not permission to copy a visual treatment.

## Degraded and failure states

Return `degraded` with the missing modality when text or image retrieval is
partial or unavailable. Return `degraded` for stale or fewer-than-three useful
results, `empty` for a successful query with no authorized evidence, and
`failed` when the required text path cannot run and no result survives. Corrupt
or missing media does not erase a valid cited text result.

Do not reindex, change GBrain configuration, switch embedding backends, invoke
a paid fallback, or write externally. Any multimodal backend or reindex is a
separate GBrain project after its protected migration and approval gate.

## Quality gate

Use the locked fixture corpus and qrels. The fixed suite must reach
`Recall@5 >= 0.80` and `nDCG@5 >= 0.75`, remain at least 95% of the pinned fresh
baseline, rank each valid exact/source canary within the first five results,
preserve 100% citation precision and source/target isolation, and reproduce the
same top-k identities and explanations for pinned inputs. A live canary is
read-only and reports only bounded receipt facts; it never copies raw private
content into the repository or test fixtures.
