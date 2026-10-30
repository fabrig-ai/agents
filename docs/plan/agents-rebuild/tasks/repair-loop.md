+++
id = "repair-loop"
part = "dispatch"
kind = "feature"
needs = []
files = ["fab/run.py", "fab/queue.py", "fab/dispatch.py", "fab/tests/test_run.py", "fab/tests/test_queue.py", "fab/tests/test_dispatch.py"]
effort = "high"
minutes = 30
+++
# Repairs see the red; a collateral red is retried

On 10-30 the queue rejected `cutover-fabrig` at its default step for a fault
of the gate's own (heavy ran with umask 022). The dispatcher started a repair
run, which was not told what failed; it found nothing to fix and reported
Done on the same tip. The queue had marked that tip tried and would never
check it again, so it was retried only by editing the queue's state by hand.
Close both gaps. Design: `docs/design/fab.md`, sections 5 and 6.

## What to build

- **The repair brief carries the red.** `fab.run.brief` gains a keyword
  `rejection: dict | None = None` (a branch.rejected record). When given, a
  `## The landing refused this branch` section follows the run facts: the step,
  the queue's log path, and the log's lines from the failing step's start
  (the line beginning `[<step>]`) to its end, at most 120 lines, prefixed
  `The landing's checks failed; reproduce this first, in the lowest tier
  that shows it. If it does not reproduce, say so in your report's first
  line.` `fab.run.start` takes the same keyword and passes it on; the log
  text is read by `fab.run.rejection_text(record, gate_host, *, sh)`, one ssh
  `tail`/`sed` on the gate host (role gate in hosts.toml).
- **`fab queue untry BRANCH`** asks the running queue to forget a tried tip:
  it writes `FAB_HOME/queue-untry/<branch with / as %2F>`; `Queue.cycle`
  consumes every such file at its start (drops the name from `tried`, saves,
  removes the file, records `untried` with branch and tip).
- **The dispatcher uses both.** In `decide`, a start for a rejected task
  carries the rejection record (Action gains `rejection: dict | None`); `tick`
  passes it to `fab.run.start`. In `tick`'s ready action, when the tip being
  readied equals the tip of the task's last branch.rejected, also run
  `fab queue untry <branch>` on the gate host before pushing the ready ref,
  and log a note `retry <task>: same tip after repair`.

## Acceptance

- Tests: the brief's refusal section (cut at the step's start, the 120-line
  cap, absent without a rejection); `rejection_text` with the fake runner;
  untry files consumed once, `tried` saved without the name, `untried`
  recorded; decide carrying the rejection; tick's untry on a same-tip ready
  and not on a new tip.
- `bin/fab test` passes; each touched test module stays within its budget.

## Options, settled up front

- A missing or unreadable log gives the section with the path and
  `(log unreadable: <why>)` instead of its lines; never a refusal.
