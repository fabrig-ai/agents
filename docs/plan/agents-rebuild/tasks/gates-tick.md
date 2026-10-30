+++
id = "gates-tick"
part = "gates"
kind = "feature"
needs = ["digest-render", "gates", "taste-brief", "review-call"]
files = ["fab/gates.py", "fab/dispatch.py", "fab/tests/test_gates.py", "fab/tests/test_dispatch.py"]
effort = "high"
minutes = 25
+++
# The tick gates every branch of this repository before it lands

Fill `fab.gates.screen` as its docstring says, and make the tick's land
action screen first, as `fab.dispatch.tick`'s amended docstring says. From
this change on, a branch of this repository with a finding is rejected with
step `gate:<name>` and repaired, never landed. Design: `docs/design/fab.md`,
section 12.

## Acceptance

- `fab/tests/test_gates.py`, with real git (`support.git_pair`; the clone
  copied to FAB_HOME/repos/agents, a branch pushed to the origin) and a
  temporary FAB_HOME:
  - a branch within its task's files, clean: no findings, the digest
    written to FAB_HOME/digests/<run>.md, nothing logged;
  - a branch touching a path outside its files: one branch.rejected with
    step `gate:files`, the digest's path as log and the findings text;
  - a branch whose `fab/x.py` does not parse: step `gate:parse`, no
    digest;
  - no run.started for the task: ValueError; a branch missing on the
    origin: `fab.sh.Failed`, nothing logged.
- `fab/tests/test_dispatch.py`: a done agents task with `fab.gates.screen`
  patched to return a finding is not landed (patched `fab.land.main` not
  called) and the action prints `rejected gate:files`; patched to return
  none, it lands as before; a screen that raises is a failed action (a
  note), the branch not landed.
- `bin/fab test` passes; the touched test modules stay under a second each.

## Options, settled up front

- The temporary trees live in `tempfile.TemporaryDirectory(dir=FAB_HOME)`.
- The flock is held with `fcntl.flock` on the open lock file, as `fab land`
  takes it.
