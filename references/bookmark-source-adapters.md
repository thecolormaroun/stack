# Bookmark source adapters

`collect-bookmark-candidates.py` is a read-only collection boundary. It records
raw observations only in its owner-only local SQLite ledger; its JSON receipt
contains opaque intake identifiers and aggregate status only.

| Adapter | Inputs | Cursor | Notes |
| --- | --- | --- | --- |
| `field_theory` | configured SQLite, JSONL, or Markdown files | content digest of the configured snapshot | SQLite rows, JSON objects, and Markdown links are normalized as inert data. |
| `arc_snapshot` | configured Arc sidebar JSON snapshot | snapshot digest | Recursively finds bookmark-like URL/title objects; it never writes Arc state. |
| `github_stars` | `gh api --paginate --slurp user/starred` or configured fixture items | page/revision digest | Uses the existing `gh` credential store only. Slurped pages are flattened locally. Missing credentials are a visible source failure, never a prompt or token log. Private repositories are discarded. |
| `github_links` | GitHub repository URLs derived from earlier Field Theory, Arc, or Hermes observations in the same run; configured fixtures are also supported | verified repository revision, metadata, and policy digest | Uses bounded `gh api repos/OWNER/REPO` reads to verify public visibility and capture license/activity metadata. It never clones repositories or fetches arbitrary page bodies. Verified public records survive a partial run even when another linked repository is private or inaccessible. |
| `hermes_link_inbox` | Hermes `links` table selected through `STACK_HERMES_LINK_INBOX_DB` | row revision/content digest | Reads only `intake_id`, `original_url`, `canonical_url`, and `updated_at` through SQLite read-only mode. The local DB path stays in the private environment; it is never stored in source config, receipts, or packets. Hermes opaque intake IDs are retained. |

Run with no `--apply` for a dry run. `--apply` is required before the local
ledger is updated. The default ledger is outside this repository:
`~/.local/state/stack/bookmark-intake.sqlite` (directory mode `0700`, database
mode `0600`). Use `--ledger` to select another owner-controlled path for tests
or a bounded local run.
