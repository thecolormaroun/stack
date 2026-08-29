# Bookmark source adapters

U15 keeps the public Stack repository at the boundary of the private corpus.
Raw bookmark rows, text, media, cursors, source paths, and owner metadata stay
in the owner-local ledger described by `config/bookmark-private-ledger.json`.
Tracked snapshots and receipts contain only opaque identities, aggregate
counts, and canonical SHA-256 digests.

## Field Theory/X default source

`field_theory` is the canonical X boundary and is read-only by default. The
adapter may read either a synthetic fixture or one explicitly configured
owner-local export. For SQLite it executes one allowlisted query only:

- table: `bookmarks`
- columns: the exact `field_theory_contract.columns` list in
  `config/bookmark-sources.json`
- media roots: the exact configured `media_roots` list, which defaults to an
  empty list

It never enumerates SQLite tables, reads FTS/helper tables, walks arbitrary
media directories, follows bookmark links, or performs network hydration.
Unknown tables, columns, missing required columns, and unallowlisted media
roots fail closed. The adapter records source-native identity, canonical
identity, revision, folders, media/link status, and raw-response digests in a
page receipt without exposing their values.

## Completeness and backfill

`reconcile-bookmark-sources.py` emits a dry-run snapshot by default. A
completed snapshot proves cursor exhaustion, page count, folder/revision/media
coverage, canonical set digest, and a safe zero-delta comparison when a prior
snapshot is supplied. Cursor cycles, page gaps, 429 responses, partial media,
and unavailable observations downgrade the snapshot to `partial` and retain
only an opaque resume digest in public output.

`backfill-bookmark-history.py` is a bounded project, separate from recurring
delta mode. It resumes from an owner-local checkpoint and requires the exact
`u15-backfill-approved-v1` contract before creating state. Repeating an
identical terminal run is a zero-delta `no_action`; it does not restart from
the first page.

## Optional direct X parity

Direct API parity is disabled and has no network fallback. An approved parity
contract must use only the `bookmark.read` scope, reference an OS secret by
opaque name, include rotation/revocation metadata, and separately prove
provider-spend approval. Plaintext tokens, token-like config fields, missing
metadata, or unapproved requests are rejected before any network operation.
Diagnostics are status classes and digests only.

## GBrain handoff

`import-bookmark-deltas.py` defines transport contract
`gbrain-cli-markdown-v1`: set source scope to `x-bookmarks`, import an
owner-local markdown directory with the installed CLI shape
`gbrain import DIRECTORY --source-id x-bookmarks --json`. Stack keeps the
content-set idempotency key in its owner-local marker/receipt; it is not passed
as an unsupported CLI flag. Import JSON is reduced to stable counts and
accepted/partial/failed states. The source-scoped canary uses
`GBRAIN_SOURCE=x-bookmarks gbrain search OPAQUE_IDENTITY --limit 1` and marks
`indexed` only when the successful output contains that identity. The current
CLI is selected through the owner environment; tests inject a fake transport
and no live mutation is performed by this repository run.

Import remains dry-run by default and requires the exact
`x-bookmarks-import-approved-v1` contract to apply. `accepted` means the
transport accepted the content; it becomes `indexed` only after a
source-scoped text retrieval canary. Rejected and pending identities remain
resumable and are never silently treated as indexed.

## Other adapters

Arc, GitHub, and Hermes remain optional U5 child adapters. Their absence or
failure cannot weaken an X completeness claim or expand the source contract.
They continue to use the existing U5 read-only boundaries and public-safe
opaque receipts.
