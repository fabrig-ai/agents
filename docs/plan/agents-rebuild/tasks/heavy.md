+++
id = "heavy"
part = "heavy"
kind = "feature"
needs = []
files = ["fab/heavy.py", "fab/tests/test_heavy.py"]
effort = "high"
minutes = 25
+++
# heavy: lanes, the disk wait, the scope

Fill the bodies of `fab/heavy.py` as their docstrings say; `bin/heavy` is the
command. Design: `docs/design/fab.md`, section 7. It replaces fabrig's
`tools/heavy` (on the builder at `~/src/fabrig/main/tools/heavy/`, read its
`design.md` section 1 only if a detail is unclear); what that one does beyond
these docstrings is deliberately left out.

## Acceptance

- `fab/tests/test_heavy.py` covers:
  - admit_disk with fake free/reclaim/clock/sleep: enough at once (no sleep,
    no reclaim); short then freed by reclaim; short then freed while waiting;
    short past the cap (False); what say() is told.
  - lane: two build places taken, a third waits until one is released (a
    thread and a short poll is fine; keep it under 0.3 s); gate exclusive.
  - wrap with and without systemd.
  - settings from a hosts file passed in, and defaults for an unknown host.
  - main: `cargo fmt` runs directly; a command's exit code passes through; the
    disk cap gives EX_TEMPFAIL and the `heavy: Infra: disk:` line; a record
    lands in FAB_HOME/heavy.jsonl. Patch the free/reclaim functions and run a
    real tiny command (`true`, `sh -c 'exit 3'`) without systemd.
- `bin/fab test` passes; `test_heavy.py` takes under a second.

## Options, settled up front

- `fab.slots.reclaim` and `fab.slots.free_bytes` may still be skeletons when
  you start: import them by module (`from fab import slots`) and patch them in
  tests.
- systemd is "available" when `systemd-run` is on PATH and
  `XDG_RUNTIME_DIR` is set; tests force it off.
- `settings` may take the hosts file path as a keyword for tests.
- Wait messages go to stderr, one line each.
