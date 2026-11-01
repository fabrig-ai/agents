# fab: builders, slots, disk, logins and the dispatcher's units

2026-11-01, split from `docs/design/fab.md` (its section 6 maps the old
section numbers). Status: `docs/design/machines.status.md`. Shared: the
overview, the event log and the tests are `docs/design/fab.md`'s.

## 1. In one page

- **Builders own their disk:** slots are claimed, swept and reclaimed so no implementer stops for disk.
- **Logins live on a shelf** (`fab logins`): captured, lent, returned and swapped across machines, and checked for their limits.
- **The dispatcher's services are fab's units** (`fab serve`/`issues`/`logins check`/`report daily --install`): persistent, enabled, on the code the tick moves.

## 2. Slots and disk

- **Builder installs follow the dispatcher:** a run's start fetches origin
  in `FAB_HOME/install` under `FAB_HOME/install.lock` (waiting up to 60 s)
  and moves an ancestor install to the running dispatcher's commit,
  detached. Under the same lock, `FAB_HOME/install.pinned` is checked
  before the fetch: when it exists, sync does nothing and notes
  `install pinned` on stderr. A person or replay setup creates and removes
  the pin; fab does neither. An install at that commit, ahead or diverged
  stays; sync failures only note stderr and never fail a start. Dispatcher hosts are
  skipped (docs/design/tick.md, 3). This updates the fab commands on
  the builder's PATH without changing the links, worktrees, slots or units.
  Long-running queue and after-landing services still need
  `bin/install.sh HOST` to update and restart them.

- **Measured (hetzner6, 10-30 20:00Z):** eight slots of 5-39 GB each; cargo's
  incremental data is 50-90% of every slot, stale test executables up to
  14 GB, everything else 2-4 GB.
- **The sweep ends every task:** when a slot's run ends, `fab slot sweep`
  removes its incremental data and the test executables the run did not
  write. The next task's base differs anyway, so little is lost: the edited
  crates compile once without incremental help. A swept slot holds about
  4 GB. The slot bound is 25 GB: a whole-workspace clippy and test build
  from a swept slot peaked at 25 GB, 19 GB of it test executables and 3 GB
  incremental data (hetzner6, 10-30 20:18Z, kache warm).
- **The builder's budget:** disk = kache cap + slots x slot bound + headroom
  (5-10 GB), and one slot bound more on a gate for the queue's target, which
  each batch sweeps as a slot's is. hetzner6: 50 + 8 x 25 + 10 = 260 of 305
  GB, the rest for QA boxes, archives and the system. `fab hosts check`
  computes it from `fab/hosts.toml`.
- **Live overrides, by hand:** `FAB_HOME/hosts.local.toml`, never in git,
  holds tables named after hosts of `fab/hosts.toml` with the keys to change
  (`roles`, `places`, `builds`, `slots`, the disk figures; never `ssh` or
  `hostname`). Every reader of the machines applies the file of the machine
  it runs on: the dispatcher's on hel8 (`places`, `roles`: from the next
  tick), heavy's on a builder (`builds`, `headroom_gb`: from its next
  command), `fab queue install`'s at a deploy (`roles`). Scaling hetzner8's
  builds down for the queue is `[hetzner8]` with `places` on hel8 and
  `builds` on hetzner8; the running work drains. A bad file fails the tick
  and `fab hosts check` (which lists the overrides in force), and heavy
  reports it and builds on the file as it is. A lasting change goes into
  `fab/hosts.toml`.
- **Claims are the builder's:** `slots/<n>.claim` is created exclusively and
  holds the run, task and time. `fab slot claim` and `fab slot release` run on
  the builder (over ssh from the dispatcher). A claim whose run unit is gone is
  stale, and the dispatcher releases it.
- **Admission waits, it does not refuse:** before a build, `heavy` needs the
  headroom plus a build allowance free. Short of it, it reclaims and waits
  (checking every 30 s, reclaiming again) up to 20 minutes, then exits 75. A
  run that exits 75 reports `Infra: disk`, and the dispatcher requeues it.
- **Reclaim takes from idle slots only:** unclaimed slots, least recently
  released first; first their incremental data and stale executables, then
  the whole target (kache refills it). A claimed slot is touched only by its
  own run's sweep.
- **Lanes are flocks:** the build lane is `builds` lock files, the gate lane
  one; a holder that dies frees its place, so heavy needs no ledger or
  reconciler. The command runs in a systemd user scope with its lane's CPU
  weight (gate 10000, build 1000). Each command appends its lane and disk
  waits to `FAB_HOME/heavy.jsonl` on its machine, the metrics' source.
- **One floor:** the headroom. The current tools' separate floors (45, 40 and
  80 GB) go when `heavy` moves here.

## 3. Logins

Replaces the agents repository's `tools/qa/logins` (QA's held logins) and
the unlanded `agents-logins` of `deploy/logins-pool-1b` (the machines'
sign-ins, director decisions 0015 and 0017). The user, 10-31: one custody
for both, recorded in the log; 4 Claude and 3 Codex subscriptions, every
login that still works reused across them before more are signed in.

- **One shelf, on hel8:** `~/src/fabrig/logins/shelf/<id>/` (0700), one
  entry per login, holding it under its kind's name. The kinds are `codex`
  (`~/.codex/auth.json`) and `claude` (`~/.claude/.credentials.json`), lent
  to a machine at that path, and QA's `chatgpt` (temper's ChatGPT record,
  a live run's `TEMPER_LIVE_ACCOUNT`), `claude-box` (a Claude Code
  directory, `TEMPER_LIVE_CLAUDE`) and `github` (temper's GitHub
  conformance fixtures, `TEMPER_LIVE_GITHUB_FIXTURES`: the probe App's
  `app.json` and `app.pem` and a `person-<owner>.token` per owner, none
  of which refreshes), lent to a run at a path of its own. `smith-live`
  (smith's live root, `SMITH_LIVE`: `config/smith/config.toml`, which names
  the root absolutely, `host-id`, `tokens/chatgpt` signed in by
  `smith login chatgpt`, and `programs/claude`) is a directory lent at
  `~/.local/state/smith-live`. A kind whose files name their own path has
  a `fixed` path and is lent only there, so one root serves one run at a
  time on any builder. An id is `<kind>-<n>`.
- **Custody is the log:** `login.added` (id, kind, origin, sha),
  `login.lent` (id, holder, host, at, sha), `login.returned` (id, sha),
  `login.checked` (id, email, plan, used, resets, error, limit_names,
  limit_used, limit_resets) and
  `login.retired` (id, reason). `fab.logins.fold` derives each login's
  holder; the dispatcher's machine is the only writer, under the shelf's
  flock.
- **Copied out, copied back:** both products refresh their tokens, so the
  copy last used is the true one. A lent login's shelf copy is a
  placeholder until `fab logins return` copies the lent copy back, checks
  its digest on both ends, and removes it where it was only if it has not
  changed meanwhile (its user must have stopped). Lending checks the shelf
  copy against the last returned digest, installs it only where nothing
  is, and checks it again there. tar, ssh and sha256sum move and hash the
  bytes; Python never holds them and nothing prints them.
- **A machine's logins:** `fab logins capture HOST KIND` takes a machine's
  current sign-in onto the shelf, still lent to it (decision 0017's
  "bound"); `--free --path P` takes one whose source is used no more (QA's
  custody holds it, its machine is gone). `fab logins swap HOST ID` gives
  back the machine's login of that kind and lends ID; `fab logins list`
  names each role's missing logins (a dispatcher or builder needs both
  kinds). Lending a `claude` login to a machine also drops the account
  Claude Code cached in `~/.claude.json`: it reports, and keeps, the
  previous login's until none is cached (11-01: three swapped builders
  said gmail until it was dropped).
- **A run's logins:** `fab logins borrow KIND HOST [--path P] --holder RUN`
  lends the free login of that kind with the lowest number and prints its
  id; `--path` may be omitted for a kind with a fixed path. Builders reach
  the shelf by ssh to hel8 (the user, 11-01: custody stays central). `fab after-landing run --live` adds the live pairs of
  `fab.after_landing.LIVE`: only `live-skein`. `live-temper` is out (11-01):
  all its live stories are ignored owner-run sittings, and since fabrig
  eb6c40aaf those binaries have no harness unit tests; nextest exits 4
  (no tests to run), faulting the pair and holding the cursor (after-landing.md 2). It comes
  back only once the user decides which ignored stories, if any, should run
  with `--run-ignored`. Borrowing and the `chatgpt` record / `claude-box`
  directory kinds remain supported and tested. `live-smith` is
  out (11-01: all 17 of its tests red at once on hetzner8): besides
  `SMITH_LIVE_CLAUDE` its tests need `SMITH_LIVE`, a whole live root
  (`config/smith/config.toml`, `host-id`, `tokens/chatgpt`, a ChatGPT
  record of smith's own made by `smith login chatgpt`, and
  `programs/claude`), held by the `smith-live` kind; its return to
  `fab.after_landing.LIVE` waits for the signed-in root's capture. Each
  pair borrows its logins, lent to the builder at the kind's fixed path or
  under its run directory for holder `after-landing/<tip>/<pair>`, runs
  with the variables naming them, and returns them when it ends; a pair
  short of a login faults, and a login that cannot be returned stays lent
  to its run with an `error` record. `live-skein` borrows a `codex` and a
  `claude` login (`SKEIN_TEST_LIVE_OPENAI_AUTH`,
  `SKEIN_TEST_LIVE_ANTHROPIC_CREDENTIALS`: its tests read a login's file
  instead of tokens in their environment, the user, 11-01, fabrig
  `logins/skein-live`). They read the access token and never refresh it,
  so fab refreshes each first where it was lent (`fab logins account KIND
  --home DIR --validate`); one that does not refresh faults the pair.
  The after-landing unit runs `--live` (the user, 11-01), on the cheapest
  models: temper's and smith's live tests pick `gpt-6-luna` and
  `claude-haiku-5-5` themselves, and `fab.after_landing.CHEAP` sets
  skein's `SKEIN_TEST_LIVE_*_MODEL` to the same.
- **Checks by the products themselves:** `fab logins check ID` asks Codex's
  app-server (`account/read`, `account/rateLimits/read`: the account, the
  plan and every limit) or `claude auth status` followed by local `/usage`. A lent
  machine login is checked in place, on its machine; a free one is lent to
  hel8 in a private directory and returned. Every check makes a real
  request (a Claude call of a few tokens; Codex refreshes its token), so an
  expired login says so and a swapped Claude login does not report the
  account its predecessor left cached (11-01: three swapped builders said
  gmail until their first call). The weekly percent is the signal for a swap.
  `account()` returns `limits`, dictionaries of `name`, `used` (percent) and
  `resets` (Unix seconds or null). Codex reads every bucket in
  `rateLimitsByLimitId`, sorted by key, or `rateLimits` alone, and each
  bucket's primary and secondary windows. Duration labels are `5 h` (300
  minutes), `week` (10080), otherwise whole days, whole hours or minutes;
  an unknown duration is `?`. A bucket whose `limitId` is not `codex`
  prefixes `other `, never its backend display name. The shelf's existing
  `used` and `resets` remain Codex's weekly window (the primary window for
  older responses without a labelled week).
  Claude runs `claude -p /usage --output-format json --no-session-persistence
  --strict-mcp-config --tools "" --model claude-haiku-5-5 --settings
  '{"disableAllHooks": true}'` with `TZ=UTC`. It accepts only a local
  `usage` command with zero turns and zero cost. `Current` lines yield each
  limit; `session` becomes `5 h`, `week (all models)` becomes `week`, other
  names stay as written, and Fable lines are dropped. English resets with
  an optional month/day and UTC suffix use the next matching date/time,
  allowing the previous hour as the old renderer did. A failed or
  model-answered `/usage` leaves limits empty and keeps the account.
  `Shelf.check` records limits as three parallel scalar lists:
  `limit_names`, `limit_used` and `limit_resets`, of equal length and order;
  unknown use or reset is null. It never puts dictionaries in log fields.
- **Check the shelf:** `fab logins check --all` checks each login whose kind
  has a check, sequentially. Custody refusals (including a run's login and
  retired logins) print `skipped`; account failures record `login.checked`
  with `error` and do not stop the remaining checks. Bulk checking exits 0;
  explicit ids retain their failure exit status. A 30-minute timer on hel8
  is deployed by hand, outside this change.
- **Left out:** the old tools' pending journals and backups, QA's waiting
  queue, reservations and admission caps (the dispatcher decides who gets a
  login, as it does places), and checks of `chatgpt`, `github` and
  `smith-live` logins: their live runs show whether they work.

## 4. The dispatcher's own units

hel8 runs four services besides the tick (tick.md 6): the status page,
the forge issue loop, the login checks and the daily reports. Until 11-01
each was a transient unit started by hand (or, for the reports, nothing);
each is now a persistent systemd user unit that fab writes, on one pattern
(the user, 11-01, via the director: lab.html item 3).

| Command | Units | Runs | Schedule and limits |
|---|---|---|---|
| `fab serve --install` | `fab-status.service` | `fab serve --port 8370 --bind 127.0.0.1` (reports.md 4) | always; `Restart=on-failure`, `RestartSec=5`; exit 75 restarts it on new code |
| `fab issues --install` | `fab-issues.timer`, `fab-issues.service` | `fab issues sync` (channel.md 3) | `OnCalendar=*:1/2`; `TimeoutStartSec=infinity` (each reply call keeps its own limit, `calls.TIMEOUT`) |
| `fab logins check --install` | `fab-logins-check.timer`, `fab-logins-check.service` | `fab logins check --all` (3); `StandardOutput=null`, `StandardError=journal` (its stdout names emails) | `OnCalendar=*:5/30`; `TimeoutStartSec=1800` |
| `fab report daily --install` | `fab-report-daily.timer`, `fab-report-daily.service` | `fab report daily` with no plan dir (below) | `OnCalendar=*-*-* 00:33:00 UTC`, `Persistent=true`; `TimeoutStartSec=1800` |

- **The installer:** `fab/units.py` gains a second installer for these
  units, `install_units(files, *, primary, restartable, role="dispatcher",
  sh, directory, known)`, and a pure text function per unit; `Service`,
  `text` and `install` and their callers (the queue, after-landing) are
  unchanged. All the texts and the installer live in `fab/units.py`; each
  command's `--install` calls them. `files` maps unit names to texts, `primary` is the unit to
  enable (the timer, or `fab-status.service`), `restartable` is true only
  for `fab-status.service`. The role is read through `fab.hosts.load()`
  (`hosts.local.toml` applied) and `fab.hosts.this`.
- **The texts,** sections in this order, one blank line between them,
  ending with a newline, as `wake.units` writes them; `<home>` is FAB_HOME
  and `<install>` is `<home>/install`, both absolute; a path or argument
  holding a newline, `%`, `$`, `"` or a backslash is a ValueError, as in
  `units.text`:
  - `fab-status.service`: `[Unit]` `Description=fab: the public status
    page`; `[Service]` `Environment=FAB_HOME=<home>`, `ExecStart=/usr/bin/bash
    -lc "exec <install>/bin/fab serve --port 8370 --bind 127.0.0.1"`,
    `Restart=on-failure`, `RestartSec=5`, `SuccessExitStatus=75`,
    `RestartForceExitStatus=75`; `[Install]` `WantedBy=default.target`.
  - each timer's service: `[Unit]` `Description=fab: <what>`, `<what>`
    being `the user's questions as forge issues`, `the logins' checks` or
    `yesterday's reports`; `[Service]`
    `Type=oneshot`, `Environment=FAB_HOME=<home>`, `KillSignal=SIGINT`,
    `TimeoutStartSec=<t>`, the login check's two output lines,
    `ExecStart=/usr/bin/bash -lc "exec <install>/bin/fab <command>"`; no
    `[Install]`. `KillSignal=SIGINT` makes a timeout, stop or shutdown run
    the command's cleanup (a login check gives back its lent login).
  - each timer: `[Unit]` `Description=fab: <what>, <when>`, `<when>` being
    `every 2 minutes`, `at :05 and :35` or `daily at 00:33 UTC`; `[Timer]`
    `OnCalendar=<as in the table>`, `Persistent=true` for the report only,
    `Unit=<its service>`; `[Install]` `WantedBy=timers.target`.
- **Following main:** no unit fetches. The tick (and a deploy) moves
  `FAB_HOME/install` to `origin/main` (every event tick and at least every
  10 minutes, tick.md 6); a timer's run uses the install as it finds it.
  The timers sit off the backstop's minutes (`*:1/2`, 00:33) so they rarely
  start beside it. `fab-status.service` runs for days: `fab serve` takes its
  install as the running package's checkout
  (`Path(__file__).resolve().parent.parent`, as `fab.forge.sync` finds
  it), reads `git -C <it> rev-parse HEAD` once before serving, and a daemon
  thread rereads it every 60 seconds; a different hash calls
  `server.shutdown()` and `main` returns 75 once `serve_forever` returns,
  so systemd starts it again on the new code. An unreadable HEAD, at start
  or later, is never a change. The reader and the interval are parameters
  (a test runs in under a second); the thread prints nothing.
- **An install, in order, all through `fab.sh.run`:**
  1. Without the role: no unit file present, nothing; a file present,
     `disable` then `stop --no-block` the primary unit, as `units.install`
     does. It prints as the CLI bullet says. Done.
  2. Transient units first: query `systemctl --user show
     --property=Transient,ActiveState --value <unit>` for every one of its
     unit names before stopping any. When a timer's service is transient
     and its ActiveState is neither `inactive` nor `failed`, the install
     refuses with `<unit> is running; rerun when it ends` (exit 1, nothing
     stopped or written). Otherwise each transient unit, timer before
     service, gets `stop` then `reset-failed` (both check=False). A unit
     that is not transient is never stopped.
  3. Paused: the primary unit's file existed before this run and
     `systemctl --user is-enabled <primary>` prints `disabled` (a pause by
     hand, `disable --now`). Its files are still written and
     `daemon-reload` runs; nothing is enabled, started or restarted, and it
     prints as the CLI bullet says.
  4. Each file through `fab.atomic.write`; then `daemon-reload`; then
     `enable --now <primary>`.
  5. Changed text: only `fab-status.service` is ever restarted, when its
     file existed with other text (`restart fab-status.service`). A timer
     whose text changed is restarted (`restart <timer>`), which does not
     start its service (the report's `Persistent=true` may run a missed
     day at once; harmless, daily keeps what exists). A timer's service is never started, stopped or
     restarted by an install; its next run reads the new text. Unchanged
     text restarts nothing.
  6. Linger: `loginctl show-user <uid> --property=Linger --value`
     (check=False); any output but `yes`, or a failure, prints `fab
     <command>: linger is off for <user>: the units start at boot only
     after loginctl enable-linger` on stderr and the install still
     succeeds.
- **CLI:** `fab serve --install` takes no other option (`--port` or
  `--bind` with it: usage error, exit 2). `fab issues --install` takes no
  command (the command becomes optional; neither given: exit 2). `fab logins
  check --install` takes no ids and no `--all`, and is handled before the
  shelf is opened. `fab report daily --install` takes no plan dirs. Each
  prints one line per path written, then `enabled <primary>`, or
  `<primary> left disabled` when paused; without the role it prints only
  `<primary>: no dispatcher role here: nothing to do` or `<primary>: no
  dispatcher role here: disabled and stopping`; it exits 0; an OSError, ValueError or `fab.sh.Failed` prints
  `fab <command>: <error on one line>` on stderr and exits 1, as `fab
  wake` does.
- **`fab report daily` with no plan dir** (now nargs `*`) takes
  `fab.channel.plan_dirs()` (FAB_HOME/plans, tick.md 5) and skips a
  directory without `plan.toml` (a plan being cut) and a plan with
  `retired = true`, as the tick does, printing `<dir> skipped` for each;
  with plan dirs given, exactly those, as today.
- **Reply calls** (channel.md 3) start in the clone holding the running
  package, now `FAB_HOME/install`: their worktrees and `calls/reply-*`
  branches live there.
- **Deployment:** ops runs the four commands on hel8 once they land, and
  adds them to `bin/install.sh` after `fab after-landing install` (they do
  nothing on machines without the role). The hand-made clones
  `FAB_HOME/serve-install` and `FAB_HOME/issues-install` and the scripts
  `FAB_HOME/bin/start-{status,issues,logins-check}.sh` are then unused;
  `issues-install` is removed only when no reply call is in flight.

## 5. Later

- Elastic builders from `fab hosts check`'s numbers.
- Logins (3), next: after-landing `--live` run on the
  queue's machine as well as builders (the user, 10-31); `tools/qa/logins`
  retired (QA's six logins are on the shelf since 11-01, held there by
  `fab/migrate`). Then a new builder lent its logins when it joins and
  returned when it goes, and swaps proposed from `login.checked`'s weekly
  percent.
- `live-smith` back in `fab.after_landing.LIVE` (`SMITH_LIVE` from
  `smith-live`) once the signed-in root is captured, its pair borrowing
  with no `--path` so the root is lent at its fixed path (3); landed only
  then, or every after-landing run faults the pair.
