+++
id = "precheck"
part = "precheck"
kind = "migration"
needs = ["gate"]
files = ["fab/precheck.py", "fab/tests/test_precheck.py"]
effort = "high"
minutes = 20
+++
# Precheck, ported

Fill the bodies of `fab/precheck.py` as their docstrings say, using
`fab.gate`. Design: `docs/design/fab.md`, section 6. fabrig's
`tools/queue/precheck` (on the builder at `~/src/fabrig/main/tools/queue/`)
is the old one; its receipts' bindings, cold tools copies, admission floors
and lifetime leases are left out on purpose.

## Acceptance

- `fab/tests/test_precheck.py`, with real git on `support.git_pair` as the
  slot (a branch checked out in it) and the checks replaced as in the queue's
  tests, covers: green (receipt fields, written file, slot back on its branch
  and clean); red (outcome red, failing step in steps, slot restored);
  conflict (outcome conflict, slot restored); the slot restored when a step
  raises; main's exit codes.
- `bin/fab test` passes; `test_precheck.py` takes under two seconds.
