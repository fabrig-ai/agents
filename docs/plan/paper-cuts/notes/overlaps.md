# The overlap family: overlaps-cache, overlaps-records, overlaps-git

What the three tasks on the overlap probe share
(`docs/design/fab-integration.md`, 4, "The overlap probe").

## The cache file, `FAB_HOME/overlaps.json`

- Keys stay as they are (`fab/overlaps.py`'s module docstring): a JSON list
  of repository, checkout, main's sha, then one trunk tip (a tree or a
  conflict) or both name-ordered tips (a pair). `trees` maps a key to a
  tree id, `pairs` a key to `{"files": [...], "more": n}`.
- overlaps-cache adds a third object, `conflicts`, a key (a tree's key) to
  `true`. A file without it (the first format, `{"trees": {}, "pairs":
  {}}`) still reads as valid, with no conflicts. overlaps-git writes the
  first format to plant a bad tree, so it holds before and after
  overlaps-cache.
- A missing, unreadable or malformed file is an empty cache: losing it
  loses only time.

## A well-formed `trunks.overlap`

- `drafts` and `tips` are lists of two strings, `files` a list of strings,
  `more` an `int` (not a `bool`) at least 0. overlaps-records binds the
  rule; every fold over `trunks.overlap` reads only such records.

## Pre-approved defaults

- The probe stays one entry point, `fab.overlaps.probe(loaded, events,
  all_loaded, *, sh, log_path)`, with the signature it has; the tick's call
  in `fab/dispatch.py` does not change.
- Printed lines and logged fields stay as they are.
