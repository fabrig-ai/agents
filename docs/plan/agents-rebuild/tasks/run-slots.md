+++
id = "run-slots"
part = "run"
kind = "feature"
needs = []
files = ["fab/run.py", "fab/tests/test_run.py"]
effort = "high"
minutes = 25
+++
# fab run: slots for fabrig, freeing at collect, the launcher switch

Extend `fab/run.py` as the amended docstrings of `start` and `collect` say,
with the new constants SLOTTED and LAUNCHER. Design: `docs/design/fab.md`,
sections 5 and 7. Runs of this repository keep their worktrees; fabrig's runs
take a builder slot, build warm there, and give it back swept.

## Acceptance

- `fab/tests/test_run.py` gains, with the fake runner: a fabrig task's start
  (slot list answered with two slots, one claimed; the claim, the fetch and
  switch in the slot, codex started in the slot, run.started carrying slot);
  no idle slot refused; a repair in a slot; collect of a slot run (release
  called, freed in run.ended) and of a worktree run (worktree removed); a
  failing release noted as free_error while the run is still collected;
  LAUNCHER "fab" giving `fab codex start` with the same arguments.
- Existing tests keep passing unchanged, except where the worktree removal at
  collect adds a call they assert on.
- `bin/fab test` passes; `test_run.py` stays under a second.

## Options, settled up front

- `fab slot list` prints one JSON object per line (see `fab/slots.py` main);
  the first line whose claim is null, in idle rank order, wins.
- The slot path on the builder is `/home/<user>/src/fabrig/slots/<n>`, user
  as in `remote_home`.
