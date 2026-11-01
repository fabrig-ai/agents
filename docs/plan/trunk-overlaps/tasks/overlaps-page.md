+++
id = "overlaps-page"
part = "page"
kind = "feature"
needs = ["overlaps-pure"]
files = ["fab/serve.py", "fab/tests/test_serve.py", "docs/design/fab.md"]
effort = "medium"
minutes = 35
+++
# The page's overlaps

Read first: `docs/plan/trunk-overlaps/notes/common.md`,
`docs/plan/trunk-overlaps/notes/overlaps.md`,
`docs/plan/trunk-overlaps/notes/decisions.md` (3 and 9).

The request: "its line on the status page (13.14)". Design:
`docs/design/fab.md`, 13.17, "What it is for, for now: report only" and
13.14.

## What to build

- `fab/serve.py`, `snapshot` (near line 172): the key `overlaps`, a list of
  `{"drafts": [a, b], "count": n}` for each pair in
  `fab.overlaps.open_pairs` over the dated events, `count` being
  `len(files) + more` of its last record; each draft by its public label as
  the Drafts panel labels them (a name in `known_drafts` matching `DRAFT`,
  otherwise `other`); sorted by the labels. Never a path, never a tip.
- The page (near line 424): a panel `<h2>Overlaps</h2>` right after Drafts,
  a table Drafts | Files (the two labels joined by ` · `, the count), or
  `<p class="empty">No drafts overlap.</p>`.
- `docs/design/fab.md`, 13.14: the page order line ("tiles, Waiting on the
  user, Subscriptions, Drafts, Today, In flight") gains Overlaps after
  Drafts. Nothing else in the design.

## Acceptance

Tests in `fab/tests/test_serve.py`:
- an open pair shows in `snapshot["overlaps"]` with its count (40 files and
  `more` 3 give 43), and on the page after Drafts; a pair closed since
  (empty `files`, `probe` or `gone`) shows nowhere;
- a draft not known from run starts, or not matching `DRAFT`, shows as
  `other`;
- no path and no tip from a `trunks.overlap` appears in the snapshot's JSON
  or the page's HTML;
- no overlaps: the key is an empty list and the panel says so; the
  existing tests pass with the new key.

## Report

The key's shape as built, and the 13.14 line changed.

## Repair (2026-11-01, step gate:size, foreman trunk-overlaps/overlaps-page/foreman-1)

Extract overlap folding and panel rendering into private helpers so existing oversized functions do not grow.
`gate:size` reports `fab/serve.py:172` snapshot at 114 lines and `fab/serve.py:308` render at 154 lines (cap 60).
The size ratchet permits existing long functions only when they do not grow (`docs/design/fab.md`, “The gates”, `size`).
In `fab/serve.py`, extract the `public_overlaps` loop, label sanitization and sorting into a private helper accepting dated events and known drafts; call it directly for the returned `overlaps` key.
Extract the Overlaps panel into a private helper and append its result alongside the existing Drafts append, keeping `render` at or below its base length.
Move shared HTML helpers to module scope only as needed; preserve escaping and public signatures. Keep every new helper within 60 lines.
Preserve the overlap shape, filtering, counts, empty state and panel order required by `docs/design/fab.md`, 13.14 and 13.17.
Keep the existing design order-line change and acceptance tests in `fab/tests/test_serve.py`.
Run the serve tests with Python `-B`, then `bin/fab test` and the landing size gate.
