# Request: the citation sweep

From the director, 2026-11-01 (agents/loop's brief, backlog item 4). fab's
design was split on 2026-11-01 into one document per subsystem
(`docs/design/fab.md` section 6). Code written before the split still
cites the old names, which section 6 says to read through its tables:

- `docs/design/fab-<name>.md` (the split's first names; the prefix was
  dropped the same day): 16 in `fab/dispatch.py`, `fab/wake.py` and
  `fab/tests/test_dispatch.py` (`grep -rnE "fab-[a-z-]+\.md" fab/`);
- `docs/design/fab.md, <old section>` (the old document's numbers,
  `13.15` and the like): about 30 across `fab/` and `fab/tests/`
  (`grep -rnE "fab\.md, ?[0-9]+|fab\.md [0-9]+\.[0-9]+" fab/`).

Build: rewrite each to the design and section it now means, by
`docs/design/fab.md` section 6's second table (old section → design,
section), checking that the cited text is there (the split may have moved
a subsection into a bullet of a section: cite the section). Citations of
`fab.md` sections 1-5 that still hold stay. Comments and docstrings only:
no behaviour, test or string a test pins changes; where a test asserts a
cited text, leave it and say so in the report. Also the role texts in
`fab/roles/` and `bin/`, if any cite the old names.

The user's rule: dogfood. Built by fab's loop (landed through `bin/fab
land`); the plan's landing is `queue` (the cut is started with `--set
'landing="queue"'`). One direct part, one or two tasks (by directory).
Run it after `docs/plan/dogfood-faults` has landed its tasks, since both
touch `fab/dispatch.py`.
