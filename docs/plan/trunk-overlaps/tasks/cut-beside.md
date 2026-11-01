+++
id = "cut-beside"
part = "beside"
kind = "interface"
needs = ["overlaps-pure"]
files = ["fab/designer.py", "fab/tests/test_designer.py", "fab/roles/cut.md", "fab/roles/cut-run.md"]
effort = "high"
minutes = 45
+++
# The cut sees the drafts beside it

Read first: `docs/plan/trunk-overlaps/notes/common.md`,
`docs/plan/trunk-overlaps/notes/decisions.md` (2, 6, 7 and 8).

The request: "the cut brief's `Drafts beside this one` section with its one
line in the cut's role text". Design: `docs/design/fab.md`, 13.17, "The cut
sees the drafts beside it", and 13.3 for the cut's brief.

## What to build

In `fab/designer.py`:
- `cut_brief` (near line 180) gains `beside: str | None = None`. A string
  inserts the section `Drafts beside this one` right after `Sources` (or
  `The user's drafts`), its text the string, `(none)` when empty; `None`
  inserts nothing. The docstring's section list says so. This adds a
  parameter to a public function: the task's kind is `interface`.
- A pure renderer taking the cut's plan, the other plans loaded (each with
  its tasks, in the plans file's order) and the log's records, returning
  the section's text, 13.17's rules exactly: same `plan.repo` only, the
  cut's own draft left out; an integration plan whose trunk has not landed
  (`fab.integration.trunk_landed`), every spec task with its `files`, those
  merged into the trunk (fold status `landed`, `fab.state.fold`) marked
  `merged`; an integration plan whose trunk has landed left out entirely; a
  queue plan, its tasks not landed with their `files`; a plan whose cut is
  in flight (decision 8) marked `cut in flight` with the tasks its
  directory already lists. Spec tasks only: a task whose `files` is
  `["**"]` (the repair and catch-up tasks folded from the log) is left
  out. At most 200 lines in all, then one line counting the rest.
- The loading, for `fab call cut` (`main` / `_compile`, near lines 347 and
  444): `fab.channel.plan_dirs(())`, loaded with `fab.dispatch._load_plans(
  ..., events, sh=run, fetch=False)` by a deferred import, its prints sent
  to stderr; events `fab.log.read()`. A cut whose options set `ready=false`
  gets `beside=None`; otherwise the rendered text (`""` when no draft is
  beside it).

In `fab/roles/cut.md` and `fab/roles/cut-run.md`, one line each, where the
role text speaks of its sources: prefer task boundaries and an order that
keep this draft's early work off files another draft is changing (the
brief's `Drafts beside this one`), and say in the plan which overlaps it
could not avoid. It refuses nothing and asks nothing.

## Acceptance

Tests in `fab/tests/test_designer.py`:
- the renderer: an integration plan of the same repository lists every
  spec task with its files, merged ones marked; its landed trunk leaves it
  out; a queue plan lists only tasks not landed; another repository's plan
  and the cut's own are left out; a cut in flight is marked; a `**` repair
  task is left out; 201 lines give 200 and a count;
- `cut_brief`: the section after `Sources` for a direct integration cut and
  after `The user's drafts` otherwise; `None` gives no section; `""` gives
  `(none)`;
- `fab call cut --brief-only` under `tmp_home()` with a plans file naming a
  second plan: the brief holds its section; with `--set ready=false` it
  does not; a plan that fails to load is skipped and the printed brief has
  no load line in it;
- the role texts hold the new line (an existing role test, if any, still
  passes).

## Pre-approved defaults

- The section's lines: `- <draft> (<landing>)` per plan, `- <draft> (cut in
  flight)` for a cut in flight, then `  - \`<task>\`: \`<file>\`, ...` per
  task, with ` (merged)` after the id of a merged one.
- The count line: `(<n> more lines)`.

## Report

The section's format as built, a sample of it from the test, and the two
role lines.
