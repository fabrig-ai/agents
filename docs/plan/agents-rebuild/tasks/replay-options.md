+++
id = "replay-options"
part = "replay"
kind = "interface"
needs = []
files = ["fab/plan.py", "fab/designer.py", "fab/calls.py", "fab/tests/test_plan.py", "fab/tests/test_designer.py", "fab/tests/test_calls.py"]
effort = "high"
minutes = 40
+++
# A plan's replay options, and the cut that is given them

docs/design/fab.md 13.12 ("The options", "The trunk", "The cut's inputs").
Only the plan, the designer's command and the call's start change here; the
tick reads the options in a later task (`integration-merge`).

## What to change

- `fab/plan.py`:
  - `LANDINGS = ("queue", "integration")` and `OPTIONS = ("landing",
    "ready", "reviews", "direct")`.
  - `Plan` gains, after `questions`, `landing: str = "queue"`,
    `ready: bool = True`, `reviews: bool = True`, `direct: bool = False`,
    and a property `trunk`: `"main"`, or `f"{draft}/integration"` when
    landing is `"integration"`.
  - `load_plan` reads the four top-level keys with its type checks (landing
    a string in LANDINGS, the others bools); a wrong type or an unknown
    landing is a PlanError naming the file.
  - `parse_options(entries: Sequence[str]) -> dict[str, object]`: each
    entry is `KEY=VALUE`, VALUE a TOML value (`landing="integration"`,
    `reviews=false`); KEY must be in OPTIONS and VALUE of load_plan's type
    for it (landing in LANDINGS). Returns the keys in entry order; a later
    entry for a key wins. PlanError naming the entry otherwise. Pure.
  - `problems`: when `plan.direct`, one line per part whose mode is not
    direct: `part <id> is not direct in a direct plan`.
- `fab/designer.py`:
  - `uncut(draft, repo, sources=(), options=None)`: the stand-in carries
    the parsed options (`dataclasses.replace` with them).
  - `fab call cut` gains `--set KEY=VALUE` (repeatable), parsed with
    `parse_options` before anything starts. With `landing="integration"`,
    the checkout root must track `origin/<draft>/integration` (`git
    rev-parse --abbrev-ref --symbolic-full-name @{upstream}` in the root
    prints exactly that), else ValueError saying so.
  - `cut_brief(..., options=())` (the raw entries): when any, a section
    `Plan options` after `The draft`: the line `Write these keys at the top
    of plan.toml, before the first table, verbatim:` and a ```toml fence
    with one `KEY = VALUE` line per parsed option. When direct is true, the
    same section adds: every part is `mode = "direct"`, so the cut writes
    every task spec itself; notes that several tasks share go once in
    `<plan path>/notes/<name>.md`, cited from each spec by repository path,
    and the implementers read them in their checkout; a task's `needs` name
    the tasks whose merged code it builds on.
  - Every designer call starts on the plan's trunk: `calls.start(...,
    base=plan.trunk, fields=...)`; the cut's `fields` are `{"options":
    [the raw entries]}` when any (call.started then carries `options`, a
    list of strings).
- `fab/calls.py`:
  - `start(..., base: str = "main", fields: Mapping[str, object] | None =
    None)`: a new branch's worktree starts from `origin/<base>` (fetch
    first whenever base is not main, as for fabrig); call.started carries
    `trunk` when base is not main, and fields.
  - `fab call answer|review|amend` pass `base=plan.trunk`.

Signature changes inside these files are yours; keep every existing caller
working with its defaults (`fab/dispatch.py` is not in this task: its calls
keep the defaults until `integration-merge`).

## Acceptance

- test_plan: the four keys load with their defaults and when set; a bad
  landing or type is a PlanError; `trunk`; `parse_options` good and bad
  entries; `problems` names a non-direct part of a direct plan only.
- test_designer: `--set` reaches the brief's `Plan options` section and
  call.started's `options` (fake runner); the integration upstream check
  refuses a checkout tracking anything else; the direct notes text appears
  only with direct.
- test_calls: `base` sets the worktree's start and call.started's `trunk`;
  the default is unchanged.
- `bin/fab test` passes within its budget.
