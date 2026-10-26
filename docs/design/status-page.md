# Status page

Provisional, 2026-10-26, with the user. One page for the whole fleet,
https://status.fabrig.ai. It shows the work in flight, what building,
testing and landing cost, and how much of each subscription is used. `scripts/devel/status-page` writes
it every 10 minutes on hel8 from what the tools already keep, and Caddy
serves it.

## 1. In one page

- **Why.** The facts are all recorded, but on six machines and in
  seven formats. `landings report` answers for landing alone, on the
  coordinator, and `record runs` only per mission. "A script that
  generates an HTML status/dashboard page from those records … all
  in-flight work and their status plus statistics about
  build/test/landing times" (the user, 10-25).
- **It reads and never writes,** but for one file. Each machine's part
  is read from the files and commands its tools keep (section 2), and
  no tool changes for the page. The one thing it records is the
  subscriptions' use, sampled as each page is written on hel8, for
  their pace (2.2): a small file outside the web root, mode 0600,
  holding no identity beyond a subscription's label, and pruned as its
  samples stop counting (the user, 10-26). Only a run given that file
  writes it.
- **Nothing to install on the fleet.** The writer pipes its own source
  to each machine over SSH, into `bash -lc 'exec python3 -I - collect'`
  (a login shell, agents' `AGENTS.md`), with the options `landings` uses,
  so that every machine runs the version that renders.
- **One failure leaves the rest.** An unreachable machine, a source it
  cannot read, a field of the wrong type or a section whose data makes
  no sense is named in the page's footer, and everything else is still
  written. A field of the wrong type is a missing one, as in
  `landings`. The detail goes to the journal.
- **Public, without the director's notes.** The page is served to
  anyone, so it holds no text from `records`' `STATUS.md` nor from a
  mission's README beyond its front matter's `state`, `ended` and
  `description`, and its `started` as a time alone, for a duration
  (the user, 10-25 and 10-26). No owner, designer,
  implementer or other session shows by name: the page counts them, and
  a name only joins a session to its mission (the user, 10-26). Each
  machine's public IP shows on its card (the user, 10-26). The
  director's post shows as a count alone: no sender, subject or body.
  What waits on the user shows as a count of open issues and a link to
  them, which only a signed-in user can follow: no title, body or
  author (the user, 10-26). An
  unreachable machine shows why in a few words (refused, timed out, key
  refused); ssh's own, which name the target, go to the journal. No
  account's email, name, organisation or id: a subscription goes by a
  label that names nothing (section 2.1).
- **The issues' token stays where it is.** The collector of the machine
  that holds it reads it from its file and sends it in a request
  header alone: never in an argument, the journal, the page or the
  `--json` file.
- **Subscriptions.** "We might have several claude/codex subscriptions
  at the same time … go through all machines of the fleet and probe
  the subscription usage of both claude and codex … deduping results"
  (the user, 10-26). Each machine asks the two CLIs, through their own
  commands and never a credential, what they are signed in to and how
  much of it is used; the page merges the machines that share one.

## 2. Sources

| Source | Where | What the page takes |
|---|---|---|
| heavy's rows | each machine's `tmp/logs/heavy.tsv` | the last week's commands: wait, run, exit, kind, mission |
| heavy's ledger | `tmp/heavy/state.json` | the tasks queued and running, and whether a gate holds the machine |
| the landings feed | the coordinator's `~/.local/state/agents-land-set/feed.jsonl` | set runs and their results' gate steps (landing-flow.md 10) |
| the landing turns | `tmp/landing-turn/events.jsonl` | each turn's wait and hold, and the turns open now; a `fail-open` closes one |
| codex-run | `tmp/codex-run/*/meta`, `runs.tsv` and the `codex-run-*` user units | the implementers running, each with its mission, and the runs that ended |
| Claude | `claude agents --json --all` | the live sessions by role, busy or idle: the director, the designers (`design/<d>`) and owners (`o/<m>`) by their names, and the rest |
| the records | `records/missions/*/README.md`, after `record pull` | each mission's front matter: its `state`, `ended` and `description`, and its `started` read as a time (anything else is unknown) |
| the user's issues | git.fabrig.ai's API (Forgejo), from the machine holding `tmp/git-fabrig/status-read.token` (hel8), a read token for issues and repositories | how many open issues of `fabrig-ai/agents` carry its label 1, `waiting-on-user` (2.3) |
| the director's post | `tmp/post/director/new/` and `cur/` (post.md 3), on whichever machine holds them | how many messages owners (`o/…`) and designers (`design/…`) sent the director in the last 24 hours, by each one's `Id` stamp: its `Id` and `From` headers alone, of the files changed within the day |
| the machine | `/proc`, the disk under `tmp/`, `ip -j -4 addr show scope global` | load, free memory and disk, and its public IPv4 addresses (the globally routable ones) |
| Claude's subscription | `claude auth status --json`, `claude -p /usage` | what it is signed in to, and each limit's use and reset (2.1) |
| Codex's subscription | `codex app-server`: `account/read`, `account/rateLimits/read` | the same (2.1) |

A command's kind is `record runs`' (records.md 5.1): `land <repo>` and
`land <repo> prebuild` labels are land's gate and prebuild, and the
rest by the cargo command. A command's mission is its working
directory's under `tmp/owners/`, and a session's its name's: the name
whole when the record holds a mission so named, else without an old
milestone's `-m<N>`. A set's mission is its name before the first `/`
(`web-look-6/set-1`), only when the record holds a mission so named:
`land-set`'s worktrees lie outside `tmp/owners/`. The collector sends
names whole, and the page, which has the record, decides.

### 2.1 Subscriptions

Each machine's collector asks the CLIs it has, and reads no
credential: not `.credentials.json`, `auth.json` nor a token.

| CLI | Who | Limits |
|---|---|---|
| Claude Code | `claude auth status --json`: `loggedIn`, `authMethod`, `orgId`, `email`, `subscriptionType` | `claude -p /usage --output-format json --no-session-persistence --strict-mcp-config --tools "" --model haiku --settings '{"disableAllHooks": true}'`, under `TZ=UTC`: the `result`'s lines `Current <limit>: <n>% used · resets <when>` |
| Codex | `codex app-server` on stdio, after `initialize`: `account/read`'s `account` (`type`, `email`, `planType`) | `account/rateLimits/read`, `excludeResetCreditDetails`: its `accountId`, and each bucket's (`rateLimitsByLimitId`, else `rateLimits`) `primary` and `secondary` windows: `usedPercent`, `windowDurationMins`, `resetsAt` |

- **A probe's answer** is one of four: a subscription, with its label,
  plan and limits; signed out (Claude's `loggedIn` false, Codex's
  `account` null); no subscription (an API key, Bedrock); or no such
  CLI on the machine. Signed out is a state the page shows, not a
  failure. A timeout, an exit the CLI doesn't document, or an answer of
  the wrong shape fails that probe alone (section 1).
- **The label** is the first 8 hex digits of SHA-256 over the CLI's
  name, the account's id (Claude's `orgId`, Codex's `accountId`) and
  its email, joined by NUL bytes. The collector computes it: the email
  and the id never leave the machine, in the page, the `--json` file or
  the journal. The id is published nowhere, so a guessed email can't
  be checked against a label by someone who doesn't already hold the
  account's id. A subscription without both has no label, and shows
  with its machine alone, as unidentified.
- **A limit** has a name, the percent used and its reset, a time.
  Claude's name is the line's `<limit>` (`session`, `week (all
  models)`, `week (Fable)`), letters, digits, spaces and brackets only;
  its `<when>` (`Oct 30, 7pm`, `Oct 26, 5:30am`, or a time alone for
  today) is UTC: the first such time no more than an hour before the
  probe, so that a reset read as it passes stays in its year. Codex's
  name is its window's length (`5 h`, `week`, else in minutes, hours or
  days), after the bucket's `limitId` when that isn't `codex`: a
  lowercase slug, else `other`, and never the backend's `limitName`,
  free text that could name an account. A reset that cannot be read
  leaves the use.
- **Merged on the page:** the machines whose probes carry one CLI's
  label share that subscription. Each of its limits is the reading with
  the latest reset, then the highest use: a later reset is a newer
  window, and within one window use only grows.
- **Cheap.** The probes run beside the collector's other sources:
  each Claude command under a timeout of 30 s, and the whole Codex
  exchange under one, after which the app-server and what it started
  are ended. `/usage` must be answered by Claude Code itself
  (`local_command` `usage`, `num_turns` 0, `total_cost_usd` 0), or the
  probe fails and the footer says so. No flag stops a print run before
  its first request (`--max-turns 0` doesn't), so a version that sends
  `/usage` to a model would spend at each run until the footer is
  read: the smallest model, with no tools, MCP servers or hooks, keeps
  that to a fraction of a cent a probe. No session is kept, so neither
  `claude agents` nor `record runs` sees a probe. The app-server is
  asked nothing that changes the account: never
  `account/rateLimitResetCredit/consume`, never with `refreshToken`. A
  token either CLI refreshes on its own is its own business, as in any
  session on that machine.

### 2.2 Pace

"When the subscription would reach limit at the current pace (we
could use the status script itself for sampling)" (the user, 10-26).

- **The samples.** A run given `--samples FILE` adds to it, as it
  writes the page, one sample per limit of each labelled subscription
  as merged (2.1) that has a use and a reset: a JSON line `{"time",
  "cli", "label", "limit", "used", "resets"}`, times in seconds since
  the epoch. A subscription without a label has no samples, since
  nothing joins its readings.
- **Kept** while it can still count: a sample whose reset has passed,
  or older than a day, is dropped, and the file keeps at most 5,000
  lines, the newest. It is rewritten whole and replaced atomically,
  mode 0600, in a directory made 0700 when missing. A line of the wrong shape is
  dropped and counted in the footer; a file that cannot be read or
  written is named there, and the page is written all the same.
- **The current pace** of a limit is the rise in its use from the
  oldest sample of its window in the look-back to now, over the time
  between them. Its window's samples share its CLI, label and limit,
  with a reset within 10 minutes of the current one's (a new window
  has a new reset). The look-back is as long as what is left of the
  window, at least an hour and at most a day: a session's pace is its
  last hour or so, a week's its last day, and a window near its end is
  judged on as long as it has left. A pace needs its two readings a
  quarter of the look-back apart, and at least 30 minutes: a use read
  in whole points moves too little in less, so that a week shows its
  pace once it has 6 hours of samples, and a session after about an
  hour.
- **At this pace** the limit is either full before its reset, at `now
  + (100 − used) / pace`, or lasts to it, at `used + pace × (reset −
  now)` then, rounded down; a pace of zero or less lasts at its use.
  A use of 100 or more is full now.

### 2.3 The user's issues

What waits on the user is a Forgejo issue on git.fabrig.ai, in
`fabrig-ai/agents`, labelled `waiting-on-user`, label 1 (the user,
10-26).

- **The count.** The collector of a machine holding
  `tmp/git-fabrig/status-read.token` (mode 0600, refused if others can
  read it) asks the API, with `Authorization: token <it>`: first
  `GET /api/v1/repos/fabrig-ai/agents/labels/1` for the label's name,
  then `GET /api/v1/repos/fabrig-ai/agents/issues?state=open&type=issues&labels=<name>&limit=50`,
  page by page until a page holds fewer than 50, at most 20 pages. It
  counts the issues that carry label 1: Forgejo drops a label name it
  doesn't know and would list every open issue. The answer is `{"open":
  n}`, and nothing of an issue leaves the machine.
- **Bounded.** Each request under 15 seconds, the whole under 30, and
  a redirect refused, so that the token's header never follows one. A
  refused token, a missing label, more than 20 pages or an answer of
  the wrong shape fails that source alone (section 1); the footer names
  the HTTP status or the error's kind, never a response's body.
- **Where.** The first machine reached, in the machines file's order,
  whose answer is a count gives the tile; with none, the tile is a dash
  and the footer says that no machine reached holds the token.

## 3. The page

- **Tiles:** missions, sets landing now, agents (the director,
  designers, owners and implementers live, and how many of them are
  busy), the director's post in the last 24 hours from owners and
  designers (`12 from owners, 3 from designers`; a dash where no
  machine reached holds the director's mailbox; the user, 10-26), land
  gates in the last 24 hours, what waits on the user (the open issues
  so labelled, the sub a link to them,
  `https://git.fabrig.ai/fabrig-ai/agents/issues?state=open&labels=1`;
  a dash where they can't be read, named in the footer; the user,
  10-26), and the subscriptions with the highest use among them. Heavy's commands now show on each machine's card alone (the
  user, 10-26).
- **Subscriptions,** after the tiles: a table, one row per distinct
  subscription and limit, giving its CLI, plan and label, a bar of the
  percent used, its reset (in how long), and at this pace (2.2):
  `full in 2 h 5 min`, the time on hover, `lasts, 64% at reset`,
  `full`, or a dash with no pace yet. Which machines
  share it the page doesn't say (the user, 10-26). The machines signed out, with no subscription, or with an
  unidentified one follow, by CLI. A machine not reached adds nothing.
- **In flight:** what is landing (set runs, `land`'s prebuilds and
  gates, landing turns) and the last five set runs, each stopped one's
  reason cut to its kind: `land-set:`, the repository where it names
  one, and the first clause, before a colon or an `outside …`
  (`land-set: rebase conflict`, `land-set: temper: land --no-push
  failed (4)`), so that no path or file name shows. A set is in flight
  when its latest run, as `landings` finds it, has not ended and was
  heard from in 6 hours: a killed `land-set` writes no end, and a turn
  is lost the same way. Then the missions, and one card per machine
  with its public IP, its heavy tasks, its implementers and its Claude
  sessions.
- **A mission's row:** its name, its state in the record, its
  description, what runs for it now, and its last activity. An owner
  idle on its waiters is waiting, as the roles have it, not missing.
  The missions ended in the last 7 days follow, newest first, with
  their `ended` time, their duration (`ended` less `started`, a dash
  where `started` is unknown or later) and their description: never
  their `end`, which is prose, nor `closing.md`.
- **What runs for a mission now** is one label, the first of these
  that holds, with how many hold where several do (`2 × build`), so
  that the description keeps the room (the user, 10-26). What is
  running comes before what waits, and within each the stage nearest
  `main` first:
  1. `landing`: a set of its in flight and started, or its land gate
     or prebuild running in heavy;
  2. `build`: another heavy command of its running;
  3. `implementer`: an implementer of its alive;
  4. `owner busy`, then `designer busy`: its session busy;
  5. `queued landing`: a set of its waiting for the lock, or its land
     gate or prebuild queued;
  6. `queued build`: another heavy command of its queued;
  7. `owner idle`, then `designer idle`.

  The running ones take the info tone, the queued the warning tone and
  the idle the neutral one; with none, a dash.
- **A machine's card** counts its implementers by mission and state
  (`alpha-m: 2 running, 1 stale`; stale when the unit is gone) with
  their models, and its Claude sessions by role and state (`director,
  3 owners, 1 other · 2 busy`).
- **Costs,** for the last 24 hours or 7 days: command time per hour or
  4 hours, running and waiting; each kind's medians and p90s; each
  machine's; land's gates and prebuilds per repository; land-set's gate
  steps; set runs' lock wait and run; the landing turn; the
  implementers' runs (`codex-run task`) and their tokens per model.
- **A mission shows** when the record holds it active or paused, when
  anything runs for it now, or when it has commands in the last 24
  hours and the record doesn't say it ended. Directories under
  `tmp/owners/` alone bring in nothing: the sweeps touch ended ones.
- **Times** show relative to the page's writing (`11 min ago`, `in 2 h
  19 min`, or how long something has run), each with its exact UTC
  time in its hover title (`2026-10-26 03:49 UTC`), so that a cell
  holds one of them (the user, 10-26): in the tiles, the tables and
  the machine cards. Only the time the page was written and the
  charts' hours show as clock times. An ended mission's duration reads
  `42 min`, `5 h 12 min` or `3 d 6 h`, as a reset's does.
- The page reloads itself every 5 minutes, carries `noindex`, and works
  in light and dark. Every chart has a table beside it.

## 4. Serving

On hel8, whose name `status.fabrig.ai` is (a CNAME of `fabrig.ai`):

- hel8's own key reaches every machine of `tmp/post/machines` with a
  shell, and each is in its `known_hosts` (checked 10-25). post's
  restricted key is not enough.
- `~/src/rust/agents/scripts/devel/status-page install --out
  /var/www/status/index.html`, from the checkout and never a worktree,
  writes the user units `status-page.service` and `status-page.timer`
  (`OnCalendar=*:0/10`) and starts the timer. The service runs the
  checkout's script in a login shell (agents' `AGENTS.md`), so that
  `setup`'s fast-forward brings each change. It runs the page with
  `--samples ~/.local/state/status-page/usage.jsonl` (2.2), under
  `XDG_STATE_HOME` when that is set; `install` again rewrites the
  units.
- `/var/www/status` belongs to `free`. The page is replaced atomically,
  mode 0644, so Caddy never reads half of one; `--json` writes 0600.
- `/etc/caddy/Caddyfile` holds:

  ```
  status.fabrig.ai {
  	root * /var/www/status
  	file_server
  	header Cache-Control "no-cache"
  }
  ```

To take it down: `systemctl --user disable --now status-page.timer`,
remove the two units from `~/.config/systemd/user/` and
`~/.local/state/status-page/`, then the Caddy
block (`/etc/caddy/Caddyfile.pre-status-page` is the file before it)
and `systemctl reload caddy`.

## 5. Testing

`scripts/devel/test-status-page`, in `scripts/check.sh`: temporary
trees for two machines and the records, a fake `ssh` that runs the
piped collector on the second and fails the third, and fake `claude`,
`systemctl` and `record`. It checks each source's figures, a machine
with none of them, the page (no private text, the down machine, the
sets in flight, mode 0644), a failing pull and a missing records tree,
fields of the wrong type and markup in names, a machine answering
nonsense, a page that cannot be written, and the units `install`
writes. Fake `claude` and `codex` answer each machine from its tree:
two machines on one subscription merged, with the later reset's and
the higher reading; a second subscription; signed out, an API key and
an unidentified one; resets read across a year's end; a `/usage`
answered by a model, a probe that times out and one that answers
nonsense, each named in the footer while the rest stands; the methods
asked of the app-server; and no email or id, on the page or in the
`--json` file. The director's post: messages from owners and
designers within the day counted, by role; older ones, other senders
(`codex-run`, `qa-watch`, the user) and a file without an `Id` or a
`From` not; a machine without the mailbox adding nothing and naming
nothing in the footer, and the tile's dash with none reached; no
sender, subject or body on the page or in the `--json` file. The
pace: a limit full before its reset, one that
lasts, one at 100, one without two samples far enough apart, a new
window's samples kept apart from the old one's by their reset, the
look-back as long as the time left within its bounds, samples pruned
past their reset and past a day, a line of the wrong shape dropped and
counted, a samples file that cannot be written named in the footer
with the page still written, no file written without `--samples`, the
file 0600 holding labels alone, and `install`'s unit passing it. The
roles' names: an owner's and a designer's session
joining its mission, implementers per mission and machine, a recorded
name ending `-m2` kept whole and an unrecorded one cut, missions ended
within the week and before it, and no Codex owner read; no owner's,
designer's, implementer's or session's name anywhere on the page, and a
description shown. What runs: one label per mission, each rank of
section 3 over the next with its count, a set joining its mission by
name and an unrecorded set's prefix bringing in none, and a description
of 65 characters shown whole. Times: each relative time in a tile,
table or card carries its exact UTC time as its hover title, no cell
holds a clock time beside it, and an ended mission's duration in days,
hours and minutes, with a dash for a `started` unknown, not a time or
after `ended`, whose text reaches neither the page nor the `--json`
file. `test-record` proves `record`'s check of the `description` key.
The user's issues, from a fake Forgejo: the label's name asked, then
its open issues counted, those without label 1 left out; the token in
the requests' `Authorization` header and nowhere on the page, in the
`--json` file, the footer or the collector's arguments; a token file
others can read refused; a refused token, a missing label, a timeout
and an answer of the wrong shape each a dash named in the footer while
the rest stands; a machine without the token adding nothing; and no
title, body or author on the page.

## 6. Open

- Mission names are public. If one ever must not be, the page needs a
  filter, or a login in front of it.
- The roles don't point at the page yet.
- A mission's `parent` and `feature` stay off the page, and so does
  the chain they would draw: the description says what a mission is
  for (the user, 10-26).
