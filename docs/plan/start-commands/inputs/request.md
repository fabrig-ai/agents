# Request: the start commands, and a park for a brief that can't compile

From the user via the director, 2026-11-01 (lab page, gaps G1 and G4 and fault F10, "fix the
small ones now"). The designs now say what to build, each marked "the user, 11-01":

1. **`fab trunk make PLAN_PATH [--base REV]`** (`docs/design/integration.md` 2, "The plan lives
   on its trunk"). Today an operator branches, pushes and adds the worktree by hand: every replay
   did, and so did the probe `phase-case` (11-01 16:50Z). Build it as designed:
   - fetch `FAB_HOME/repos/fabrig`;
   - branch `<draft>/integration` at REV;
   - push it;
   - add the worktree `FAB_HOME/integration/<draft>` tracking it;
   - log `trunk.made`;
   - print the plan directory;
   - refuse without changing anything when the branch exists on origin or the worktree path
     exists.

   Register it in fab's CLI (`fab/cli.py`) beside the other commands.
2. **`fab plan inputs PLAN_DIR FILE... [--replace]`** (same section). Today `inputs/` is written
   and committed by hand (main-sync's handover: "no command writes a plan's `inputs/`"). Build
   it as designed: copy, commit, and deliver per checkout:
   - an integration trunk's worktree: push fast-forward to the trunk;
   - this repository: branch `inputs/<draft>` through `fab land` (`fab.land`);
   - fabrig on main: `ready/inputs/<draft>` to the queue.

   It prints the `--source` paths.
3. **A call whose brief can't compile parks its subject** (`docs/design/calls.md` 2, moved from
   5 Later). Today `fab call` exits 1 before `call.started` and the tick starts it again every
   tick. Build:
   - `fab call` (`fab/calls.py` `main`, `fab/designer.py` `main`), when started by the tick and
     failing before `call.started`, logs `call.parked` (subject, role, `call` "", reason
     `brief failed: <first line>`);
   - `fab.dispatch._parked_subjects` holds such subjects until a later `call.answered` names
     them;
   - `fab.channel.asks` shows them as `parked` asks;
   - check that a call run by hand (not the tick) also parks, or say why not in the status file.

Tests for each in `fab/tests/`: fakes and fixture logs, and real git in a temporary directory
for the two commands, as `test_overlaps_git.py` does.

The user's rule: dogfood. Built by fab's loop (landed through `bin/fab land`); the plan's landing
is `queue` (the cut is started with `--set 'landing="queue"'`). Three independent tasks. Run it
after `docs/plan/dogfood-faults` has landed its tasks; it may run beside
`docs/plan/mechanisms-out` (different functions, both in `fab/calls.py` and `fab/designer.py`).
