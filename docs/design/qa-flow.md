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
  sets up a deployment with the product's own commands, and drives it
  only through the tool its users' agents use: `temper ctl`, for
  temper. For each commit it tests the happy path and two to four tricky
  cases it picks, writing down what it expects before running each
  (section 4).
- **Its report** gives each case's outcome, each finding with the
  commands that reproduce it, and what in the pass a helper could
  automate (section 5).
- **Findings wait in a queue** until they are triaged: routed to an
  owner, put in the backlog, or dropped. Who triages is open; for now,
  the director (section 6).
- **One tool, `qa`,** in `scripts/devel/`, which names no product. Its
  record is three kinds of files in `records/qa/` (section 7).
- **Fakes first:** passes start on the product's fake backends. A real
  forge and a real model follow once the loop runs (the user, 10-26).

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
    finding again what the tier already showed.

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
  read `roles/qa.md`, and names the commits, the `main`, the worktree,
  a scratch directory in `tmp/qa/<pass>/`, the cap and the report's
  path. Its wall time has a cap, the user's to set (proposed: two
  hours). Its tokens are recorded, not capped.
- **What it does:**
  1. Reads each commit's diff and the designs the commit touches.
  2. Writes its plan in the scratch directory before running anything.
     For each commit: the happy path, then two to four tricky cases it
     picks (errors, retries, odd input, a thing done twice or two at
     once), each with the outcome it expects.
  3. Builds the product and sets up a deployment with the product's
     own commands, as the product's guide says: for temper, `temper
     box` on a scratch directory and `temper ctl`'s sign-in. Cases that
     don't disturb each other share one deployment. A case that would
     disturb others gets a fresh one.
  4. Drives each case through the product's tool alone: for temper,
     `temper ctl`, whose `help` is temper's guide for agents. It checks
     outcomes through the tool too. Where the tool can't show one, for
     example a branch on the forge, it may read the backend and says so
     in its report: the tool's not showing it is a finding in itself.
     It never acts on the product any other way: not through its store,
     its HTTP API, or a fake's internals.
  5. Writes its report (section 5).
- **Its transcript is Codex's own:** the session's rollout records
  every command and its output, so no wrapper logs the tool's calls.
- **Backends:** the product's fakes, for now. A real forge and a real
  model come as a second set once passes run (the user, 10-26). Their
  accounts and spend are open (section 9).

## 5. The report

`records/qa/passes/<pass>.md`, at most 8 KB, `<pass>` its start and
repository (`20261026-0915-temper`). The service writes the front
matter: repository, `main`, commits, machine, model, effort, started,
ended, wall time, tokens, and the outcome (`done`, `capped` or
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
| `qa watch` | runs the service (section 4) |

The record is committed with `record commit`, and its rows are in
[records.md](records.md) 3's table:

| Path | Writer | Written | Holds |
|---|---|---|---|
| `qa/decisions.md` | the director, through `qa decide` | appended | one item per choice: `- <time> <repo> <commit> run\|backlog <why>` |
| `qa/passes/<pass>.md` | the pass, and `qa watch` for the front matter | at the pass's start and end | the report (section 5) |
| `qa/triage.md` | the triager, through `qa triage` | appended | one item per finding: `- <time> <pass> <n> <route> <why>`, the route an owner's address, `backlog` or `drop` |

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
  the user unit `agents-qa-watch.service`.

## 9. Open

- **Triage:** who works the findings queue (section 6).
- **Real backends:** which accounts a pass uses on a real forge and
  model, how they are held, and the product's own spend.
- **qa's lab:** what becomes of it (the user, 10-26).
- **The machine:** after landing's runner's, or one of its own.
