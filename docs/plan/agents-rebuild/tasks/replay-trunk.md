+++
id = "replay-trunk"
part = "replay"
kind = "interface"
needs = []
files = ["fab/run.py", "fab/rust_gates.py", "fab/precheck.py", "fab/foreman.py", "fab/repairs.py", "fab/spec_edit.py", "fab/roles/fabrig.md", "fab/tests/test_run.py", "fab/tests/test_rust_gates.py", "fab/tests/test_precheck.py", "fab/tests/test_foreman.py", "fab/tests/test_repairs.py", "fab/tests/test_spec_edit.py"]
effort = "high"
minutes = 40
+++
# Runs, gates, precheck and spec edits read a plan's trunk, not main

docs/design/fab.md 13.12 ("The trunk", "The end check"). Each function
below that reads main for a plan takes the trunk as a keyword whose default
keeps today's behaviour; the tick passes it in a later task
(`integration-merge`). The trunk is a branch name (`main`,
`component-kit/integration`); the remote ref is `origin/<trunk>`.

## What to change

- `fab/run.py`:
  - `start(..., trunk: str = "main")`: the base is `origin/<trunk>` where
    it is `origin/main` today (a task started from a checked skeleton tip
    keeps that tip); so is `_rebase_brief`'s `--onto` and base.
  - `brief(..., trunk: str = "main")`: when trunk is not main, the facts
    gain `- Trunk: \`origin/<trunk>\`` after `- Base:`; unchanged otherwise.
- `fab/rust_gates.py`: `screen(..., trunk: str = "main")`: the base is the
  tip's merge base with `refs/remotes/origin/<trunk>`.
- `fab/precheck.py`:
  - `precheck(slot, tip, *, onto: str = "origin/main", full: bool = False,
    ...)`: detach at `onto` (resolved to its sha, which the receipt's
    `main` holds) and merge tip into it, as today with main. With full,
    the selection is `"full"` whatever the paths, and the ratchet steps
    run for every tree in `fab.gate.TREES` that has
    `scripts/old_forms.py`.
  - The command: `fab precheck SLOT TIP [--onto REF] [--full]`.
- `fab/foreman.py` and `fab/repairs.py`: `start(..., trunk: str = "main")`
  launches detached at `origin/<trunk>` (foreman) and logs it as the base;
  their `commit(..., trunk="main")` pass it to `fab.spec_edit`.
- `fab/spec_edit.py`: `commit(..., trunk: str = "main")`: the worktree and
  the spec read start from `origin/<trunk>`.
- `fab/roles/fabrig.md`: the precheck line becomes `fab precheck <your
  slot> <tip> --onto <trunk>`, the trunk your task's facts name
  (`origin/main` when they name none); a conflict with the trunk is a
  `Question:`.

Signature changes inside these files are yours, as long as every caller
outside them works unchanged with the defaults.

## Acceptance

- Tests in the listed test files: each function with a non-main trunk uses
  `origin/<trunk>` where it used `origin/main` (fake runner argv), and
  with the default produces exactly what it did before; `brief`'s Trunk
  fact; `precheck --full` selects full and every tree's ratchet; `--onto`
  sets the receipt's `main`.
- `bin/fab test` passes within its budget.
