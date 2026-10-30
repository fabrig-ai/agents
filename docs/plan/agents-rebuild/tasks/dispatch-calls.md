+++
id = "dispatch-calls"
part = "calls"
kind = "feature"
needs = []
files = ["fab/dispatch.py", "fab/calls.py", "fab/tests/test_dispatch.py", "fab/tests/test_calls.py"]
effort = "high"
minutes = 30
+++
# The dispatcher makes its own Claude calls

Today a skeleton or answer call is started by hand, and the first one failed
with no trace of why (claude exited in a second; nothing kept its stderr).
Make the tick start calls in their own user units and finish them, as the
amended docstrings of `fab.dispatch.call_actions`, `fab.dispatch.tick` and
`fab.calls.start` say. Design: `docs/design/fab.md`, section 11.

## Acceptance

- `call_actions` as a pure function: no call when one of the role is in
  flight; an answer call at ANSWER_AT questions and at ANSWER_AFTER minutes,
  not before; a skeleton call for the first design part only; finish for a
  done call once (not after its call.finished), not for a failed one;
  question.answered ids parsed from the report's `Answered:` line.
- `tick` with the fake runner: the systemd-run argv for a call, finish
  landing the branch (patched `fab.land.main`), question.answered and
  call.finished logged; a failed landing logged as a note and call.finished
  with outcome failed.
- `calls.start` keeps stderr.log and runs claude with CLAUDECODE* and
  CLAUDE_CODE_* removed from its environment (assert on the env the fake
  runner received).
- `bin/fab test` passes; the touched test modules stay under a second each.

## Options, settled up front

- The report path of a call is FAB_HOME/calls/<id>/report.md (as
  `calls.start` writes it); finish reads it there.
- A call unit's number n counts that role's call.started events plus one.
