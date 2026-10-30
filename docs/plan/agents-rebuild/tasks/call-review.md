+++
id = "call-review"
part = "call-review"
kind = "feature"
needs = ["taste-brief"]
files = ["fab/call_review.py", "fab/run.py", "fab/tests/test_call_review.py", "fab/tests/test_run.py"]
effort = "high"
minutes = 45
+++
# Chains of calls and their review runs

Fill the bodies of `fab/call_review.py` (`chains`, `brief`, `amend_brief`,
`start`) as their docstrings say. Also fill `fab.run.fetch_clone` and
`fab.run.launch`, and make `fab.run.start` use both for every run. That means
the worktree and slot preparation stays in start, while the clone, the brief's
write, the launcher and run.started move into them. start's arguments, its
ssh commands and the run.started it logs do not change: the run tests that
pass today keep passing, their expected argvs unchanged except where two
commands merge into one (the `mkdir -p` of the run directory moving into the
brief's write). Design: `docs/design/fab.md`, 13.1 and 5. The role texts are
`fab/roles/call-reviewer.md` and `fab/roles/amender.md`, already written.

## Acceptance

- `fab/tests/test_call_review.py`:
  - `chains` as a pure function over hand-built events, one test per path:
    a call still in flight or ended failed is no chain; a role not in
    REVIEWED is no chain; review, reviewing, approved; a refusal gives
    amend; an amend call in flight is amending; its call.ended done gives
    review again (the earlier refusal now before latest's call.ended);
    refused again gives hold with `refused after its amendment`; an amend
    call ending question gives hold with its outcome; infra once gives
    review, INFRA_LIMIT times gives hold; call.parked gives parked; a
    question.answered naming the subject after it gives review, and then a
    refusal gives amend again; call.finished on the root or on an amend
    call gives finished; an amend call naming an unknown root is ignored;
    the chains' order is their roots' call.ended order.
  - `brief` with a temporary FAB_HOME holding a call's brief and two refusal
    reports: every section in order, `Amended by` only when latest differs,
    `(report missing)`, `(brief missing: ...)`, a diff over DIFF_LIMIT cut
    at a newline with the note, a short one whole.
  - `amend_brief`: its sections, the earlier amend calls listed, `(none)`
    without refusals, and the `# Call facts` section that `fab.calls.start`
    rebinds.
  - `start` with `support.FakeRunner`: the git commands in the checkout,
    the worktree add at the tip over ssh, `fab codex start --effort medium
    --read-only`, the run id `<root>-<n>`, run.started with task the root,
    kind review, call and tip; a failing launch removes the worktree and
    re-raises; a failing `git fetch` starts nothing on the builder.
- `fab/tests/test_run.py`: `fetch_clone` (an unknown repository refused
  before any command) and `launch` (`--read-only`, the fields carried into
  run.started, a malformed launcher answer refused) directly; start's
  existing tests pass.
- `bin/fab test` passes; each touched test module takes under a second.

## Options, settled up front

- `amend_brief` builds its text with `fab.calls._brief` and
  `fab.calls._facts` (private, used as `fab.calls` uses `fab.run._write`).
  Copying them is a defect.
- `chains` walks the events once in log order and keeps per-chain
  positions (the index of each event). Comparing ts strings would also
  work, but indexes keep equal timestamps in order.
- `brief` and `amend_brief` quote refusals through one private function
  (the `clones` gate would refuse a copy).
- Each new or changed function stays within 60 lines (the `size` gate):
  `fab.run.start` shrinks by this change.
