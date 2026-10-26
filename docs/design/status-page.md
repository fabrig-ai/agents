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
- **It reads and never writes.** Each machine's part is read from the
  files and commands its tools keep (section 2). Nothing new is
  recorded, and no tool changes for the page.
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
  `description` (the user, 10-25 and 10-26). No owner, designer,
  implementer or other session shows by name: the page counts them, and
  a name only joins a session to its mission (the user, 10-26). An
  unreachable machine shows why in a few words (refused, timed out, key
  refused); ssh's own, which name the target, go to the journal. No
  account's email, name, organisation or id: a subscription goes by a
  label that names nothing (section 2.1).
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
| post | `tmp/post/*/new` | unread mail per box |
| Claude | `claude agents --json --all` | the live sessions by role, busy or idle: the director, the designers (`design/<d>`) and owners (`o/<m>`) by their names, and the rest |
| the records | `records/missions/*/README.md`, after `record pull` | each mission's front matter: its `state`, `ended` and `description` |
| the machine | `/proc`, the disk under `tmp/` | load, free memory and disk |
| Claude's subscription | `claude auth status --json`, `claude -p /usage` | what it is signed in to, and each limit's use and reset (2.1) |
| Codex's subscription | `codex app-server`: `account/read`, `account/rateLimits/read` | the same (2.1) |

A command's kind is `record runs`' (records.md 5.1): `land <repo>` and
`land <repo> prebuild` labels are land's gate and prebuild, and the
rest by the cargo command. A command's mission is its working
directory's under `tmp/owners/`, and a session's its name's: the name
whole when the record holds a mission so named, else without an old
milestone's `-m<N>`. The collector sends names whole, and the page,
which has the record, decides.

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

## 3. The page

- **Tiles:** missions, sets landing now, heavy commands now, agents
  (the director, designers, owners and implementers live, and how many
  of them are busy), commands and land gates in the last 24 hours, and
  the subscriptions with the highest use among them.
- **Subscriptions,** after the tiles: a table, one row per distinct
  subscription and limit, giving its CLI, plan and label, its
  machines, a bar of the percent used, and its reset (in how long, and
  when). The machines signed out, with no subscription, or with an
  unidentified one follow, by CLI. A machine not reached adds nothing.
- **In flight:** what is landing (set runs, `land`'s prebuilds and
  gates, landing turns) and the last eight set runs. A set is in flight
  when its latest run, as `landings` finds it, has not ended and was
  heard from in 6 hours: a killed `land-set` writes no end, and a turn
  is lost the same way. Then the missions, and one card per machine
  with its heavy tasks, its implementers, its Claude sessions and its
  unread post.
- **A mission's row:** its name, its state in the record, its
  description, what runs for it now, counted (its owner's or
  designer's session, busy or idle; its implementers; its heavy
  commands), and its last activity. An owner idle on its waiters is
  waiting, as the roles have it, not missing. The missions ended in the
  last 7 days follow, newest first, with their `ended` time and
  description: never their `end`, which is prose, nor `closing.md`.
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
  `setup`'s fast-forward brings each change.
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
remove the two units from `~/.config/systemd/user/`, then the Caddy
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
`--json` file. The roles' names: an owner's and a designer's session
joining its mission, implementers per mission and machine, a recorded
name ending `-m2` kept whole and an unrecorded one cut, missions ended
within the week and before it, and no Codex owner read; no owner's,
designer's, implementer's or session's name anywhere on the page, and a
description shown. `test-record` proves `record`'s check of the
`description` key.

## 6. Open

- Mission names are public. If one ever must not be, the page needs a
  filter, or a login in front of it.
- The roles don't point at the page yet.
- A mission's `parent` and `feature` stay off the page, and so does
  the chain they would draw: the description says what a mission is
  for (the user, 10-26).
