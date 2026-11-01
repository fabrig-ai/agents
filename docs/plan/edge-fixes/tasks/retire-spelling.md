+++
id = "retire-spelling"
part = "edge-cases"
kind = "feature"
needs = []
files = ["fab/dispatch.py", "fab/tests/test_dispatch.py", "docs/design/calls.status.md"]
effort = "medium"
minutes = 30
+++
# Retiring a plan that spells the key another way

Read first: `docs/plan/edge-fixes/notes/common.md`,
`docs/plan/edge-fixes/notes/decisions.md` (6-9), then
`docs/design/calls.md` 3 (~425-436).

The request's item 2. `_retire_plan` recognises only the bare `retired = false`.
Valid TOML such as `"retired" = false` passes `load_plan`, keeps its assignment
and gains `retired = true`. The output no longer loads (`Cannot overwrite a
value`), and `_pre_deliver` publishes it.

## What to build

`fab/dispatch.py`, `_retire_plan` (~859). Keep its `missing plan.toml` refusal
and its early return when `tomllib` reads `retired` True. Then:

- Split the text with `statements, tables = designer._plan_header(text)`.
- When the parsed text has the key, replace each statement whose
  `tomllib.loads(statement)` holds `retired` with `retired = true\n`.
- When it does not, insert as today: `retired = true\n` after the header, with
  a newline first if the header does not end in one.
- Parse the final text: raise `ValueError` when it does not parse or its
  `retired` is not True (`tomllib.TOMLDecodeError` is a `ValueError`). The
  edit runs inside `commit_path`, so nothing is committed.
- Say this in the docstring.

`docs/design/calls.status.md`, "`retired = true` is code's" (~71): replace
"`_retire_plan` replaces a top-level `retired = false` or inserts..." with what
it does as built: it replaces the top-level assignment however the key is
spelled, inserts only when the key is absent, and refuses a final text that
does not set it. Cite plan `docs/plan/edge-fixes`. Remove anything else there
this makes too broad.

## Acceptance

In `RetireFinishTest`, `fab/tests/test_dispatch.py`:

- A new test on a complete plan (`write_plan`, then prepend the key's
  assignment to `plan.toml`) for each of `retired`, `"retired"`, `'retired'`
  and `"r\u0065tired"` (a quoted key whose `e` is the TOML escape: backslash, `u`,
  `0065`; 14 bytes in the file, so use a Python raw string): `plan.load_plan`
  before reads `retired` False; after `_retire_plan` it reads True, and the parts
  and slices are unchanged.
- `test_retire_edit_replaces_or_inserts_top_level_flag` (~5342) gains: a table's
  `retired = false` stays, a multi-line header value holding the text
  `retired = false` stays, an absent key is inserted once, and `[retired]`
  and split dotted keys (`retired.a = 1`, `retired.b = 2`) raise `ValueError`.
- Through `self.take()`, with `self.branch_text` spelling `"retired" = false`:
  the pushed text loads with `tomllib` and `retired` is True.
- Through `self.take()`, with a `branch_text` that fails the final parse: no
  commit, no landing, the finish left open and a `finish root failed` note, as
  `test_retire_commit_or_push_failure_leaves_finish_open_and_retries` checks.
- `bin/fab test` green.

## Pre-approved defaults

- The request's "replace that statement" drops a trailing comment. The two pins
  of `retired = true # pending` (~5345, ~5363) become `retired = true`. Name
  them in your report.
- `re` stays imported: ~1404 uses it.
- Calling `designer._plan_header` from `fab/dispatch.py` is what the request
  asks. Leave `fab/designer.py` as it is, unless a gate refuses the private
  name; then that is a `Question:`.

## Report

The function changed; the tests added and the two updated; that the new tests
fail on the old `_retire_plan`. Machine action: none; the tick follows main.
