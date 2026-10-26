# QA after landing

Provisional, 2026-10-26, proposed with the user. This is how a change that
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
  deletes a pass's scratch directory 7 days after it ends.
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
started, ended, wall time, tokens, and the outcome (`done`, `capped` or
`failed`). It commits the file twice: at the pass's start, `running`,
so that the pass shows in `qa passes` and its commits are taken
wherever the record is read; and at its end, completed, with the body.
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
`QA_SLOTS` (1), `QA_BATCH` (5), `QA_CAP_MINUTES` (120) and
`QA_INTERVAL_SECONDS` (300).

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

## 9. Open

- **Triage:** who works the findings queue (section 6).
- **Real backends' spend:** the subscriptions' use is measured by
  `logins list`'s last day; whether passes get a cap of their own on it
  is the user's.
- **qa's lab:** what becomes of it (the user, 10-26).
- **The machine:** settled, where the held logins rest (section 10.2).

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
  the deployment that used it has stopped, which the unit's stop
  ensures. It runs that file itself before it
  stops its deployment, and checks each path by `stat`. It never runs
  `logins`. A stop in the seconds between the import and the file is a
  login lost in its deployment (below).
- **A stop gives back too:** the session runs under `codex-run task
  --on-stop` with the give-back file, so that its unit runs the file
  before the deployment inside it is signalled: at the cap, a person's
  stop, a shutdown, or a session that ended with its deployment up
  ([post.md](post.md) 5).
- **The service gives after the end,** once the run's unit is
  inactive and its give-back done. A login not back stays the
  service's: the pass's notice to the director names it and the
  deployment's directories, and the service tries the give again at
  each check, so that the login is free as soon as it is back. It
  keeps that pass's scratch until then, past its 7 days.
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
