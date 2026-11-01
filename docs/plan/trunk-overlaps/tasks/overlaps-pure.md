+++
id = "overlaps-pure"
part = "probe"
kind = "feature"
needs = []
files = ["fab/overlaps.py", "fab/tests/test_overlaps.py", "fab/integration.py", "fab/tests/test_integration.py"]
effort = "high"
minutes = 45
+++
# The overlap probe's pure part

Read first: `docs/plan/trunk-overlaps/notes/common.md`,
`docs/plan/trunk-overlaps/notes/overlaps.md`,
`docs/plan/trunk-overlaps/notes/decisions.md`.

The request: "the overlap probe (`fab/overlaps.py` ...)". Design:
`docs/design/fab.md`, 13.17, "The overlap probe", its last bullet: "The
pure part (`fab/overlaps.py`): the plans to probe from the loaded plans and
the log, the pairs, the parse of merge-tree's output, whether a result is
news, and the pairs gone."

## What to build

- `fab/integration.py`: `trunk_landed(plan: Plan, events: Sequence[dict]) -> bool`,
  true when the log holds a `branch.landed` for task `<draft>/integration`
  carrying `queue_ts`. `queue_step` (near line 272) uses it instead of its
  own check; its behaviour is unchanged. Binding (cut-beside reads it).
- `fab/overlaps.py`, a new module, pure, importing `fab.plan` and
  `fab.integration` only:
  - `FILES = 40` and `open_pairs(events)`, as `notes/overlaps.md` binds.
  - The plans to probe: from the loaded plans and the log, those with
    `landing == "integration"`, `ready`, not `retired`, and not
    `trunk_landed`, in draft-name order. (Whether the trunk is on origin is
    the shell's, next task.)
  - The pairs: from the probed plans, every two of the same `plan.repo`,
    as `(a, b)` in name order.
  - The parse of a trunk's catch-up merge (`git merge-tree --write-tree
    --no-messages origin/main origin/<trunk>`): exit 0 and a hex tree id on
    the first line is the tree; exit 1 with a tree id first is a catch-up
    conflict; anything else a failure.
  - The parse of a pair's merge (`--name-only --no-messages -z`): exit 0 is
    no overlap; exit 1 is an overlap only when stdout's first NUL-separated
    field is a hex object id, the paths following it (empty fields
    dropped); anything else a failure. Returns the paths (or none) and
    `more` past `FILES`.
  - Whether a result is news: a pair's (`files`, `more`) differ from its
    last `trunks.overlap` (none counts as empty).
  - The pairs gone: given this tick's pairs and the log, the open pairs
    (`open_pairs`) not among them, each with the closing record's fields
    (`files` empty, `more` 0, `reason` `gone`, the tips of its last record).
  - The failure note's prefix and whether a failure note is news
    (`notes/overlaps.md`, "Failure notes").
  - The `trunks.overlap` fields for a pair as a dict, for the shell to log.

Names other than `trunk_landed`, `open_pairs` and `FILES` are yours; give
each a docstring citing 13.17, as the next task builds on them.

## Acceptance

Tests in `fab/tests/test_overlaps.py` and `fab/tests/test_integration.py`:
- `trunk_landed`: true only with `queue_ts`; a trunk merge (`into`) or a
  landed task of the plan is not it; `queue_step`'s existing tests pass
  unchanged;
- probed plans: a queue plan, a replay (`ready` false), a retired plan and
  a landed trunk are left out; the order is by draft name;
- pairs: only within one repository; three drafts make three pairs, in
  name order;
- both parses, each outcome: exit 0, an overlap with paths (one with a
  space and a newline in its name, read from `-z`), exit 1 with no tree id,
  exit 128, garbage; 45 paths give 40 `files` and `more` 5;
- news: a clean first probe is not news; a changed set is; the same set is
  not; an empty set after a non-empty one is;
- pairs gone: an open pair not among this tick's pairs is closed with
  `reason` `gone`; a pair already closed or still present is not;
- failure notes: the same text twice is news once; a different text is
  news again.

## Report

The functions added with their signatures, for overlaps-tick to call.
