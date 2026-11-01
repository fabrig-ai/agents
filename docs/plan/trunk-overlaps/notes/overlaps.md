# The overlap family: overlaps-pure, overlaps-tick, overlaps-page

What the three tasks that read or write `trunks.overlap` share
(`docs/design/fab.md`, 13.17, "The overlap probe").

## A pair and its record

- A pair is the two drafts' names as a tuple in name order, `(a, b)` with
  `a < b`; `drafts` and `tips` are lists in that order.
- A pair's **last** `trunks.overlap` is the latest record in the log whose
  `drafts` equal the pair. A pair with none counts as `files = []`,
  `more = 0`. `count` is `len(files) + more`.
- A pair is **open** when its last `trunks.overlap` has non-empty `files`.
  One copy of that rule, bound here:
  `fab.overlaps.open_pairs(events: Sequence[dict]) -> dict[tuple[str, str], dict]`,
  each open pair to its last `trunks.overlap` record, in name order. Records
  whose `drafts` is not a list of two strings are skipped. Pure. The probe's
  "pairs gone" and the page read it.
- `FILES = 40` in `fab.overlaps`: at most this many `files`; `more` counts
  the rest.

## Failure notes

- A failure is logged as a `note` whose `text` starts with
  `trunks.overlap <a> <b>: ` for a pair or `trunks.overlap <draft>: ` for a
  trunk's catch-up merge, then the failure in one line (the command's exit
  code and its first stderr line). It is logged only when that text differs
  from the last note with the same prefix. The prefix and the "is it news"
  rule are pure functions of `fab.overlaps` (overlaps-pure's to name).

## Pre-approved defaults

- Draft names come from `Plan.draft`; the trunk is `Plan.trunk`
  (`<draft>/integration`), on origin as `origin/<draft>/integration`.
- A trunk has landed when `fab.integration.trunk_landed(plan, events)`
  (overlaps-pure) says so; nothing else in this family re-derives it.
