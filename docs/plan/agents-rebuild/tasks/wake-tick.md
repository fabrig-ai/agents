+++
id = "wake-tick"
part = "events"
kind = "interface"
needs = ["wake", "buffer-order"]
files = ["fab/dispatch.py", "fab/wake.py", "fab/tests/test_dispatch.py", "fab/tests/test_wake.py", "fab/tests/wakes.py"]
effort = "high"
minutes = 35
+++
# The tick takes its wakes; its units replace the 2-minute timer

Once `wake` lands, every event appends to `FAB_HOME/tick.want`, but the
tick neither takes it nor closes its rounds, and the transient
`fab-tick.timer` still ticks every 2 minutes. Make the tick take the want,
know what started it, close each round through `fab.wake.settle`, and fill
the units that start it. Design: `docs/design/fab.md`, 13.9.

## What to change

- **`fab.dispatch.tick`** gains a keyword `trigger: str = "hand"`, one of
  `fab.wake.TRIGGERS` (ValueError otherwise, before the lock). Under its
  lock (an event tick waits for it with a blocking flock; a hand or
  backstop tick that finds it held returns [] as today, taking nothing):
  1. `taken = wake.take(wake.want_path(log_path))`; when not None, print
     `wake - <taken joined by "; ">` (`wake - -` when empty);
  2. note how many records the log holds;
  3. the round as today (loading, import, plans, strays, page), its early
     returns included;
  4. in a `finally`, `wake.settle(trigger, taken, <the records the log
     gained since step 2>, path=wake.want_path(log_path),
     log_path=log_path)`, printing each line it returns.
  Move today's body into a private function so `tick` stays well under 60
  lines; `tick`'s docstring says the four steps and the lock's two modes.
- **`fab.dispatch.main`**: `--trigger {hand,event,backstop}` (default hand)
  passed to `tick`. `--dry-run` ignores it and takes no want. Its docstring
  says so.
- **`fab/wake.py`:** `units` and `install`, as their docstrings say.

## Acceptance

- `fab/tests/test_dispatch.py`, with the vocabulary of
  `fab/tests/wakes.py` beside the existing tick fixtures: a want taken and
  printed before the import; a want made during the round (a fake
  `fab.run.collect` that wants) left for the next; a hand tick that
  collects an ended run wants `tick 1: run.ended` and logs no note; a
  backstop tick that does the same logs the lost-event note; a backstop
  tick that only starts a run logs nothing and wants nothing; an event
  tick waits for a held lock (hold it from a thread, release it, the tick
  then runs) while a backstop tick returns [] and leaves the want; an
  unknown trigger raises before the lock; `main --trigger backstop`
  reaches `tick`. Existing tests change only where they assert printed
  lines or the want beside their log.
- `fab/tests/test_wake.py`: `units` for two plan dirs (each file parsed
  with `WakeTestCase.unit`: the path, the timer's OnCalendar, both
  services' ExecStart naming their trigger and the plan dirs, Type and
  TimeoutStartSec), a refused path character, the files ending with a
  newline; `install` with a FakeRunner under the temporary HOME: the files
  written under XDG_CONFIG_HOME and without it, the three systemctl argvs
  in order, a failed stop of the old timer still returning the paths, a
  failed enable raising fab.sh.Failed; `main --install`'s printed lines.
- `bin/fab test` passes; `test_dispatch.py` stays within its budget and
  `fab.digest.functions` over `fab/dispatch.py` finds no new function over
  60 lines.

## Options, settled up front

- The round's records are the log's records after the count of step 2:
  other writers' records during the round count too.
- `fab wake --install` is run by hand on hel8 after this lands (with
  `~/src/fabrig/fab/install/docs/plan/agents-rebuild` as its plan dir,
  as the transient tick has); the commit says so. Nothing installs it
  automatically.
- The units stay files in `~/.config/systemd/user`; fleet keeping them
  is Later (`docs/design/fab.md`, 14).
