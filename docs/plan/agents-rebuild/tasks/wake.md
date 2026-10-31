+++
id = "wake"
part = "events"
kind = "feature"
needs = []
files = ["fab/wake.py", "fab/hosts.py", "fab/heavy.py", "fab/cli.py", "fab/codex.py", "fab/calls.py", "fab/land.py", "fab/channel.py", "fab/queue.py", "fab/tests/test_wake.py", "fab/tests/wakes.py", "fab/tests/test_package.py", "fab/tests/test_codex.py", "fab/tests/test_calls.py", "fab/tests/test_land.py", "fab/tests/test_channel.py", "fab/tests/test_queue.py"]
effort = "high"
minutes = 45
+++
# Events wake the tick

Today the tick runs only on a 2-minute timer: a run that ends, a landing or
a call's end waits for it. Fill `fab/wake.py` so anything that ends work
the dispatcher waits for wakes the tick, and make each of those places
wake it. Design: `docs/design/fab.md`, 13.9, and section 2 for the want
file's place.

## What to fill

- **`fab/wake.py`:** `want_path`, `want`, `take`, `wake`, `wanted`,
  `again`, `lost`, `settle` and `main`, as their docstrings say. Leave
  `units` and `install` raising NotImplementedError: `wake-tick` fills
  them. `main`'s `--install` branch is written here and calls `install`.
- **`fab/hosts.py`:** `this_name` and `this`. `fab.heavy.settings` finds its
  entry's name through `this_name({name: entry.get("hostname", "")}, host)`
  over the raw entries it already reads; it keeps reading raw TOML, since
  its test files hold entries without `ssh` that `fab.hosts.parse` refuses.
- **`fab/cli.py`:** register `"wake": ("fab.wake", "wake the tick from any
  machine; install the tick's units")` after `tick`. You may add only that
  line.
- **The wakers**, each after its record is durable:
  - `fab.codex.start`: the systemd-run argv gains
    `--property=ExecStopPost=-<python3> -I -B <bin/fab> wake codex <id>`
    right after `--property=UMask=0077` (the same python3 and bin/fab as
    `_exec`; the `-` lets a failed wake leave the unit's result alone).
    Its docstring says so.
  - `fab.calls.start`: after logging call.ended, `wake.want(f"call
    {call_id}", path=wake.want_path(log_path))`. Nothing else wakes for a
    call; a call that raises before call.ended wakes nothing.
  - `fab.land.main`: after logging branch.landed or branch.rejected,
    `wake.want(f"land {task} {outcome.step}")` (task as logged; `-` when
    None).
  - `fab.channel.answer`: after logging call.answered,
    `wake.want(f"answer {subject}", path=wake.want_path(log_path))`.
  - `fab.queue.Queue`: `__init__` gains a keyword `wake: Callable[[str],
    object] | None = None`. `_reject` and `_retire` note each record they
    write as `rejected <branch>` or `landed <branch>`; `cycle`, in a
    `finally` around its attempts, calls `wake("queue " + <the notes
    joined by ", ">)` once when there are any and wake is set, then clears
    them. `main` passes `wake=fab.wake.wake`, so only the running queue
    wakes; a Queue built without it, as every test builds it, never does.
    A wake that raises is caught and printed to stderr; it never fails a
    cycle.
  Each changed docstring names its wake.

## Acceptance

- `fab/tests/test_wake.py`, in the vocabulary of `fab/tests/wakes.py`
  (`HOSTS`, `DISPATCHER`, `BUILDER`, `ended`, `imported`, `landed`,
  `started`, `here`, `WakeTestCase.assertWanted`, `assertNoWant`, `notes`):
  - the exemplar test runs: remove its skip;
  - `want`: lines appended in order, a multi-line and a blank reason, the
    parents created, the mode 0o600;
  - `take`: none, empty, a leftover TAKEN replaced, a want made after the
    rename survives as a new want;
  - `wake`: on the dispatcher no command runs; elsewhere one ssh with the
    reason as one argument; a failed ssh is False and raises nothing; no
    dispatcher in hosts is False with nothing run; an unknown machine goes
    over ssh; `here=None` follows FAB_HOST (`here`);
  - `wanted`, `again` and `lost` over hand-built records: the order and
    distinctness of kinds; `tick <n>:` counting up to AGAIN_LIMIT and None
    after; an outside reason among taken resetting to 1; a malformed own
    reason (`tick x: ...`) counting as outside; a hand-landed record not
    lost and an imported one lost;
  - `settle`: each trigger, the note texts and the printed lines, the
    limit's note, an unknown trigger a ValueError;
  - `main`: a delivered and an undelivered wake's exit codes and stderr,
    no reason exits 2.
- `fab/tests/test_package.py`: `this_name` (given name, FAB_HOST, hostname,
  none) and `this`. `fab/tests/test_heavy.py` passes unchanged.
- The wakers' tests: codex's systemd-run argv with ExecStopPost; a call's
  end leaves `call <id>` in the want beside its log_path; fab land's
  landing and refusal each leave their line; an answer leaves its line; the
  queue wakes once per cycle naming landed and rejected branches, not at
  all for a cycle that decided nothing or without `wake`, and a raising
  wake does not fail the cycle. Every test that reaches a waker runs under
  a temporary FAB_HOME (`WakeTestCase` or `tmp_home`), so no test touches
  hel8's want file. Existing tests whose recorded argv lists change are
  updated to the new argv, nothing else in them.
- `bin/fab test` passes; `test_wake.py` takes well under a second.

## Options, settled up front

- The want file is the only file fab appends to outside the log's lock;
  O_APPEND keeps concurrent lines whole. No flock.
- Reasons are free text for people reading the journal and the notes; no
  code parses them except `again`'s own `tick <n>:`.
- A wake is never retried. The backstop and its lost-event note are the
  remedy.
- `wake` reads `fab/hosts.toml` of the machine it runs on; a builder's
  install has it.
