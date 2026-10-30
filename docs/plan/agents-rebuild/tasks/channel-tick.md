+++
id = "channel-tick"
part = "user-channel"
kind = "interface"
needs = ["channel", "designer-tick", "foreman-tick"]
files = ["fab/channel.py", "fab/cli.py", "fab/dispatch.py", "fab/call_review.py", "fab/calls.py", "fab/tests/test_channel.py", "fab/tests/test_package.py", "fab/tests/test_dispatch.py", "fab/tests/test_call_review.py", "fab/tests/test_calls.py"]
effort = "high"
minutes = 45
+++
# The page is written, answers come back, and they reach the next brief

After `channel`, the fold and the page's text exist but nothing writes the
page or takes an answer. This task makes the channel live:

- `fab page` writes the page and takes the user's answers;
- the tick rewrites the page at its end;
- `call.answered` becomes the only answer that unparks a call's subject
  or resets its chain;
- every later call of the subject, and every review run of its chain,
  reads the user's answers in its brief.

Design: `docs/design/fab.md`, 13.6, with 3, 12 and 13.1.

`designer-tick` and `foreman-tick` change `fab/dispatch.py`,
`fab/call_review.py` and `fab/calls.py` and land first. The size gate holds
every new or changed function to 60 lines; put new steps in private
functions, as `tick-split` does.

## What to build

- **`fab/channel.py`:** the bodies of `compose`, `write`, `answer` and
  `main`, as their docstrings say. `fab.atomic`, `fab.log`, `fab.plan` and
  `fab.report` are imported at the top; `fab.calls`, `fab.call_review` and
  `fab.dispatch` import this module, so it never imports them.
- **`fab/cli.py`:** `page` in COMMANDS, `("fab.channel", "the user's page:
  their questions and the latest reports; their answers")`.
- **`fab.dispatch`:**
  - `_parked_subjects` gives the subjects of `fab.channel.asks((), events)`
    of kind `call`: one rule for the page and the tick. Its `started`
    argument goes if nothing else needs it.
  - `call_actions` computes the parked subjects before the answer
    branch, which also requires `plan.draft` not parked: an answer call
    that ended `Question:` starts no answer call again until
    `call.answered` names the draft, or a later call of the draft ends
    done. Skeleton and review keep their parked checks.
  - `call_actions`' docstring says a question parks its subject, an
    answer call's being its draft, until `call.answered` names it, or a
    later call of the subject ends done.
  - `tick`, after the call actions, rewrites the page in a private
    function: `fab.channel.write(fab.channel.compose(
    fab.channel.plan_dirs([plan_dir]), log.read(log_path), log.now()))`,
    printing `page - <path>`. An OSError or a ValueError prints `page -
    failed: <error on one line>`, logs nothing, and the tick still returns
    its actions. A tick that returns early (the lock held, a retired plan)
    writes no page. Say so in `tick`'s docstring.
- **`fab.call_review`:**
  - `chains`: the reset is a `fab.channel.ANSWERED` record whose subject is
    the chain's subject, later than its last call.parked. A
    `question.answered` resets nothing. Its docstring says so.
  - `brief` gains the keyword `answers: str = ""`. When it is not empty, a
    section `fab.channel.SECTION`, then answers, comes after `# Earlier
    findings` (or after `# Your review` when there are none) and before
    `# The diff`. Add it to the docstring's list.
  - `start` passes `answers=fab.channel.answers_text(chain.subject,
    events)`.
- **`fab.calls.start`:** after rebinding the Call facts, it reads
  `fab.channel.answers_text(subject, fab.log.read(log_path))`. When that
  is not empty, it puts `fab.channel.SECTION`, a blank line and the text
  right after the Call facts section, before the next `# ` section, or at
  the end when there is none. This happens before brief.md is written, so
  the call's review quotes it too. Its docstring says so. `--brief-only`
  prints the brief as compiled, before facts and answers are bound.

## Acceptance

- `fab/tests/test_channel.py`, under a temporary HOME and FAB_HOME:
  - `compose` with a plan written in the test with a `[[question]]`, a
    directory without plan.toml (skipped), one whose plan.toml does not
    parse (unread), a call's question with its report under
    FAB_HOME/calls, a parked chain with and without a report, and a
    report under FAB_HOME/reports;
  - `write` puts the page at FAB_HOME/user.md;
  - `answer`:
    - a call's question: the record's fields, its question line from the
      report;
    - a parked chain: `parked: <reason>`;
    - a blank text, an unknown subject (the open ones named), a plan
      question's id: each a ValueError, nothing logged;
  - `main` through `fab.cli.main(["page", ...])`: `show`, `write`,
    `answer` (logged, the page rewritten without the question), an error's
    exit 1, bad arguments' exit 2.
- `fab/tests/test_package.py`: `fab --help` lists `page`.
- `fab/tests/test_dispatch.py`:
  - a call that asked parks its part until `call.answered` names it;
  - a `question.answered` naming the subject leaves it parked;
  - a later done call of the subject unparks it;
  - an answer call that ended `Question:` starts no answer call, with
    open questions past ANSWER_AT, while its draft is parked; a
    `question.answered` naming the draft leaves it parked; a
    `call.answered` naming the draft, or a later done call of the draft,
    starts one again;
  - a tick writes the page, and a page that cannot be written prints its
    failure line while the tick returns its actions.
  The test that answers with `question.answered` today moves to
  `call.answered`.
- `fab/tests/test_call_review.py`:
  - `chains` resets on `call.answered` and not on `question.answered`;
    the existing reset tests move to `call.answered`;
  - `brief` with answers, after the findings and before the diff, and
    without them, unchanged;
  - `start` passes the subject's answers.
- `fab/tests/test_calls.py`: `start` with `fab.sh.run` faked puts the
  answers after the Call facts in brief.md, and writes no section when the
  subject has none.
- `bin/fab test` passes and `bin/fab status docs/plan/agents-rebuild` shows
  no problems. The touched test modules stay within their budgets.

## Options, settled up front

- `by` is `user` for every answer `fab page answer` logs. Whoever types
  the command speaks for the user; there is no `--by` flag.
- TEXT is one answer of any length: its words are joined with single
  spaces. A multi-line answer is a later flag.
- The page is rewritten whole every tick: it is computed from files, and
  that is cheap.
- A plan's question is still answered in plan.toml by hand. `answer`
  refuses its id, because it is not a call's subject.
- The live log has two open call questions with no call.answered (the
  retire and accounting skeleton calls'). They show on the first page,
  which is right. The gates subject's question, answered by hand with
  `question.answered`, is closed by its later done call. No record needs
  rewriting.
