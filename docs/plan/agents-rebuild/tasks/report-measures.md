+++
id = "report-measures"
part = "accounting"
kind = "feature"
needs = ["part-measures"]
files = ["fab/accounting.py", "fab/code_report.py", "fab/tests/test_accounting.py", "fab/tests/test_code_report.py"]
effort = "high"
minutes = 50
+++
# The hand session's weight and each part's time breakdown in the code report

docs/design/fab.md 13.11 ("The hand session's weight" and "Time per part").

## What to build

- Hand sessions: read `FAB_HOME/hand-sessions` (`<session id> <draft>` per
  line; `#` comments and blank lines skipped; a missing file gives no hand
  line). For each session of the report's draft, read
  `~/.claude/projects/*/<id>.jsonl` and
  `~/.claude/projects/*/<id>/subagents/*.jsonl` (the projects root
  injectable for tests). Take each `type: assistant` line's
  `message.usage`, counted once per `requestId` (a message streams as
  several lines with the same usage). Weigh its input, cache write
  (`cache_creation_input_tokens`), cache read and output as calls are
  (13.5). Show a Hand line in the figures beside Claude and Codex: its
  tokens, its weight, and the Claude to Codex weight both without and with
  the hand weight. A transcript that cannot be read is a note, not a
  failure.
- Time per part: the Parts table (part-measures) gains, per finished part,
  in minutes: draft start to skeleton landed, spec landed to first run
  started, runs summed, run ended to checks, checks to ready, ready to
  landed. Take them from the log's events: `call.started` of the plan's
  first call, `call.finished` or the chain's `branch.landed`,
  `run.started`, `run.ended`, `branch.rejected` or the gating,
  `branch.ready`, `branch.landed`. A boundary with no event shows `-`. This
  repository's tasks land without a ready: for them, checks to ready is `-`
  and ready to landed is run ended to landed.

## Acceptance

- Tests with a hand-written transcript (two lines of one request, one of
  another, a subagent file): the hand weight counts each request once and
  shows apart; the ratio with and without it.
- Tests with hand-built events: a part's six intervals; a missing boundary
  as `-`.
- `bin/fab test` passes within the 30 s budget.
