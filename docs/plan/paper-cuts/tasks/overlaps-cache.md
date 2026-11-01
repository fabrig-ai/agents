+++
id = "overlaps-cache"
part = "probe-cuts"
kind = "feature"
needs = []
files = ["fab/overlaps.py", "fab/tests/test_overlaps.py"]
effort = "high"
minutes = 50
+++
# The probe's cache: conflicts cached, pruned, written on change

Read first: `docs/plan/paper-cuts/notes/common.md`,
`docs/plan/paper-cuts/notes/overlaps.md`.

The request (2): "the overlap probe's cache (results only, catch-up
conflicts included, pruned to this tick's keys, written only when
changed)". Design: `docs/design/fab-integration.md`, 4, "The cache"
paragraph ("results are cached in `FAB_HOME/overlaps.json` ... Losing the
file loses only time").

## What to build

In `fab/overlaps.py`:
- **Conflicts cached:** `_catch_up_trees` (near line 190) stores a trunk
  whose catch-up conflicts as `conflicts[<its tree key>] = true`, and a
  trunk whose key is there is not merged again (its pairs are skipped, as
  now for a conflict). Failures are never cached.
- **Read:** `_read_cache` (near line 256) accepts `conflicts` (an object
  of key to `true`) and a file without it (the first format) as valid; any
  other shape is an empty cache, as now.
- **Pruned:** each probe keeps only the entries it looked up or stored this
  tick (trees, pairs, conflicts); a cached tree dropped because a pair
  that used it failed is not kept although it was looked up. So the file
  holds only this tick's keys.
- **Written only when changed:** `probe` (near line 137) writes the file
  with `fab.atomic.write` only when the pruned cache differs from what it
  read (a missing file reads as empty).
- The module docstring states the three objects and the pruning.

## Acceptance

Tests in `fab/tests/test_overlaps.py`, through `probe` with a `FakeRunner`
(the `OverlapProbeTest` class, near line 162):
- a conflicting catch-up runs one merge-tree in the first probe and none in
  the second with nothing moved; a new tip or a new main merges again;
- a second probe with nothing moved runs no merge-tree and does not write
  `overlaps.json` (its mtime, or a patched `atomic.write`, unchanged);
- after a tip moves, the file holds no key with the old tip, and after a
  pair leaves, none of its keys;
- a pair failure drops its trees and they are not in the written file;
- a file in the first format (no `conflicts`) is read: its tree is used
  without a merge; a malformed `conflicts` makes the cache empty;
- the existing tests pass, their assertions unchanged.

## Pre-approved defaults

- A test that pinned "the cache is written every probe" changes to the new
  rule; say which in the report.
- Keep `probe` within the 60-line cap: the pruning and the change check go
  in private helpers.

## Report

The file's format as built, and the git commands a second probe with
nothing moved runs (the `rev-parse`s only).
