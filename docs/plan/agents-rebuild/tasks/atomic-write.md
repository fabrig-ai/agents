+++
id = "atomic-write"
part = "run"
kind = "feature"
needs = ["gates-tick"]
files = ["fab/atomic.py", "fab/run.py", "fab/queue.py", "fab/precheck.py", "fab/codex.py", "fab/gate.py", "fab/tiers.py", "fab/after_landing.py", "fab/calls.py", "fab/report.py", "fab/gates.py", "fab/tests/test_atomic.py", "fab/tests/test_after_landing.py", "fab/tests/test_report.py", "fab/tests/test_gates.py", "fab/tests/test_call_review.py", "fab/taste.md"]
effort = "medium"
minutes = 25
+++
# One write to a sibling, then rename

`AGENTS.md` asks every write to go to a sibling and be renamed over the
destination. The package does it in ten places. `fab.run._write` is private,
yet `fab.after_landing`, `fab.calls`, `fab.report` and two test modules
import it, and the taste file cites it as the good form. The others spell
it out again: `fab.queue._write` and the untry request in `fab.queue.main`,
the nested `write` in `fab.precheck.precheck`, two in `fab.codex` (`start`'s
meta.json and the nested `write` in `execute`, with a fixed `.tmp` sibling),
`fab.gate.run_steps`'s log, and `fab.tiers.run_pair`'s log. Make one public
function and call it everywhere. Design: `docs/design/fab.md`, sections 2
and 8; `AGENTS.md`.

## What changes

- New module `fab/atomic.py` with:
  - `write(path: Path, text: str) -> None`: create path's parent, write
    text (UTF-8) to a new sibling `.<name>.<random>` in the same directory,
    rename it over path, and remove the sibling if anything fails. The
    sibling is hidden, so a directory scan that skips dotfiles never takes
    it for a file (the queue's untry requests rely on that today).
  - `extend(path: Path, text: str) -> None`: write path's text (empty when
    it is missing) followed by text. The queue's detail log and
    `fab.tiers.run_pair`'s error both do this today with `read_text() + ...`.
- Every site above calls `atomic.write` or `atomic.extend` and keeps its
  current argument text. `fab.run._write` and `fab.queue._write` go. So do
  the nested writers in `precheck` and `codex.execute`. Each module imports
  `from fab import atomic`.
- Docstrings that name `fab.run._write` (`fab.after_landing.AfterLanding.check`,
  `fab.gates.screen`, `fab.report.main`) name `fab.atomic.write`. This
  task waits for `gates-tick`, whose `screen` writes the digest through
  `fab.run._write`. That call moves here too.
- Tests that import or patch `fab.run._write` or `after_landing._write`
  use `fab.atomic.write` (patched where the module looks it up:
  `fab.atomic.write`).
- Left as they are: `fab.slots.claim` (an exclusive create, not a
  replace), `fab.log.append` (an append under a lock), and the brief that
  `fab.run` writes on the builder through `bash -c 'cat > tmp && mv'`.

## Acceptance

- `fab/tests/test_atomic.py`, with a temporary directory: `write` creates
  missing parents and replaces an existing file whole; a failure while
  writing (patch the rename to raise) leaves the old file unchanged and no
  sibling behind; `extend` appends to an existing file and creates a
  missing one.
- `grep -rnw "NamedTemporaryFile\|_write" fab/*.py` finds only
  `fab/atomic.py` and the exclusive create in `fab/slots.py`.
- `bin/fab test` passes, with no other change in behaviour and every
  touched test module under a second.

## Options, settled up front

- The module is `fab/atomic.py`; the alternative, a function in
  `fab/log.py`, would mix the event log with every other file.
- `write` keeps no fsync; `fab.log.append` alone makes its line durable.

## Answers

- 2026-10-30, the user (by hand, run atomic-write-3): yes, migrate the two
  run._write calls in fab/tests/test_call_review.py to fab.atomic.write; the
  file is now in files. Anything else that still calls run._write is the
  same case: migrate it.
- 2026-10-31, the answerer (run atomic-write-4, four runs without landing):
  the work is done; its branch's history is what fails. Run 4 merged the old
  branch (dc80204, 59de177) into a fresh one, so every rebase replays commits
  main has since moved past and conflicts in six files. The next run starts
  from origin/main, takes the final tree of `agents-rebuild/atomic-write`
  (f755560) as the reference, re-applies it as one commit, resolving each
  file once against main, and pushes that over the task branch; it merges
  no old branch. Two loose ends land with it: the acceptance grep is now
  word-bounded (`-w`) and names `fab/slots.py` too, since `cache_write` and
  the exempt `slots.claim` are not the case it checks for; and
  `fab/taste.md` is in files, so its "Good" example for writes to a sibling
  cites `atomic.write(path, json.dumps(state))  # fab.atomic.write` rather
  than `fab.run._write` (its "Bad" private-import example stays).
