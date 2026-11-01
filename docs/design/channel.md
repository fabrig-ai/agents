# fab: the channel to the user

2026-11-01, split from `docs/design/fab.md` (its section 6 maps the old
section numbers). Status: `docs/design/channel.status.md`. Shared: the
overview, the event log and the tests are `docs/design/fab.md`'s.

## 1. In one page

- **The user's page** lists what waits on the user (questions, parked chains, signals) and takes the answers.
- **Each open ask is a forge issue,** and the loop replies to the user's comments there.

## 2. A channel to the user

- **Questions that are the user's** (budgets, machines, what is hard to
  reverse) park their task and are listed, with the reports' signals that
  are the user's, on one page the user reads; nothing else goes to the user.
- **Whoever asks decides it is the user's,** never the page. Four things
  are (`fab.channel.asks`, folded from the plans and the log):
  - a plan's `[[question]]` with no answer, the cut's (calls.md 3);
  - a call that ended `Question:` (gates.md 2);
  - a call's chain referred by settle as `user: ...`, or parked because
    settlement failed (calls.md 2); an ordinary second refusal or failed
    amend goes to settle first. Amend and settle calls' own `Question:`
    reports open no ask. Older parked asks stay open until their chain
    settles; a later `chain.settled` for the subject closes its parked ask,
    so its forge issue closes at the next `fab issues sync` (channel.md 3);
  - a QA finding's question from its triage call (qa.md 2: a `user` or
    `brief` decision, or a `path` line's `; user:`): Ask kind `finding`,
    subject `<draft>/triage/<finding>`, its text the question, what to read
    the walk's report; the page quotes the ask's text after the finding's
    title, rung and the first 12 lines of its reproduction. `fab page
    answer <subject> TEXT` logs `call.answered` as for any subject, which
    closes the ask (as it closes the call and parked kinds) and makes the
    finding new again or dropped (`brief`), its answer in the next triage
    call's brief; a `; user:` answer only releases the rung, and the next
    triage call's brief carries it.
  A task's questions are the foreman's and the answerer's and never reach
  the page; an answer call that cannot settle one ends `Question:` itself.
- **The page** is `FAB_HOME/user.md` on hel8 (`fab/channel.py`):
  - the open questions, the plans' first, then the log's in the order they
    were asked, each with what to read and how to answer it;
  - then `## Open signals` (`(none)` when there are none): each open
    signal folded from the log
    (`fab.channel.signals(events)`, pure), oldest first, as a block
    `### <id>, <what>, since <ts>`, its facts, `- Read: ...` and, but for a
    fault, `- Clear: \`fab page clear <id> TEXT\``. Three kinds:
    - `queue:<branch>`, a hand-pushed rejection (landing.md 3): `- Tip`, `- Step`,
      `- Tests` (the record's, `(see the log)` when []), `- Read:
      \`<gate>:<log>\``;
    - `red-<n>`, an after-landing red no task owns (after-landing.md 2): `- Tip`,
      `- Why` (`no fab task among the suspects`, `no suspects`, `not the
      suspects': <the foreman's line>` or `unfixed: <draft>/red-<n> landed,
      still red at <tip>`), `- Tests` (at most 10, then `and <k> more`),
      `- Suspects` (hand-pushed ones marked), `- Read:` the evidence file
      and the foreman's report when there is one;
    - `fault:<profile>`, a pair that cannot run: `- Fault` (its text),
      `- Runs` (how many in a row), `- Read: \`<host>:<run log>\`` (the
      run's `host`, after-landing.md 2);
    - `finding-<n>`, a QA finding its foreman left (qa.md 2): `- Rung`,
      `- Why` (`not the code's: <the foreman's line>`), `- Title`, `- Read:`
      the walk's report and the foreman's report;
    - `backlog:<draft>`, a ladder's backlog branch rejected twice at one
      render (qa.md 2): `- Branch`, `- Step`, `- Read: \`<gate>:<log>\``;
  - then, from each standing report's latest day (reports.md 2), its path and
    only the Signals lines whose owner is the user (the drafts' signal
    tables: targets, capacity, a usage limit, a budget the three questions
    could not settle); the rest of each report is the director's;
  - then `## After landing` (after-landing.md 2), then `## The ladder` for each
    plan with rungs (qa.md 2): `### <draft>`, one line per rung in plan
    order (its state: due, walking, waiting, holding or passed, with what
    it waits for), then `- Backlog: <n> findings in \`<backlog path>\``,
    then `## Unread`, as today. The ladder is not the user's: it is there
    so the session that walks by hand, and the director, read what is due
    where they read fab's other state, as `## After landing` is.
  The tick rewrites it at its end; `fab page show|write [PLAN_DIR...]`
  makes it on demand. Its plans are those in `FAB_HOME/plans` (tick.md 5) and
  those named. The drafts send the reports to the director, who passes the
  user what needs the user; the director reads the same page.
- **Answers come back on the same path.** `fab page answer SUBJECT TEXT` on
  hel8 logs `call.answered` and rewrites the page. The subject's calls may
  start again, and a parked chain's counts start afresh (calls.md 2). Every later
  call of the subject, and every review run of its chain, carries the
  user's answers in its brief (`# The user's answers`). A plan's question
  is answered in its plan.toml, landed with `fab land`.
- **Subjects are named apart from tasks:** `question.answered` names a task
  and `call.answered` a subject. A part and a task of the same name never
  unpark each other.
- **Signals with no other owner come to the page too** (the user, 11-01),
  a departure from "nothing else goes to the user" above: a red no fab task
  owns and a hand-pushed branch's rejection have no owner fab knows (no
  task, no plan, no session it can name), and the director, who passes the
  user what needs the user, reads the same page. The page's first line
  says so: `Only what is the user's (budgets, machines, what is hard to
  reverse) and what has no owner fab knows.`
- **A signal opens and clears from the log:** `queue:<branch>` opens at a
  `queue.rejected` and clears at a later `queue.landed` of the branch, at
  a later `queue.rejected` or `queue.collateral` of it at another tip (a
  newer tip was tried; a newer rejection opens its own), or by hand;
  `red-<n>` opens when the red becomes a signal and clears when the red
  closes (after-landing.md 2) or by hand; `finding-<n>` opens at its
  `finding.settled` left and clears at its rung's next `rung.passed` (the
  rerun showed it was not the code's) or by hand, which drops the finding,
  the clear's text its reason; `backlog:<draft>` clears when the render
  changes, when a backlog branch of the draft lands, or by hand (the tick
  then readies it once more, and the count of two rejections restarts at
  the clear, so one further rejection raises it again); `fault:<profile>` clears only when a run
  does not fault the pair. `fab page clear ID TEXT` on hel8 logs
  `signal.cleared` (signal, by `user` or `--by`, text) and rewrites the
  page; it refuses an id that is not an open signal, and a fault. Clearing a
  red's signal closes the red (`red.closed`, reason `cleared`). A signal
  open again after its clear (a later raise) shows again.

## 3. The user's questions on the forge

- **One issue per subject** (`fab/forge.py`): `fab issues sync` takes the
  log's open asks (`fab.channel.asks((), events)`, 2), calls and parked
  chains only. A plan's questions stay in plan.toml. One pass opens,
  converses, then closes, under `FAB_HOME/issues.lock`; a second pass while
  it runs exits 0 at once. The log is the only state. No webhook or router;
  one conversation call runs at a time.
- **The forge** is Forgejo on hel8: API
  `http://127.0.0.1:3000/api/v1`, links `https://git.fabrig.ai`, repository
  `fabrig-ai/agents`, label 1 (`waiting-on-user`). The bot's `write:issue`
  token is read from `~/.config/fab/forgejo.token` and sent as
  `Authorization: token ...`. Standard-library `urllib.request` only;
  requests have a 30-second timeout and refuse redirects. Neither token,
  response bodies nor exception text is printed or logged. A forge error
  stops the pass with exit 1 and one line naming the step, method and path;
  earlier records remain for the next pass.
- **Open:** an ask without `issue.opened` for its subject gets an issue;
  after `issue.closed`, only a later ask opens another. Log order, not
  timestamp precision, decides later. Both ask kinds for a subject share
  one issue, using the newest ask. Title: `<subject>: <first non-blank
  question line>`, cut to 200 characters. Body: the call report's
  `channel.excerpt`, or the parked reason and its report's excerpt, then
  `Read: <report path>` and the footer: "Answer in a comment. Ask for more
  context if you need it: the loop replies here. Your answer is recorded
  once the loop reads it as one." Apply label 1 and log `issue.opened`
  (subject, kind, number, url).
- **Converse:** read all comments of each issue opened and not closed,
  paginated, oldest id first. Only `free` is acted on, and only an id not
  already named by `issue.comment` for that issue. Log `issue.comment`
  (number, subject, comment id) before starting one `reply` call. Its brief
  holds the role text, Call facts, the ask's question, report excerpt and
  path, and the issue thread through this comment as
  `**<author>** (<time>): <body>` blocks. Later comments wait their turn;
  bot comments are context. An answer ends the conversation.
- **The reply** (`fab/roles/reply.md`, `fab.calls.ROLES`, effort medium)
  reads what the question and report point to: code, designs, FAB_HOME
  runs and calls. It changes no repository file and pushes nothing. It
  runs through `calls.start` in the agents clone, with subject
  `issues/<number>`, keeping the call's artifacts and usage (reports.md 3).
  No plan owns that subject; the tick reserves no capacity for reply calls
  and neither reviews, collects nor lands them. Their `call.ended done`
  cannot close the asking subject (2).
- **The report's first line** is exactly `Done: reply` or `Done: answer`,
  then a blank line, then only the text to post or record. A request for
  context or a counter-question gets a short, plain reply, the options and
  a recommendation when helpful. A decision (an option, yes to the
  recommendation, the user's own choice) becomes a self-contained answer
  in one paragraph; wrapped lines become spaces.
  - Reply: post the text as a comment and log `issue.replied` (number,
    call).
  - Answer: `channel.answer(subject, text, events, by="user")` logs
    `call.answered` and wakes the tick exactly as `fab page answer` does;
    comment `Recorded as your answer: <text>`.
  - Anything else, or a failed call: comment "The loop could not read this
    comment; it will retry on your next comment." and log `issue.replied`
    with outcome `failed`. A consumed comment never runs again, including
    after a posting error; the user's next comment starts another call.
- **Close:** after conversations, reread the log. For each issue opened
  and not closed whose subject has no open ask, comment "Answered;
  closing.", PATCH its state to closed, then log `issue.closed` (number,
  subject). A `fab page answer` follows the same path. Completed mutations
  are logged before moving on; a crash between a forge mutation and its
  record can repeat that mutation on the next pass.
- Deployment (the token file, a transient timer on hel8 running
  `fab issues sync` every 2 minutes) is by hand.

## 4. Later

- The user's page published where the user reads it without hel8 (the
  status page in reports.md 4, a doc), once the user says where; a notification when a
  question joins it.
- A plan's question answered by `fab page answer`, writing plan.toml and
  landing it as the foreman lands its answers.
