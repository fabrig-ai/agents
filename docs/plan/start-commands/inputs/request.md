# Request: the start commands, and a park for a brief that can't compile

From the user via the director, 2026-11-01 (lab page, gaps G1 and G4 and fault F10, "fix the
small ones now"). The designs now say what to build, each marked "the user, 11-01":

1. **`fab trunk make PLAN_PATH [--base REV]`** (`docs/design/integration.md` 3, "The plan lives
   on its trunk").
   - Today an operator branches, pushes and adds the worktree by hand: every replay did, and so
     did the probe `phase-case` (11-01 16:50Z).
   - Build it as designed: the refusals, then the worktree first, then the push with an empty
     lease, the undo on a refused push, and `trunk.made` only after both.
   - Its own module (not `fab.plan`, the loader), registered in `fab/cli.py` COMMANDS.
2. **`fab plan inputs PLAN_DIR FILE... [--replace]`** (same section).
   - Today `inputs/` is written and committed by hand (main-sync's handover: "no command writes
     a plan's `inputs/`").
   - Build it as designed:
     - never commit in the plan's checkout; use a temporary worktree removed in every outcome;
     - the push per checkout kind; after a push or landing, the fast-forward under
       `FAB_HOME/tick.lock`;
     - the refusals.
   - Its own module, registered in `fab/cli.py` COMMANDS at a different place from item 1's
     entry, so the two tasks don't conflict at rebase.
   - Tests fake the landing (patch `fab.land.land`): `fab.land.main` clones when
     `FAB_HOME/repos/agents` is missing, and `land()` runs `bin/fab test`.
3. **A call whose brief can't compile parks its subject** (`docs/design/calls.md` 2, moved from
   5 Later).
   - Today `fab call` exits 1 before `call.started`, and the tick starts it again every tick.
   - Build as designed:
     - `_call` passes `--tick` to every role's parser, triage's included;
     - only a `--tick` call parks, and only on a ValueError or OSError while building the brief
       text;
     - `call.parked` fields as designed, with amend and settle naming their chain's root;
     - `_parked_subjects` adds open `parked` asks whose call is "";
     - the triage start checks it;
     - `fab/calls.py`, `fab/designer.py` and `fab/triage.py` `main` park alike;
     - `wake.want` after the park;
     - a later `call.started` of the subject closes the ask (`fab/channel.py` `_log_asks`);
     - a parked ask with no report shows no excerpt and no "Read:" in the forge body
       (`fab/forge.py`).
   - `fab.channel.asks` already shows a `call.parked` as a parked ask: test it, don't rebuild it.

Tests for each in `fab/tests/`: fakes and fixture logs, and real git in a temporary directory for
the two commands, as `test_overlaps_git.py` does.

The user's rule: dogfood. Built by fab's loop (landed through `bin/fab land`); the plan's landing
is `queue` (the cut is started with `--set 'landing="queue"'`). There are three tasks: 1 and 2 are
independent, and 3 touches `fab/dispatch.py` `_call`, `call_actions`, `_parked_subjects` and
`fab/calls.py` `main`. Run it after `docs/plan/dogfood-faults` has landed its tasks; it may run
beside `docs/plan/mechanisms-out` if that one has not reached `fab/calls.py` `main`'s amend path
yet. Otherwise order 3 after it.
