# fab: reports, accounting and the status page

2026-11-01, split from `docs/design/fab.md` (its section 6 maps the old
section numbers). Status: `docs/design/reports.status.md`. Shared: the
overview, the event log and the tests are `docs/design/fab.md`'s.

## 1. In one page

- **Reports are computed from the log,** never kept by hand: the code report, the landing report and their figures.
- **Accounting** weighs Claude and Codex usage per call and run.
- **The status page** (`fab serve`, status.fabrig.ai) is public and shows counts only.

## 2. Reports

- **Two standing reports, from records alone:** the code report of a plan
  (the metrics of `docs/design/draft/code-producing-pipeline.md`, 3, that the
  log records) and the landing report (those of
  `docs/design/draft/landing-pipeline.md`, 3, that the queue's record holds).
  Nothing is counted by hand and nothing new is recorded for them.
- **`fab report` runs on hel8.** It reads the whole log there, the queue's
  record from the gate machine (`fab queue log --since`, as the tick does) and
  each builder's and the gate's `heavy.jsonl`, over ssh, seven days back. A
  source it cannot read is named in the report, never a failure.
- **A report covers one UTC day,** or today so far on demand, and every figure
  stands beside the previous day's: the trend the drafts ask for until the
  user sets targets.
- **The code report** (`fab/code_report.py`): runs started and their outcomes,
  branches ready, landed and rejected; runs in flight per hour against the
  builders' places; idle gaps (no run in flight while a task is not landed,
  10 minutes or more) with the tasks' statuses at their start; runs and Codex
  minutes per landed task; questions, their rate per report and time to
  answer; Infra minutes and heavy's lane and disk waits on the builders;
  Claude calls, minutes and tokens, Codex's tokens and the weights (3);
  the stops (questions, failed and Infra runs, rejections) ranked by time
  lost; the same per part.
- **The landing report** (`fab/landing_report.py`): batches, their outcomes
  and branches; the share of the day in gate steps; rejections by step (the
  red classes) and collateral ones (a rejected tip that later lands, and the
  branches the queue retried after a collateral red, landing.md 3); batches landed
  on a precheck receipt; ready to
  landed latency (from the log's `branch.ready`), branches waiting and the
  oldest wait; bisection runs and minutes; repair rounds; each step's
  durations, failures and timeouts; batches in error; heavy's waits on the
  gate. From the log, cheaply (after-landing.md 2, landing.md 3): after-landing reds opened,
  sent to a foreman and sent to the page; settled fix, none and left (not
  the suspects'); red repairs landed; reds closed, by reason (recovered,
  absent, cleared), with the median hours from opened to recovered (the
  draft's "time to the confirmed fix"); hand-pushed rejections
  (`queue.rejected`). From the log too, the landing draft's "QA passes ...
  and their findings" (qa.md 2): walks by verdict, findings raised and
  merged, triaged by decision, finding repairs landed, rungs passed, and
  the median hours from a failed walk to its rung's next pass. These are
  decisions the tick records anyway, not records kept for the report.
- **Signals without targets:** a report raises only the drafts' signals that
  need no number of the user's: idle gaps, rising rejections, Infra runs,
  collateral rejections, queue errors, a ready branch waiting over an hour and
  longer than the day before, disk waits and unread sources, an after-landing
  red or a hand-pushed rejection with no owner fab knows (channel.md 2's open
  signals), each with the draft's first action and owner. Thresholds come with targets.
- **Where they go:** `FAB_HOME/reports/<draft>/<day>.md` and
  `FAB_HOME/reports/landing/<day>.md` on hel8, written to a sibling and
  renamed. `fab report daily PLAN_DIR...` writes yesterday's that do not
  exist yet; the director reads them there.

## 3. Accounting

- **run.ended carries Codex's tokens** (input, cached, output) from the run's
  result: `fab run status` reads the launcher's `result.json` in the ssh that
  reads the report, and `tokens` is `<input>/<cached>/<output>`, Codex's
  input holding its cached tokens. call.ended's `tokens` keeps its shape,
  `<input>/<cache read>/<output>`, Claude's input holding neither cache reads
  nor writes, and gains `cache_write`. Records from before have no
  `cache_write` or no `tokens`, and weigh as if they had none.
- **A call's usage comes from claude's stream** (`--output-format
  stream-json`), kept as `FAB_HOME/calls/<id>/stream.jsonl`: the totals and
  turns from its result event, and `peak`, the largest context (input, cache
  write and cache read) of one message of the main thread; subagents have
  their own context and are left out of it. A call cut short by its timeout
  has no result event, and is measured from the messages it streamed.
- **The code report weighs both** (`fab/accounting.py`): input 1, cache write
  1.25, cache read 0.1, output 5 for Claude and 8 for Codex, in millions. A
  draft's Claude calls are those whose subject is the draft or under it; its
  Codex runs are its tasks' and the review runs of its calls. Its figures show
  the Claude and Codex tokens, both weights, the Claude to Codex weight, the
  largest call context and the calls over 600k; a Calls table lists each call
  with its minutes, turns, peak context, weight and whether it is over.
- **A call is measured, not capped, for now** (the user, 10-30): no context
  cap and no turn limit (no `--max-turns`); a call is stopped only by its
  60-minute timeout (40 until the user raised it, 10-31, after the
  playground replay's cut ran out with its four designers in flight). call.ended carries its peak context and turns, and the
  code report flags calls over the user's 600k target (10-30; the model's
  draft said 120k). Of the first eleven calls, seven peaked over 120k
  (130k-190k) and all ended well; the user sets a cap, if any, from the
  measurements. The code may hold an unset
  bound for later; nothing ends a call for its size now.

## 4. The status page

- **Public counts and subscriptions from the log.** `fab serve [--port 8370] [--bind 127.0.0.1]`
  serves one HTML page at `/`, its JSON snapshot at `/api/status` and `ok` at
  `/healthz`. GET only; other methods return 405, other paths 404, and query
  strings are ignored. It prints its bound address, including a port chosen
  by `--port 0`.
- **Pure core, read-only shell.** `fab.serve.snapshot(events, now, hosts)`
  computes counts and subscriptions; `render(snapshot)` returns escaped HTML. Each request
  reads `FAB_HOME/log.jsonl` through `fab.log.read` and host names through
  `fab.hosts.load`. No lock, writes, cache, ssh or plan files. An unreadable
  log still returns 200, with `log: "unreadable"` and no figures; failures
  show fixed classifications, never exception text.
- **Now and waiting.** The last event's age; runs started within 24 hours
  and calls within `fab.calls.TIMEOUT` seconds without a matching end, by
  host and role. Waiting uses `fab.channel.asks((), events)`: only the log's
  open user asks, without plans or the foreman's task questions. The
  `waiting_on_user` snapshot has `asks`, `by_kind` (`call`, `parked`, `finding`) and
  `oldest_age_s` from the asks' `since`, null when none. Waiting has no age
  cut; answers, completed designs and finished chains close asks as on the
  user's page (channel.md 2).
- **Today is UTC.** `landed` counts `branch.landed` without `into` (on main);
  `merged` counts those with `into` (into a trunk). Each has `last_hour` and
  `today` counts; the page labels both under Today. Rejected branches and
  ended runs by done, question, infra, failed or other are today's.
  `fab.accounting.run_weight` and `call_weight` sum today's measured endings
  in millions, to one decimal; missing weights are skipped. Invalid timestamps
  and future events are skipped; today ends at the snapshot's time.
  The snapshot's `weight_today` keeps `codex_m` and `claude_m` and adds
  `ratio`: Codex divided by Claude using the unrounded totals, rounded
  to one decimal, or null when Claude's weight is zero. One tile replaces
  the separate Codex and Claude weight tiles: `Weight today · Codex/Claude`,
  value `4.9×` (one decimal) or `–` when the ratio is null, and sub
  `Codex 165.0M · Claude 33.2M` using the existing one-decimal figures.
  The Today card `Weight` stays unchanged.
- **Drafts come from run starts.** Only prefixes of `run.started` tasks in
  the log qualify. Those with a run in flight, a main landing or a trunk
  merge today show `runs_in_flight`, `landed_today` and `merged_today`.
  A main landing belongs to its task's prefix only when that prefix is a
  known draft from a run start; otherwise it belongs to `by-hand`. Missing,
  null, empty, `-` or slash-less tasks and unknown prefixes are `by-hand`.
  A trunk merge belongs to the prefix of `into` (`<draft>/integration`),
  only when that draft is known. Call branches do not create drafts.
- **Only public labels leave the fold.** Known host names, call roles from
  `fab.calls.ROLES` (others become `other`), and draft names matching
  `[a-z0-9][a-z0-9.-]{0,63}` (known drafts failing the pattern become
  `other`). A prefix ends at the first `/`; draft qualification uses this
  prefix before public classification. Subscription labels are
  masked emails. No task, run or call ids, branches, shas, paths, question
  or answer text, notes, reports, full emails or raw holders in HTML or JSON.
  Subscriptions expose only the public custody labels below.
- **Subscriptions:** include logins named `claude-<n>`, `claude-box-<n>` or
  `codex-<n>` of kind `claude`, `claude-box` or `codex`. Normalize `claude-box`
  to `claude` for grouping and display: a box login and a Claude login for
  the same account share one row and their sign-ins count together.
  Group nonretired logins whose latest
  `login.checked` is within 24 hours and successful (no error), with a
  nonempty email, by `(kind, email)`. Each login's latest check decides its
  current account; a failed check or one without an email leaves that login
  out. Full email is only an internal grouping key; groups sharing a mask
  stay separate. The snapshot's `subscriptions` list has one entry per group,
  sorted by kind then label. Each has `subscription` (the masked email),
  `kind`, `plan` matching `[a-z0-9_]{1,40}` or empty, `logins` (the sign-in
  count), `held`, `held_by`, `checked_age_s` and `limits`. `held` counts the
  group's logins currently lent, from `fab.logins.fold`: each login with a
  holder counts once; logins on the shelf count nothing. `held_by` is a
  sorted list of public labels, repeated once per use. A holder that is a
  known host name with the kind's machine path (`.claude/.credentials.json`
  or `.codex/auth.json`) is labelled by that host name. Holders beginning
  `walk/`, `after-landing/` or `check/` become `QA walk`, `after-landing`
  or `check`; any other holder becomes `other`. No other holder text, path
  or login id leaves the fold. For `local@domain`, the mask keeps
  the local's first and last characters around `***`, followed by `@` and
  the lowercased domain. A local of one or two characters keeps only its
  first character before `***`. Local characters keep their case; the domain
  is otherwise unchanged. Without exactly one `@` and two nonempty parts,
  the label is `***`. For example, `free.ekanayaka@gmail.com` becomes
  `f***a@gmail.com`. The group's newest successful check supplies its plan.
  A check's three nonempty scalar log lists are zipped back to `name`,
  `used`, `resets`. When the lists are empty or absent, a finite numeric
  `used` supplies one `week` limit with that `used` and `resets`: the older
  fab's weekly window. Nonfinite or nonnumeric figures become null; without
  lists or numeric `used`, the check has no limits. The group's newest
  successful check with limits supplies its figure and `checked_age_s`;
  a newer check with no limits does not hide an older figure. If no check
  has limits, use the newest successful check's age and empty limits.
  Fable is omitted;
  `5 h` appears only above 80% use. Each limit also has `rate_per_h`,
  `full_at` and `at_reset`, null without a usable earlier sample. Use the
  oldest successful sample across the group's logins for that account and
  limit with the same reset, reading limits by the same rule in both old and
  new checks, at least 20 minutes before the check supplying the figure;
  decreasing use and expired or unknown resets give no pace. Checks made
  under another account do not contribute. Rate is percent per hour to one
  decimal; projections use the unrounded rate from the figure's check time.
  `full_at` is Unix seconds if full before reset; otherwise `at_reset` is
  projected percent at reset to one decimal (zero rate lasts).
  The panel after Waiting on the user has Subscription (kind, plan, label,
  and `7 sign-ins` or `1 sign-in` on its first row), Held, Used (meter and
  percent), Resets (countdown and a UTC `time` element/title), Rate
  (`3.6%/h`) and At this pace (`full in 1 d 13 h`, `lasts, 19% at reset`,
  or `–`). Held appears only on the group's first row: a count in a
  `span` whose `title` joins `held_by` with ` · `, or says `none` when zero.
  There is no Limit column; a limit other than `week` follows its percent
  in Used in small text (`92% · 5 h`). Meters warn at 80% and turn critical
  at 95%. A check with no limits shows `–`. With no eligible subscriptions:
  `No login checked in the last 24 hours.` A Subscriptions tile after the
  weight ratio shows the highest `week` percent (`–` when absent), with
  `<n> subscriptions` below.
- The page reuses the previous status page's stylesheet and layout (tiles, panels, cards, badges), 1280 px wide.
- **One plain document.** Title `fab status`, inline CSS, no JavaScript,
  refresh every 30 seconds, phone width and light and dark colours. Header,
  tiles, Waiting on the user, Subscriptions, Drafts, Overlaps, Today, In flight, then footer; ages in
  seconds, minutes or hours. Waiting is the first section below the tiles.
  Its tile, kind labels (Call questions and Parked chains) and "Open the
  questions" below the oldest age link to the forge's open `waiting-on-user`
  issues at `https://git.fabrig.ai/fabrig-ai/agents/issues?state=open&labels=1`.
  The repository is private; the public page links to it without showing
  issue contents.
- **Deployment is by hand at the user's OK:** a transient unit on hel8 and
  Caddy's `status.fabrig.ai` moved to `reverse_proxy 127.0.0.1:8370`.

## 5. Later

- `fab report daily` on a timer on hel8, with the dispatcher's; reports
  posted to the director rather than read from FAB_HOME.
- Report metrics the records do not hold yet: lines changed per landed
  branch, questions by kind, continuity, CPU per step against its budget,
  after-landing verdicts by outcome, lag and coverage (its reds are counted,
  10); targets and their signals once the user sets them.
