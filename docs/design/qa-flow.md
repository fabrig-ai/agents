# QA after landing

Provisional, 2026-10-26, proposed with the user; revised 2026-10-27
(section 11). This is how a change that
landed gets tested by an agent that drives the product the way its users'
agents do:
- the landing's owner marks the commit;
- the director chooses which marked commits get a pass;
- a service starts each pass on a batch of chosen commits;
- the pass reports its findings, and what in it could be automated.

It starts as light as it can (the user, 10-26): no setup helpers
beyond the product's own commands, and tools added only as the passes'
reports show the need. It settles the roles' open question of who
starts QA and who judges its findings ([roles/README.md](../../roles/README.md)
2), except for the triage itself (section 6). It does not use qa's lab,
whose future is open (section 9).

## 1. In one page

- **The owner marks** a landing commit worth testing with a `QA:`
  trailer: one line on what a user can now do (section 2).
- **The director chooses** which marked commits get a pass and which
  wait in a backlog. It works from the user's priorities and the
  capacity and spend at hand, and records each choice with `qa decide`
  (section 3).
- **A service starts the passes by itself.** When a slot is free and
  chosen commits wait, it starts one pass over all of them, on the
  newest `main` that after landing has cleared. Commits chosen while a
  pass runs batch into the next one (section 4).
- **A pass is a Codex session.** It builds the product at that `main`,
  sets up a deployment with the product's own commands, and works with
  it as its users' agents do: the product's tool for the product
  (`temper ctl`, for temper), and tools of its own for the systems the
  product works with (`curl`, for temper's forges). The product's
  binding, its `docs/design/qa.md`, says how. For each commit it tests
  the happy path and two to four tricky cases it picks, writing down
  what it expects before running each (section 4).
- **Its report** gives each case's outcome, each finding with the
  commands that reproduce it, and what in the pass a helper could
  automate (section 5).
- **Findings wait in a queue** until they are triaged: routed to an
  owner, put in the backlog, or dropped. Who triages is open; for now,
  the director (section 6).
- **One tool, `qa`,** in `scripts/devel/`, which names no product. Its
  record is three kinds of files in `records/qa/` (section 7).
- **Rungs, from fakes to real backends:** a product's binding names its
  rungs, its fakes first, and the held logins each takes. The director
  opens a repository's rung with `qa rung` once the rung below has run
  clean, and its passes run there; the fakes stay its first rung (the
  user, 10-26: passes climb temper's rungs to real backends now)
  (section 10).
- **A held login has one holder at a time.** A subscription's login
  refreshes, so it is never copied: it rests on one machine, where the
  passes run, and a second tool, `logins`, keeps its custody. QA's
  passes and the director's other live runs take it in turn, and it is
  free again only once it is back (section 10).
- **A pass's evidence is kept** (the user, 10-27): at its end, the
  service copies an allowlist of its scratch (its brief, plan, notes and
  report, the helpers it wrote, the outputs it captured) to the branch
  `evidence` of the private qa repository, and the report's front
  matter names the commit. A scan by name and shape refuses a copy that
  holds a secret, whole, and says which file; nothing is trimmed. The
  ladder's focused walks keep theirs the same way (section 11).

## 2. The marker

- **A trailer** in the commit's message, `QA: <what a user can now do,
  or what changed for them>`: one line of at most 160 characters,
  which the pass takes as its starting point.
- **The landing's owner decides** whether a change is one a user meets
  through the product's tool. If it is, the owner writes the trailer
  into the landing's commit, or has its landing task write it. A set's
  landing marks each commit that carries such a change; often that is
  one.
- **Nothing else is eligible:** an unmarked commit never gets a pass.
  The trailer is written once, in git. The candidates are read from it
  each time (section 3), never copied.

## 3. Choosing

- **`qa candidates [REPO]`** lists the marked commits on origin's
  `main` that have no decision yet, oldest first, each with its
  repository, short commit, subject and trailer.
- **The director decides** at its check (director.md 7), from:
  - the user's QA priorities, in `director/direction.md`;
  - capacity: the passes running and the commits waiting for one
    (`qa passes`);
  - spend: recent passes' tokens and wall time (section 7).
- **`qa decide REPO COMMIT... run|backlog [--why TEXT]`** records the
  choice:
  - `run` sends the commits to the next pass;
  - `backlog` keeps them for later, and `qa backlog` lists them.

  The latest decision on a commit wins, until a pass has taken it. A
  decision after that chooses it again, for a pass that was capped or
  failed: a commit's state is its latest event, decision or pass.

## 4. The pass

- **The service, `qa watch`,** is a user unit on the machine the
  director names, by writing its own address in
  `~/.config/agents-qa/director` there, as for after landing's runner.
  It checks every five minutes, and at once when a pass ends: its loop
  is the waiter of the mailbox `qa-watch`, where each pass's `codex-run`
  posts its end. It starts a pass when all of these hold:
  - a slot is free: one, for now (the settings' `slots`);
  - commits chosen to run are in no pass;
  - the newest `main` that after landing has cleared holds the oldest
    of those commits: `landings cleared REPO`, the newest run of the
    repository's tier whose verdicts are all cleared
    ([landing-flow.md](landing-flow.md) 4, step 8). Reds standing from
    older landings don't hold it back. A pass then spends no tokens
    finding again what the tier already showed;
  - the held logins of the repository's rung are granted to the
    service, `logins take` (section 10.3).

  The pass takes every chosen commit that `main` holds, oldest first,
  up to the settings' `batch` (five, for now). The rest wait for the
  next pass. A pass covers one repository: chosen commits of several
  make a pass each, in turn, the repository with the oldest decision
  first.
- **Its checkout:** one clone per repository on that machine,
  `tmp/qa/repos/<repo>/`, kept with its target as after landing's are.
  The service checks it out, detached, at the pass's `main`. The pass
  builds through `heavy` at `HEAVY_CLASS=background`. The service
  deletes a pass's scratch directory 7 days after it ends, once its
  evidence is kept or refused (section 11.4).
- **The session:** Codex at `codex-run`'s defaults, started by
  `codex-run task` with a brief the service writes. The brief says to
  read `roles/qa.md`, then the product's binding, `docs/design/qa.md`
  in its repository, and names the commits, the `main`, the worktree,
  a scratch directory in `tmp/qa/<pass>/`, the cap and the report's
  path, and the rung with its held logins (section 10.3). Its wall time
  has a cap, the user's to set (proposed: two hours), counted from its
  start, once it holds its logins. Its tokens are recorded, not capped.
- **The product's binding** is the product's: whom a pass plays, the
  deployment and its rungs, the hands it holds on the product and on
  its backends, and what makes a finding there. This document and the
  role name no product; the binding is where a product says what they
  leave to it.
- **What it does:**
  1. Reads each commit's diff and the designs the commit touches.
  2. Writes its plan in the scratch directory before running anything.
     For each commit: the happy path, then two to four tricky cases it
     picks (errors, retries, odd input, a thing done twice or two at
     once), each with the outcome it expects.
  3. Builds the product and sets up a deployment with the product's
     own commands, as its binding says: for temper, `temper box` on a
     scratch directory, `temper ctl`'s sign-in, and the forge's hands
     from the files the box names. Cases that don't disturb each other
     share one deployment. A case that would disturb others gets a
     fresh one.
  4. Works each case as the product's users' agents do: the product
     through its tool (for temper, `temper ctl`, whose `help` is
     temper's guide for agents), its backends through tools of the
     pass's own (the user, 10-26: the product is agnostic about how its
     users reach other systems, and our passes choose `curl`). It checks
     each outcome on both sides. A finding is the product not saying
     where to look, the two disagreeing, the product stale past its
     bound, a guide that doesn't get the pass there, or the product's
     words wrong; having read the backend is none. It never acts on the
     product any other way: not through its store, its HTTP API, or a
     fake's internals.
  5. Writes its report (section 5).
- **Its transcript is Codex's own:** the session's rollout records
  every command and its output, so no wrapper logs the tool's calls.
- **Backends:** the repository's open rung, named in the binding, the
  director opening one for the brief to name (section 10.1). A rung's
  held logins are the service's from before the pass starts until
  after it ends, and the session's give-back returns them whatever
  ends it (section 10.3).

## 5. The report

`records/qa/passes/<pass>.md`, at most 8 KB, `<pass>` its start and
repository (`20261026-0915-temper`). The service writes the front
matter: repository, `main`, commits, rung, machine, model, effort,
started, ended, wall time, tokens, the outcome (`done`, `capped` or
`failed`), and `evidence`, the commit that keeps its evidence (section
11.4). It commits the file twice: at the pass's start, `running`,
so that the pass shows in `qa passes` and its commits are taken
wherever the record is read; and at its end, completed, with the body.
A third commit writes `evidence` when its copy was pushed after the
end's. A line of the body that the evidence's scan refuses is withheld
from the record, and said (section 11.4).
The pass writes the body, in [roles/qa.md](../../roles/qa.md) 3's
shape; past the cap, the service cuts it and says so:

- **Cases:** for each commit, one line per case: what it tried, what it
  expected, what it saw, and `ok` or a finding's number.
- **Findings,** numbered within the pass. Each gives what is wrong, the
  commands that reproduce it from a fresh deployment, what it expected
  and what it saw, and the commit it most likely comes from.
- **Automation:** a short list of what the pass did by hand that a
  helper would make faster or surer: setup it repeated, waits it wrote,
  checks it scripted. Each item gives the time it took. These lists
  decide which helpers get built (the user, 10-26).
- **Blocked:** what it could not test, and why.

When a pass is capped or ends without its report, its outcome says so,
and the service posts the director.

## 6. Findings: the queue and its triage

- **The queue** is every finding in a committed report that has no
  triage line yet. `qa findings` lists them, oldest first.
- **`qa triage PASS N owner ADDRESS|backlog|drop [--why TEXT]`**
  routes one finding by appending its line:
  - an owner's finding goes to that owner by post, naming the report;
  - a backlog one gets an entry in `director/backlog.md` that points
    at the report.
- **The service posts the director** one line when it commits a report
  that has findings.
- **Who triages is open** (the user, 10-26). Until that is settled, the
  director does it at its check, by director.md 6: a finding on
  v0.1.0's happy path goes to the owner of what it names, or to its
  designer; any other goes to the backlog. Two options for later:
  - a Codex session per pass, which proposes each finding's route and
    any duplicates for the director to confirm;
  - a standing owner for QA's findings.

## 7. The tool and the record

`scripts/devel/qa` comes with its fixture. It names no product, and
takes a repository's name where it needs one.

| Command | What it does |
|---|---|
| `qa candidates [REPO]` | lists marked commits that have no decision |
| `qa decide REPO COMMIT... run\|backlog [--why]` | records a choice |
| `qa backlog [REPO]` | lists the commits kept for later |
| `qa passes [--running]` | lists passes, with their commits, outcome, wall time and tokens |
| `qa findings` | lists the queue |
| `qa triage PASS N ROUTE [--why]` | routes one finding |
| `qa rung REPO [RUNG [--login NAME]... [--why]]` | opens a rung, or shows the open one (section 10.1) |
| `qa watch` | runs the service (section 4) |
| `qa keep --check DIRECTORY` | scans what a copy of DIRECTORY would hold, and writes nothing (section 11.5) |
| `qa keep --walk NAME DIRECTORY` | keeps a focused walk's evidence (section 11.5) |
| `qa deploy DIRECTORY NAME -- COMMAND...` | starts a pass's deployment in a unit of its own, stopped by its give-back (section 10.5) |

The record is committed with `record commit`, and its rows are in
[records.md](records.md) 3's table:

| Path | Writer | Written | Holds |
|---|---|---|---|
| `qa/decisions.md` | the director, through `qa decide` | appended | one item per choice: `- <time> <repo> <commit> run\|backlog <why>` |
| `qa/passes/<pass>.md` | the pass, and `qa watch` for the front matter | at the pass's start and end | the report (section 5) |
| `qa/triage.md` | the triager, through `qa triage` | appended | one item per finding: `- <time> <pass> <n> <route> <why>`, the route an owner's address, `backlog` or `drop` |
| `qa/rungs.md` | the director, through `qa rung` | appended | one item per opening: `- <time> <repo> <rung> <logins> <why>`, the logins comma-separated, or `-` |

Times are UTC to the second, commits full SHAs. The settings are the
kit's: the machine, named as section 4 says, and `machine.env`'s
`QA_SLOTS` (1), `QA_BATCH` (5), `QA_CAP_MINUTES` (120),
`QA_INTERVAL_SECONDS` (300) and `QA_EVIDENCE_KIB` (2048, section 11.1).

## 8. When it runs

- `owners.md` gains one line: the trailer (section 2).
- `director.md` gains a line each for choosing at its check (section
  3) and for triage (section 6). Its open question on QA leaves
  `roles/README.md`.
- `roles/qa.md`, the pass's role, is short: section 4's steps and
  section 5's report.
- `setup` installs `qa watch` on the machine the director names, as
  the user unit `agents-qa-watch.service`, and links `logins`.
- `director.md` gains a line for the rungs and the held logins at its
  check: opening a rung, and reading `logins list` for saturation
  (section 10).
- `director.md` gains a line for the evidence: a focused walk kept with
  `qa keep --walk` at its end post, and a refused copy mended by name
  and line, or left refused (section 11.4, 11.5). `roles/qa.md` gains
  its scratch's layout and the check before its report's last write
  (section 11.1, 11.5).

## 9. Open

- **Triage:** who works the findings queue (section 6).
- **Real backends' spend:** the subscriptions' use is measured by
  `logins list`'s last day; whether passes get a cap of their own on it
  is the user's.
- **qa's lab:** what becomes of it (the user, 10-26).
- **The machine:** settled, where the held logins rest (section 10.2).
- **Evidence that isn't text** (a page's screenshot): the scan can't
  read it, so it refuses it (section 11.2). Whether a pass that
  captures pages keeps them, and how, waits for one that does.
- **The branch's growth:** about 1 MB a day packed, at ten passes a
  day of 200 to 400 KB each, 30 to 90 KB compressed (measured 10-27).
  Whether old directories ever leave it, by a new branch and never a
  rewrite, is open.

## 10. Real backends: rungs and the held logins

The user, 10-26: QA after landing climbs the product's rungs to real
backends now, its passes taking the held login in turn with the
director's other live runs, one at a time; if that saturates the login,
the director says so to the user.

### 10.1 Rungs

- **The binding names the rungs,** lowest first: the product's fakes,
  then each real backend in turn, and for each the held logins a pass
  takes, by their names in `logins` (temper's `docs/design/qa.md` 3:
  fakes; a real model, with ChatGPT's login; GitHub).
- **The director opens a rung** for a repository: `qa rung REPO RUNG
  [--login NAME]... [--why TEXT]`, once the rung below has run clean,
  as the binding says, which `qa passes` shows, each pass with its
  rung. The latest opening holds every pass started after it; going
  back down is an opening too, when a rung's findings must be fixed
  first or its login is short. `qa rung REPO` shows the open one.
- **A repository with no opening** runs on its binding's first rung,
  with no login.
- **The fakes stay** the first rung: what a fake does better (no
  account, no wait, no spend) holds while the rungs above wait.

### 10.2 The held logins

- **A held login** is a refreshing credential exported from a product
  (a subscription's sign-in): it has one holder at a time, is never
  copied or read, moves into a deployment by the product's import and
  back by its export before the deployment stops. A program's own login,
  a signed-in configuration directory of the program's (Claude Code's),
  is one too, but never moves: the deployment uses it in place, as the
  product's binding says (temper's `protocol/credentials.md`, 3), and
  stops using it when it stops. A key that doesn't refresh (a GitHub
  App's) is not one: the director places it, as director.md 10 says.
- **It rests on one machine,** at `tmp/logins/NAME/login`, private,
  moved there once by the director with `logins add NAME PATH`, a
  rename, never a copy: a file, or a program's configuration
  directory. QA's passes run on that machine: `qa watch` is
  installed there (section 4).
- **One holder at a time, in turn:** `logins take NAME --as HOLDER`
  grants it when it is at rest and no taker waits ahead of HOLDER;
  otherwise it exits 1 and HOLDER keeps its place in the queue while it
  asks again within 15 minutes. `--wait SECONDS` waits, and exits 1
  past it. Every change is made under one lock, and `add` refuses a
  name that has a login or a holder.
- **Free only once back:** `logins give NAME --as HOLDER` checks, by
  `stat` alone, that the login is at its resting path, and only then
  frees it: a private (0600), non-empty regular file, or a private
  (0700) directory with at least one entry, each the user's own and no
  link. A directory is checked through one descriptor opened without
  following a link, so that a link swapped in after the check is never
  taken for it. Nothing inside a directory is read or checked: what it
  holds is the program's. A login not back
  stays held by its holder, so that one left inside a dead deployment
  is never handed on, and shows in `logins list`.
- **Every live run takes it:** QA's passes through the service
  (10.3); the director's other runs on it (a ladder's rung, a focused
  story) by `logins take` before their start and `logins give` after
  their end, each started with `codex-run task --on-stop` and a brief
  that writes the give-back file as 10.3 says. The director is their
  holder: it gives at the run's end post, and a give refused is its own
  to recover, as 10.3's last point says.
- **Saturation shows in `logins list`:** each login's holder and since
  when, its waiters, and its last 24 hours: time held, takes, longest
  wait. The director reads it at its check; a login held most of the
  day while passes wait is saturated, and the director tells the user.

### 10.3 A pass on a rung with held logins

- **The service takes before it starts:** at a check where a pass
  could start (section 4), it takes each of the rung's logins as
  holder `qa-watch`, in name order. One refused gives back those
  taken, still at rest, and the pass waits for a later check, its
  commits still chosen, the service's place in the queue kept. A login
  is held from the pass's start, its build and plan included: minutes,
  where a session taking it itself would wait inside its cap.
- **Nothing held without a pass:** at each check the service gives
  back every rung's login it holds that no pass of its own still holds,
  so that a crash between a take and a pass's start strands nothing.
- **The brief names** the rung, each login with its resting path, and
  the give-back file, `give-back` in the pass's scratch directory.
- **The session borrows them:** it moves each login into its
  deployment as the binding says, and at once writes the give-back
  file, an executable that moves each back to its resting path by the
  product's export, safe to run twice (the second export finds the
  file there and sends nothing). A login used in place moves nothing:
  the give-back has nothing to do for it, and the login is back once
  the deployment that used it has stopped. It runs that file itself
  before it stops its deployment, and checks each path by `stat`. It
  never runs `logins`. A stop in the seconds between the import and the
  file is a login lost in its deployment (below).
- **Each deployment is a unit of its own,** started with `qa deploy
  DIRECTORY NAME -- COMMAND...` (10.5): the user unit
  `qa-<pass>-<NAME>`, outside the session's unit, so that it outlives
  the session and a login not back stays where it can still be
  exported. Its stop command (`ExecStop=`) runs the give-back file,
  which systemd runs before it signals the deployment, while the
  deployment can still export; never only after it has exited
  (`ExecStopPost=`), when no export can succeed (pass
  20261027-1202-temper's box unit, 10-27). The file need not exist when
  the unit starts.
- **A failed export leaves the deployment up,** where the session or
  the service decides: the session stops a deployment only once each
  login it moved is back by `stat`, and otherwise leaves it running
  and says so, in its report's first line with the unit's name
  (roles/qa.md 2, step 5); the service stops one only as the last
  bullet says. A stop nobody decided (a person's `systemctl stop`, a
  shutdown) runs the give-back first, as the unit's stop command, but a
  failed export can't hold that stop back: it is the best the unit
  can do, and what it leaves is a login lost in a dead deployment
  (below). So is a deployment that exits by itself or crashes: its stop
  command then runs after it, and exports nothing.
- **A stop gives back too:** the session runs under `codex-run task
  --on-stop` with the give-back file, so that its unit runs the file
  at the cap, a person's stop, a shutdown, or a session that ended with
  its deployment up ([post.md](post.md) 5), while the deployment's own
  unit is still up; the session's stop never stops that unit. At a
  shutdown the two units stop together, and each deployment's own stop
  command is what gives its login back. The give-back is run through
  one wrapper that takes a lock in the scratch directory (10.5), so
  that two stops that run it at once take turns.
- **The service gives after the end,** once the run's unit is
  inactive and its give-back done. A login not back stays the
  service's: the pass's notice to the director names it, the
  deployment's directories and its units, and the service tries the give
  again at each check, so that the login is free as soon as it is back.
  It keeps that pass's scratch until then, past its 7 days.
- **A pass's end, in order,** each step saved in its `pass.json` before
  the next, and each one not done tried again at the next check:
  1. the report and the evidence (section 5, 11.4);
  2. each moved login given back (`logins give`, which frees it once it
     is back at rest);
  3. once every moved login is back, each of the pass's units stopped,
     those `qa deploy` recorded (10.5), and its stop confirmed by
     `systemctl`; a pass that held no login has its units stopped at
     once;
  4. each login used in place given back, only once every unit of the
     pass is confirmed stopped, so that no deployment still uses it
     when it is free;
  5. the notice, which says what is still out: a login not back, a
     unit up or of unknown state.

  A login's kind, moved or in place, is known from its resting path
  when the service takes it (a file is moved, a directory used in
  place, 10.2), and kept in `pass.json` with it. The scratch is never
  deleted while a login is out or a unit of the pass is up or of
  unknown state, past its 7 days.
- **A login lost in a dead deployment** (one that died before its
  export: a crash, a session that stopped its deployment first) is in
  the deployment's state, kept with the pass's scratch. The director
  has it brought back, as a task of its own: the
  deployment restarted on its directories, signed in, the login
  exported to its resting path, as the binding says. The service's
  next check frees it.

### 10.4 The tool

`scripts/devel/logins`, with its fixture, names no product. Its state
is the machine's, in `tmp/logins/NAME/`, private: `login` at rest,
`holder.json` while taken, `waiting.json`, the queue, and `log.tsv`,
one line per `add`, `take` (with its wait) and `give` (with the time
held).

| Command | What it does |
|---|---|
| `logins add NAME PATH` | moves PATH, a file or a program's configuration directory, in as NAME's login, at rest |
| `logins take NAME --as HOLDER [--note TEXT] [--wait SECONDS]` | grants NAME in turn and prints its resting path; exit 1 while another holds it or waits first |
| `logins give NAME --as HOLDER` | frees NAME once its login is back; exit 1, still held, if it isn't |
| `logins list [NAME]` | each login's holder, waiters and last 24 hours |

### 10.5 A deployment's unit

- **`qa deploy DIRECTORY NAME -- COMMAND [ARG]...`** starts COMMAND as
  the transient user unit `qa-<pass>-<NAME>`, `<pass>` DIRECTORY's
  name, and prints the unit's name. DIRECTORY is a pass's scratch
  directory, or a focused walk's, absolute and of the characters a stop
  command may hold (codex-run's rule: no shell, no `$`); NAME is a
  lowercase slug. Before it starts the unit, it appends the unit's name
  to `DIRECTORY/deployments`, which the service reads (10.3), since a
  collected unit leaves no trace in systemd.
- **The unit:**
  - `Type=exec`, COMMAND in the foreground, `KillMode=control-group`;
  - works in DIRECTORY, its output appended to `DIRECTORY/<NAME>.log`;
  - its stop command (`ExecStop=`) is `qa`'s give-back wrapper on
    DIRECTORY: it runs `DIRECTORY/give-back` under a lock,
    `DIRECTORY/give-back.lock`, so that runs take turns; an absent file
    is nothing; a run is bounded, its output and exit appended to
    `DIRECTORY/give-back.log`; and a failure never fails the unit, as
    codex-run runs a stop command (post.md 5);
  - `TimeoutStopSec=` above the wrapper's bound, so that systemd never
    signals the deployment while its export runs;
  - no `ExecStopPost=`;
  - collected once stopped.
- **The session's stop runs the same wrapper:** the service starts the
  session with `--on-stop` on a file that runs it, so that both stops
  take the one lock.
- **It names no product:** COMMAND is the binding's (temper's `temper
  box`, with its flags).
- **Its fixture,** `test-qa`, under a fake systemctl whose stop runs the
  stop command before it ends the process:
  - `qa deploy` records the unit, then hands systemd its name, its
    directory, its log, the wrapper as its stop command, the timeout,
    and no `ExecStopPost=`; an unsafe DIRECTORY or NAME is refused;
  - a deployment that can export only while it is up gets its login
    back when the session is stopped at the cap, and the service stops
    its unit after the give: a stopped pass's login is back;
  - a failed export leaves the unit up and the login held; the notice
    names the unit; once the login is back, the next check gives it and
    stops the unit;
  - two stops that run the wrapper at once take turns;
  - a wrapper past its bound is ended, logged, and the unit still
    stops;
  - a deployment that exited by itself leaves its login out, and the
    notice says so;
  - a stop that `systemctl` fails, or a unit of unknown state, is tried
    again at the next check, and the scratch is kept;
  - a service restarted between steps goes on from the last one saved;
  - a pass with no login has its units stopped at its end;
  - a login used in place is given only after every unit has stopped.

## 11. The evidence, kept

The user, 10-27: at a pass's end, its non-secret evidence goes into the
private qa repository, so that what a pass did outlives its scratch's 7
days. agents alone names qa's paths: the public repositories never do.

### 11.1 What is kept

- **An allowlist** of the pass's scratch directory, and nothing else:
  `brief.md`, `plan.md`, `notes.md`, `report.md` (whole, before the
  record's cut), `scripts/`, the helpers the pass wrote, and `evidence/`,
  the outputs it captured. Any of them may be absent. The deployments,
  the binaries, the give-back file, the service's own files
  (`pass.json`, `post-body`) and everything else stay in the scratch and
  go with it.
- **The pass lays its scratch out for it** ([roles/qa.md](../../roles/qa.md)
  4): captures in `evidence/` and helpers in `scripts/`, as text; what
  holds a secret outside them; a helper that needs a secret reads it by
  its path (`curl -H @FILE`), never with its value in its text.
- **Not the transcript:** Codex's rollout holds every command's output,
  the secrets the pass handled among them, so it stays where Codex keeps
  it on the machine, and the copy's index names its run.
- **A cap,** `QA_EVIDENCE_KIB` (2048), on the bytes of the files a copy
  holds. Past it, the copy leaves out `evidence/` whole, then `scripts/`
  whole, and its index says what it left out, with the files and bytes.
  Documents past the cap alone refuse the copy (11.2). A pass's
  allowlist measured 200 to 400 KB on 10-27.

### 11.2 What never is: the scan

- **One snapshot:** the tool walks the allowlist through descriptors
  that never follow a link (the allowlist's directories too), reads each
  file once, and scans those bytes; the bytes it commits are the bytes
  it scanned, so a file changed after the scan never reaches the copy.
- **Whole or not at all:** one file that fails refuses the copy, and the
  refusal names each failing file with its line and the rule's name,
  never the text that matched. Nothing is trimmed, but for 11.1's cap,
  which says what it left out.
- **By name and shape alone:** the scan is the tool's match, and no
  agent reads a file to check it. A refusal is mended by name and line
  (11.4), and the matched text never reaches an output, a log or a post.
- **Paths are scanned as lines are:** a path whose text a content rule
  below matches refuses the copy, and is named by its directory and its
  place in that directory's sorted listing (`evidence/, entry 17`),
  never by its text. Every other refusal names its path.
- **The rules,** each with its name:
  - `kind`: anything but a regular file: a symbolic link, a file with
    another name (a hard link), a device, a pipe, a socket;
  - `binary`: a file that isn't UTF-8 text, or holds a NUL: a store, a
    database, a binary;
  - `name`: a path any of whose parts holds as a word, case aside and
    between `-`, `_`, `.` or its ends, `cookie`, `cookies`, `password`,
    `passwd`, `secret`, `token`, `credential`, `credentials` or `netrc`;
    or is `auth.json`, `id_rsa`, `id_ed25519`, or `login` with or
    without an extension; or ends in `.header`, `.headers`, `.pem`,
    `.key` or `.env`. So `token-form.html` and `forge-cookies` refuse,
    and `tokens.txt` and `session-status.txt` pass;
  - `key`: a private key's block, or a token's known prefix, as
    `record` refuses them ([records.md](records.md) 2);
  - `jwt`: a signed token's shape, three base64url parts after `eyJ`;
  - `header`: `Authorization` or `Proxy-Authorization` with a scheme
    and a value, or `Cookie` or `Set-Cookie` with a name and a value;
  - `cookie-jar`: a cookie file's line, in Netscape's tab-separated form,
    or its heading;
  - `link`: a URL with a user and a password before its host, or a
    query or fragment parameter named `code`, `token`, `secret`, `key`,
    `password`, `access_token`, `refresh_token`, `id_token`,
    `client_secret` or `signature` with a value: a sign-in or an
    authorization link;
  - `assigned`: `password`, `passwd`, `secret`, `token`, `api_key`,
    `client_secret`, `access_token`, `refresh_token` or `private_key`,
    as a quoted key with a string value (`"token": "…"`), a name with
    `=` and its value (`TOKEN=…`, a form's `password=…`), or a line of
    the name, a colon and a value alone (`password: …`);
  - `user`: curl's `-u` or `--user` with a password after the colon.
- **Placeholders pass, at any length:** a value that is empty, `null`,
  `true` or `false`; a name in capitals (`TOKEN`, `FILE`); `<…>`;
  `$NAME` or `${NAME}`; `@FILE`; `…` or `...`; or a run of `*`. So a
  plan's "`Authorization: token TOKEN`" and a help page's
  `--password-file FILE` pass, and any other value, however short,
  refuses. A rule that refuses a plain capture twice is narrowed in
  the tool, with a fixture story of that capture.
- **What has no shape** (a forge's new token, shown once in its answer
  or its page) the scan can't know: keeping such a capture out of
  `evidence/` is the pass's rule (roles/qa.md 4).

### 11.3 Where

- **The branch `evidence` of the qa repository,** `fabrig-ai/qa`: a
  pass's copy in `passes/<pass>/`, its name the record's; a focused
  walk's in `walks/<name>/` (11.5); and at its root a `README.md` that
  says what it holds and points here. It shares no history with `main`,
  and nothing on `main` reads it.
- **Off `main`, so no gate:** qa's gate proves the lab's code on
  `main`, which a copy never touches, and `land` moves `main` alone. A
  clone of `main` with `--single-branch` never fetches it. tidy keeps it:
  none of its commits has a twin on `main` ([cleanup.md](cleanup.md) 4).
- **A copy is a tree:** its files and its index, and nothing that varies
  between two copies of the same files: the time is the commit's. Two
  copies of the same scratch, unchanged, are the same tree.
- **Only appended:** each copy is one commit that adds its directory on
  the branch's tip, pushed fast-forward; never a force-push, a rewrite
  or a deletion. The first copy makes the branch, with its `README.md`.
  A directory already on the branch with the copy's tree is the copy
  already kept (a push whose answer was lost, a walk kept twice), and
  its commit is the copy's; with another tree, the name is taken, and
  the copy refuses.
- **Each copy's index,** `README.md` in its directory, front matter
  then lines:
  - `kind` (`pass` or `walk`), `name`, `machine`, `source` (the scratch
    directory), `run` (codex-run's id, whose rollout is the transcript,
    or `unknown`), `record` (`qa/passes/<pass>.md`, or `-` for a walk),
    `files` and `bytes`;
  - below it, a line for each tree the cap left out, with its files and
    bytes, or none.
- **The writer is the `qa` tool** on the scratch's machine, in a bare,
  blobless clone of its own, `tmp/qa/repos/qa.git`, that fetches
  `evidence` alone, under a lock beside it, as its product clones are
  kept (section 4). With a temporary index and plumbing it commits the
  copy's tree on `origin/evidence` and pushes, five tries when the
  branch moved, as `record` does (records.md 2), within 2 minutes in
  all: past them the copy waits for the next try. The commit's author
  and committer are the writer's name at its machine (`qa-watch
  <qa-watch@hetzner6>`, the service's), and its subject `qa keep: <kind>
  <name>`; the push goes with the machine's key.

### 11.4 When, and the link

- **The pass's state** (`pass.json`) holds its copy's: `waiting`, with
  the tree once made; `kept`, with its commit; or `refused`, with the
  refusal's digest; and whether the report's front matter names it yet.
  Each step saves it before the next, so a check after a crash goes on
  from the last one saved.
- **At a pass's end,** the service scans and makes the copy, tries its
  push (11.3's 2 minutes), then commits the completed report (section
  5), whose front matter's `evidence` is the commit that holds
  `passes/<pass>/`, `refused`, or `unknown` while the copy waits. Then
  it gives the logins back and posts its notice, as before: a copy
  delays them by its 2 minutes at most, and never stops them.
- **The record's report takes the same scan:** a line of its body that
  a content rule refuses is withheld from the record, replaced by
  `(withheld: RULE)`, and the notice says so, as it says the report's
  cut (section 5).
- **At each check,** the service tries again every finished pass whose
  scratch is there and whose copy isn't kept: it scans the scratch
  afresh, so a mended one goes through, and pushes a clean copy that
  waits. A report whose front matter doesn't name its kept copy yet is
  committed again with it.
- **A refusal** is in the pass's notice to the director, with each
  file, line and rule, never the text; a check that finds the same
  refusal (the same digest) posts nothing, and a new one posts again.
  The director mends it on the machine by name alone, never opening a
  file: it moves a named file out of the allowlist, into the scratch's
  root, or deletes a named line (`sed -i 'Nd' FILE`); or it leaves the
  copy refused.
- **The scratch waits for the copy:** at its 7 days, the check tries
  the copy once more, then deletes the scratch if its copy is kept or
  refused, and keeps it while its copy waits for a push, as it keeps a
  scratch whose login is not back (10.3). `refused` stays in the record.
- **Passes from before this** are finished passes whose copy is neither
  kept nor refused: the first check gets theirs, as far as their scratch
  holds the allowlist.
- **The link** is the front matter's commit: `git show
  COMMIT:passes/<pass>/` in a clone of qa that fetched `evidence`.
  A report from before this has no `evidence`, and `qa` reads it as
  `unknown`.

### 11.5 Focused walks, and the command

- **The same path:** the ladder's focused walks, the director's runs on
  a rung (10.2), read roles/qa.md, so they lay their scratch out the
  same way, and their copies are kept the same way, in `walks/<name>/`.
  The director keeps one with `qa keep --walk NAME DIRECTORY` on the
  walk's machine once its run has ended, at its end post, and names the
  commit wherever it records the walk. NAME is a new one: the date and
  the walk's (`20261026-rung-a-1`).
- **`qa keep --walk NAME DIRECTORY`** prints the commit, exit 0; or the
  refusal, exit 2; or exit 1 when the push failed, to run again, which
  keeps the same tree.
- **`qa keep --check DIRECTORY`** scans what a copy would hold, and
  prints its files, its bytes, what the cap would leave out and each
  refusal, exit 0 or 2. It reads DIRECTORY alone and writes nothing: no
  record, no clone, no network. A pass runs it on its own scratch
  before its report's last write, and moves out of the allowlist what
  it names (roles/qa.md 2, step 5).
- **One code path:** the service keeps a pass's copy through the same
  snapshot, scan, cap, index and push as `qa keep --walk`.

### 11.6 Its fixture

`scripts/devel/test-qa` proves it against a local origin for qa, in the
fixture's `origins/`, never `fabrig-ai/qa`. Its secrets are made at run
time, never written whole in a source file:

- **A clean pass** ends: `passes/<pass>/` on `evidence` holds the
  allowlist and nothing else from a scratch that also holds a
  deployment, a header file and a cookie jar outside it; its index's
  fields are right; the report's `evidence` is the commit.
- **Each rule refuses:** a scratch with one file per rule, and one path
  with a secret's shape, refuses the copy, naming each file, line and
  rule, and that path by its entry; the matched text is nowhere in the
  output, the log, the post's body or the record; nothing is pushed;
  the report says `refused`. Moving the named file out lets the next
  check keep it, and the report's `evidence` follows; the same refusal
  twice posts once.
- **Plain captures pass:** JSON with `tokens` counts and `"secret":
  false`, a commit's `sha`, a help page's `--password-file FILE`, a
  plan quoting `Authorization: token TOKEN`, a file named
  `session-status.txt`.
- **One snapshot:** a file swapped for a link, or changed, between the
  walk and the commit never reaches the copy.
- **Past the cap,** `evidence/` is left out and the index says so; past
  it again, `scripts/` too; documents past it alone refuse.
- **A push race:** the branch moved between the fetch and the push, and
  the second try keeps both directories.
- **A lost answer:** the push landed but the state wasn't saved, and the
  next check takes the commit that holds the same tree.
- **A failed push** leaves `unknown` without delaying the give-back or
  the notice past 11.3's bound, is tried again, and keeps the scratch
  past its 7 days until it is pushed.
- **The record's body** withholds a refused line, and says so.
- **A walk** is kept in `walks/<name>/`; kept again unchanged it gives
  the same commit; the same name with other files refuses.
- **`--check`** writes nothing and runs with no record and no origin.
- **An old report,** without `evidence`, is read as before.
