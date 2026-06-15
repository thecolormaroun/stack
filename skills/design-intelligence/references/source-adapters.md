---
id: design-intelligence.source-adapters
name: Design Intelligence Source Adapters
description: Read-only source map for weekly design intelligence intake.
---

# Source Adapters

All adapters are read-only during intake. They may create a run-local manifest, but they must not mark source rows processed, edit browser state, sync accounts, or write permanent notes.

## Curated Web Sources

| Source | Focus | Notes |
|--------|-------|-------|
| Brian Lovin `/sites` and writing | Product taste, systems, design engineering | High signal; prefer current `/sites` entries plus new essays. |
| Design Spells | Micro-interactions and delightful details | JS-heavy; use a browser-capable scrape if plain fetch is thin. |
| Handheld Design | Mobile product decisions and rationale | Substack; capture article title, date, and pattern. |
| Featured Mobile | Curated mobile UI examples | JS-heavy; if extraction fails, record failure in the manifest. |

## Arc Bookmarks

Default local source:

```text
~/Library/Application Support/Arc/StorableSidebar.json
```

Supplemental date source:

```text
~/Library/Application Support/Arc/User Data/Default/History
```

Use the sidebar as the canonical bookmark-like source. Use History only to enrich recency because Arc sidebar records can lack a useful saved date.

Safe read-only scan:

```bash
python3 /Users/maroun/hermes/scripts/mookie_link_inbox.py arc scan \
  --path "$HOME/Library/Application Support/Arc/StorableSidebar.json" \
  --dry-run
```

Design relevance signals:
- title or URL contains design, interface, UI, UX, typography, motion, brand, landing, dashboard, component, product, portfolio, layout, mobile, animation, Figma, Framer, Mobbin, Awwwards, Godly, Land-book, Refero, SiteInspire, Screenlane, Lapa, SaaSFrame, or Landingfolio.
- recent `timeLastActiveAt` activity after the run window start.
- matching Arc history visit in the run window.

Do not run `mookie_link_inbox.py process --apply` from this loop; that mutates saved-link processing state.

## Field Theory / X Bookmarks

Default local source root:

```text
~/.ft-bookmarks
```

Expected surfaces:

```text
~/.ft-bookmarks/bookmarks.db
~/.ft-bookmarks/bookmarks.jsonl
~/.ft-bookmarks/md/bookmarks/
~/.ft-bookmarks/media/
```

Use SQLite first because it has `tweet_id`, `url`, `text`, `posted_at`, `synced_at`, `primary_domain`, `categories`, `domains`, `links_json`, and `media_count`.

Important date rule: current Field Theory rows may not have `bookmarked_at`. Use `synced_at` for local capture/import recency and `posted_at` for content recency.

Design relevance signals:
- `primary_domain = 'design'`.
- `categories`, `domains`, `article_title`, `article_text`, or tweet text contains the design terms listed in the Arc section.
- attached media count or link count is nonzero.

Syncing through Arc cookies is a separate guarded operation. Do not run it from the digest unless the operator explicitly approves account sync:

```bash
/Users/maroun/hermes/scripts/field-theory-sync-from-arc.py --max-minutes 30
```

## GBrain

Default source roots:

```text
~/.gbrain/source-roots/x-bookmarks-native
~/.gbrain/source-roots/saved-links
```

Use GBrain to detect what has already been imported and where Field Theory is ahead. The weekly digest should prefer the live Field Theory corpus for newest X bookmarks, then report GBrain deltas as an ingestion/backfill lane.

The loop may stage review manifests under Hermes tmp or a new GBrain-owned source root only after approval. It must not edit `.ft-bookmarks`, Arc, Vault, or mark any row processed.

## Source Manifest

Each run should record:
- exact path or URL for each source.
- whether the source was reachable/readable.
- candidate counts per source.
- design-relevant candidate counts in the run window.
- GBrain delta counts, especially Field Theory bookmark markdown files missing from `x-bookmarks-native`.
- failures and extraction limits.

