---
id: design-intelligence.output-contract
name: Design Intelligence Output Contract
description: Required digest, backfill, and promotion packet structure.
---

# Output Contract

Every run creates a reviewable packet. A good packet proves what was read, what failed, what was learned, and what should happen next.

## Files

Recommended run folder:

```text
/Users/maroun/Codex/tmp/design-intelligence/runs/YYYY-MM-DD/
```

Required files:

```text
source-manifest.json
weekly-design-digest-YYYY-MM-DD.md
promotion-packet.md
```

Historical backfills should use one folder per weekly chunk:

```text
/Users/maroun/hermes/tmp/design-intelligence-backfill/YYYY-MM-DD..YYYY-MM-DD/YYYY-MM-DD..YYYY-MM-DD/
```

## Weekly Digest

Use `templates/weekly-digest.md`.

Preserve the old OpenClaw output contract:
- Output A - Design Digest.
- Output B - Zettelkasten Candidates.
- Output C - Studio Skill Update Candidates.
- Telegram or short summary text.

Improve it with:
- source status per source lane.
- Arc bookmark section.
- Field Theory/X bookmark section.
- GBrain delta section.
- no claimed save unless the file exists.
- wikilinks for proposed Zettelkasten notes, not hashtags.

## Output A - Design Digest

Include 3-5 strongest findings.

For each finding:
- what it is.
- why it matters.
- source links.
- evidence type: direct page, Arc bookmark, X bookmark, GBrain imported note, or cross-source pattern.
- apply-this instruction for future product/design work.

## Output B - Zettelkasten Candidates

Suggest up to 3 notes. Do not write them by default.

For each note:
- title.
- proposed location.
- source links.
- outline.
- likely wikilinks.
- why this is durable knowledge instead of a weekly mention.

## Output C - Studio Skill Update Candidates

Suggest up to 3 skill updates. Do not apply them by default.

For each update:
- target file.
- proposed rule or snippet.
- evidence links.
- duplicate/idempotency check.
- eval required before promotion.

## Backfill Packet

For the outage catch-up, chunk by week and include:
- window start and end.
- source manifest for that chunk.
- top missed Arc candidates.
- top missed Field Theory/X candidates.
- GBrain delta summary.
- whether each chunk should produce a new permanent note, a skill candidate, both, or neither.
