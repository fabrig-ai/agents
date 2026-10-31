+++
id = "run-texts"
part = "replay"
kind = "feature"
needs = []
files = ["fab/run.py", "fab/designer.py", "fab/tests/test_run.py", "fab/tests/test_designer.py"]
effort = "high"
minutes = 25
+++
# The run's own texts reach the cut and the implementers

docs/design/fab.md 13.12 ("The run's own texts"). The texts are written:
`fab/roles/cut-run.md` and `fab/roles/fabrig-run.md`.

## What to change

- `fab/designer.py` (`cut_brief`): for a plan whose options make it direct
  and integration (the defaults), the `Role` section is
  `fab/roles/cut-run.md` alone, in place of `cut.md`, `cut-fabrig.md` and
  `cut-direct.md`; other plans keep today's texts. The `Plan options`
  section stays; its direct-mode sentences go when `cut-run.md` is the role
  (that text says it).
- `fab/run.py`:
  - `role_text(repo, trunk)`: for fabrig with a non-main trunk, the text is
    `fab/roles/fabrig-run.md` alone (no `implementer.md`, no taste file, no
    `fabrig.md` or `fabrig-integration.md`); everything else unchanged.
  - The brief names the spec by its path relative to the repository: the
    tick passes the plan's checkout root (a keyword of `start`, default
    None keeps today's path), and the `- Task:` fact shows `task.path`
    relative to it when it lies inside.
- Delete `fab/roles/cut-direct.md` and `fab/roles/fabrig-integration.md` only
  if nothing reads them after this change (say so in the report).

`fab/dispatch.py` is another task's: pass the checkout root from it is
that task's (`cut-early`), so keep the keyword's default working.

## Acceptance

- test_designer: a default (direct, integration) cut's brief has
  cut-run.md's text and none of cut.md's, cut-fabrig.md's or
  cut-direct.md's; a queue plan's cut is unchanged.
- test_run: a fabrig run on a non-main trunk gets fabrig-run.md alone; the
  spec fact is repository-relative when a root is given.
- `bin/fab test` passes within its budget.
