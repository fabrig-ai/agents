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
  `description`, its `started` as a time alone, for a duration
  (the user, 10-25 and 10-26), and its `blocked` as the references
  of issues alone (`temper#9`), with the time it was first committed
  so, from the record's history: never a commit's author, message or
  hash (2.4). No owner, designer,
  implementer or other session shows by name: the page counts them, and
  a name only joins a session to its mission (the user, 10-26). Each
  machine's public IP shows on its card (the user, 10-26). The
  director's post is not read (the user, 10-26).
  What waits on the user shows as counts of open issues and links to
  them, which only a signed-in user can follow into a private
  repository: no title, body or author (the user, 10-26). An
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
| the landings feed | the coordinator's `~/.local/state/agents-land-set/feed.jsonl` | set runs and their results' gate steps (landing-flow.md 10), and plain `land`s' records (landing-flow.md 12), counted alone: never their branch or `taught` |
| the landing turns | `tmp/landing-turn/events.jsonl` | each turn's wait and hold, and the turns open now; a `fail-open` closes one |
| codex-run | `tmp/codex-run/*/meta`, `runs.tsv` and the `codex-run-*` user units | the implementers running, each with its mission, and the runs that ended |
| Claude | `claude agents --json --all` | the live sessions by role, busy or idle: the director, the designers (`design/<d>`) and owners (`o/<m>`) by their names, and the rest |
| the records | `records/missions/*/README.md`, after `record pull` | each mission's front matter: its `state`, `ended` and `description`, its `started` read as a time (anything else is unknown), and its `blocked` read as the seven repositories' issue references, `<repo>#<n>`, n without a leading zero (records.md 3; any other word is dropped); for a mission so blocked, since when, from its README's history in the checkout (2.4) |
| the user's issues | git.fabrig.ai's API (Forgejo), from the machine holding `tmp/git-fabrig/status-read.token` (hel8), a read token for issues and repositories | how many open issues of seven `fabrig-ai` repositories carry their `waiting-on-user` label (2.3) |
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
- **The rate** is that pace per hour, beside it: `2.0%/h`, to one
  decimal, `0.0%/h` for none or a fall; its hover title the readings'
  span and its start (`over 5 h 12 min, since 2026-10-26 06:20 UTC`), a
  moving average as the look-back slides (the user, 10-26). A dash
  where there is no pace.
- **No pace yet.** Where a run keeps samples but its window's readings
  don't yet span enough, the pace says how long it still waits for
  them, at most: `pace in 2 h 10 min`, the span it needs (a quarter of
  the look-back, and 30 minutes) less the one it has, its hover title
  both (`needs 6 h of samples, has 3 h 50 min`); the look-back shrinks
  as the reset nears, so the pace may come sooner (the user asked why
  a week shows a dash, 10-26). Without samples, a dash.

### 2.3 The user's issues

What waits on the user is a Forgejo issue on git.fabrig.ai labelled
`waiting-on-user`, in any of seven repositories of `fabrig-ai`, each
with its own label's id (the user, 10-26; agents' `user-issues.md`):

| Repository | Label |
|---|---|
| `agents` | 1 |
| `skein` | 2 |
| `smith` | 3 |
| `jig` | 4 |
| `hearth` | 5 |
| `temper` | 6 |
| `qa` | 7 |

- **The count.** The collector of a machine holding
  `tmp/git-fabrig/status-read.token` (mode 0600, refused if others can
  read it) asks the API for the seven repositories at once, with
  `Authorization: token <it>`: first
  `GET /api/v1/repos/fabrig-ai/<repo>/labels/<id>` for the label's
  name, then
  `GET /api/v1/repos/fabrig-ai/<repo>/issues?state=open&type=issues&labels=<name>&limit=50`,
  page by page until a page holds fewer than 50, at most 20 pages. It
  counts the issues that carry the label's id: Forgejo drops a label
  name it doesn't know and would list every open issue. The answer is
  `{"open": {"agents": n, …}, "failed": {"temper": "HTTP 404"}}`: the
  repositories it read, and why each other could not be; nothing of an
  issue leaves the machine.
- **Bounded.** Each request under 15 seconds, all of them under 30,
  and a redirect refused, so that the token's header never follows
  one. A repository whose label is missing, whose token is refused,
  with more than 20 pages or an answer of the wrong shape fails alone,
  named in `failed` by the HTTP status or the error's kind, never a
  response's body. A token file others can read, or one that holds no
  token, fails the source whole (section 1).
- **Where.** The first machine reached, in the machines file's order,
  whose answer holds a count gives the tile; with none, the tile is a
  dash and the footer says that no machine reached holds the token.

### 2.4 Blocked since

"Since when" a mission has waited on the user (agents#12, the user,
10-27) is read from the record's history, never written: git's history
is the record's timeline (records.md 1), and every `blocked` line
reaches it through `record commit`. No writer can forget or misdate it,
the line written by a mission and by its parent alike.

- **The time** is the commit time of the oldest version of the
  mission's README in the newest unbroken run of its versions, on the
  checkout's `HEAD` along first parents, whose `blocked` names a
  reference (as section 2's records row reads it). The issues may
  change within the run (`temper#9`, then `temper#9 agents#11`), and
  the README be rewritten around the line: the mission has waited
  since the first. One that went on and was parked again waits since
  the second time. A run that reaches the README's first version waits
  since that version: its brief was committed blocked. It is when the
  mission blocked, not when its issue was opened: an issue it worked
  beside blocked nothing (user-issues.md 5).
- **A commit time is its publishing.** `record commit` makes each
  commit as it pushes, and remakes it on a `main` that moved (records.md
  2): its time is within seconds of the writing, or of the next push
  for one whose push failed (exit 3).
- **Committed history alone.** The working tree's README says which
  missions are counted (section 2's records row), and `HEAD`'s history
  since when. An edit not committed changes no since: a `blocked` in
  the working tree alone is unknown, and one `HEAD` already names keeps
  the run `HEAD` holds.
- **Read on the writing machine,** from the records checkout the page
  read, for the missions the count counts (section 3) alone: the
  README's commits newest first (`git log --first-parent
  --format='%H %ct' -- missions/<m>/README.md`), then their versions
  until one names no reference. Only commit times leave the history:
  never an author, committer, message or hash, on the page, in the
  `--json` file or in the footer.
- **Unknown,** a dash, where `HEAD`'s version names no reference, or
  where the history can't be read whole. The footer names each reason
  once, `records: history: <reason>`, in fixed words, while the rest
  stands: `no git repository`; `shallow`, a checkout whose history is
  cut (`git rev-parse --is-shallow-repository`), whose runs could end
  at its cut and so are read for none; `git failed`; `timed out`, the
  reads together running under 30 seconds and leaving what they didn't
  reach unknown. git's own words go to the journal: they can hold a
  path or a hash.
- **In the `--json` file,** each mission's `blocked_since`: seconds
  since the epoch, null where unknown or not blocked.

## 3. The page

- **Tiles:** missions, landings per hour (below), agents (the director,
  designers, owners and implementers live, and how many of them are
  busy), land gates in the last 24 hours, what waits on the user (the open issues
  so labelled in the seven repositories, in all; the sub each
  repository's count as a link to its issues,
  `https://git.fabrig.ai/fabrig-ai/<repo>/issues?state=open&labels=<id>`,
  in 2.3's order; a repository not read a dash, named in the footer,
  the sub then saying how many were read; the user, 10-26; and the
  missions blocked on the user, below), and the
  subscriptions with the highest use among them. Heavy's commands now show on each machine's card alone (the
  user, 10-26), and the director's post has no tile (the user, 10-26).
- **Blocked on the user** ("a "blocked" count for owners or designers
  blocked on me (taken from records)", the user, 10-26): the missions
  the record holds `active` or `paused` whose `blocked` names an issue
  (records.md 3), each an owner's or a designer's. The count leads the
  Waiting on the user tile's sub, `2 blocked ·` before the
  repositories' counts, its hover title each such mission by name with
  its issues (`configuring-docs: temper#9; ladder: agents#11`);
  `0 blocked` with none, and `– blocked` where the record was not
  read. It is the record's word, independent of the issues' source: a
  dash in the tile's value leaves it. In each of its three forms the
  count is a link to Blocked on you, `href="#blocked"`: on the same
  page, so it opens no tab (agents#12, the user, 10-27).
- **Blocked on you** (agents#12, the user, 10-27), the section after
  the tiles, `<h2 id="blocked">Blocked on you</h2>`: a table, one row
  per mission the count counts, the longest waiting first, then those
  whose since is unknown, each set by name. A row gives the mission's
  name, its state in the record (`active`, `paused`), its description
  (a dash without one), the issues it waits on, each `temper#9` a link
  to its issue, `https://git.fabrig.ai/fabrig-ai/<repo>/issues/<n>`,
  opening a new tab as the page's other links out, and since when
  (2.4): `5 h 12 min ago`, its time on hover as in Times below, or a
  dash. With none blocked it says `Nothing is blocked on you.`, and
  with the record not read `The record was not read this time.`, the
  footer saying why. Its data failing shows as any section's does.
- **Landings per hour** (the user, 10-26): the landings that pushed a
  `main` in the last 6 hours, over 6, to one decimal: a set's run once,
  at its last `landed` event, and a plain `land`'s record once. Six
  hours moves at each write and holds enough landings to be steady; the
  hover title gives the window and the raw counts (`87 in the last 6 h:
  4 sets, 83 lands`), and the sub the last landing (`last landed 3 min
  ago`, its time on hover, as in 3's Times). What is landing now stays
  under In flight.
- **Subscriptions,** after Blocked on you: a table, one row per distinct
  subscription and limit, giving its CLI, plan and label, a bar of the
  percent used, its reset (in how long), its rate (2.2), `2.0%/h`
  with its span on hover, and at this pace: `full in 2 h 5 min`, the
  time on hover, `lasts, 64% at reset`, `full`, `pace in 2 h 10 min`
  while its samples gather, or a dash without them. Which machines
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
  in light and dark. Every chart has a table beside it. A link out of
  the page (git.fabrig.ai's issues) opens a new tab, `target="_blank"
  rel="noopener noreferrer"`, so that the page stays open (the user,
  10-26).

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
sets in flight, landings per hour from sets and plain `land`s within and before the window, mode 0644), a failing pull and a missing records tree,
fields of the wrong type and markup in names, a machine answering
nonsense, a page that cannot be written, and the units `install`
writes. Fake `claude` and `codex` answer each machine from its tree:
two machines on one subscription merged, with the later reset's and
the higher reading; a second subscription; signed out, an API key and
an unidentified one; resets read across a year's end; a `/usage`
answered by a model, a probe that times out and one that answers
nonsense, each named in the footer while the rest stands; the methods
asked of the app-server; and no email or id, on the page or in the
`--json` file. A machine holding the director's mailbox adds nothing
of it to the page, the `--json` file or the footer. The
pace: a limit full before its reset, one that
lasts, one at 100, one whose samples don't yet span enough saying how
long it waits and what it needs, each pace's rate per hour with its
span on hover and a dash beside no pace, a new
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
The user's issues, from a fake Forgejo: for each of the seven
repositories its label's name asked, then its open issues counted,
those without its label left out, and the sum in the tile; one
repository failing alone, its dash and footer line beside the others'
counts and the sum of those read; the token in
the requests' `Authorization` header and nowhere on the page, in the
`--json` file, the footer or the collector's arguments; a token file
others can read refused; a refused token, a missing label, a timeout
and an answer of the wrong shape each a dash named in the footer while
the rest stands; a machine without the token adding nothing; and no
title, body or author on the page. Blocked on the user: an `active`
and a `paused` mission with `blocked` counted, and named with their
issues in the hover title, by name; an `ended` one (written past
`record`) and one whose `blocked` holds no reference of the seven
repositories not; a word of `blocked` other than a reference on
neither the page nor the `--json` file; `0 blocked` with none, `–
blocked` without the records tree, and the count beside the tile's
dash when no machine holds the token, each a link to `#blocked`.
Blocked on you, over a records tree that is a git repository whose
commits carry chosen times and an author and message of their own: a
mission blocked since its first blocked commit, through a later change
of its issues and a commit of its body alone; one blocked, gone on and
blocked again, since the second time; one whose `blocked` is in the
working tree alone, a dash; the rows longest waiting first, the
unknown after them; the state, the description and a dash without
one; each issue a link to its issue that opens a new tab; `Nothing is
blocked on you.` with none, and the record's line without the records
tree; a records tree that is no git repository, each since a dash and
the footer naming the history once, and the same of a shallow clone
and of a git that fails, in their fixed words; `blocked_since` in the `--json`
file; and no author, committer, message or hash of the history on the
page, in the `--json` file or in the footer. `test-record` proves `record`'s
check of `blocked`: the seven repositories' references taken, one or
several; another form (`temper#09`, `temper#0`, `temper 9`), another
repository and an issue named twice refused, and so is `blocked` beside a `state` of `ended`, `abandoned`
or `unknown`.

## 6. Open

- Mission names are public. If one ever must not be, the page needs a
  filter, or a login in front of it.
- The roles don't point at the page yet.
- A mission's `parent` and `feature` stay off the page, and so does
  the chain they would draw: the description says what a mission is
  for (the user, 10-26).
- The blocked count and Blocked on you trust the record: a `blocked`
  naming only closed issues still counts, and is listed, until its
  writer removes it. If that goes stale
  in practice, the issues' collector could return the open issues'
  numbers, which name nothing, and the page count only the missions
  blocked on one of them.
- A blocked mission's row under the missions doesn't say so; Blocked
  on you lists it.
