# QA after landing

Provisional, 2026-10-26, proposed with the user; revised 2026-10-27
(sections 3, 6, 10.5, 10.6, 11). This is how a change that
landed gets tested by an agent that drives the product the way its users'
agents do:
- the landing's owner marks the commit;
- marked commits are chosen by default, the director keeping the
  exceptions;
- a service starts each pass on a batch of chosen commits;
- the pass reports its findings, and what in it could be automated;
- each finding goes to the mission that landed its commit.

It starts as light as it can (the user, 10-26): no setup helpers
beyond the product's own commands, and tools added only as the passes'
reports show the need. It settles the roles' open question of who
starts QA and who judges its findings ([roles/README.md](../../roles/README.md)
2), the triage included since 10-27 (section 6). It does not use qa's lab,
whose future is open (section 9). The rules that operate it day to day,
each with its date and source, are
[roles/qa-operations.md](../../roles/qa-operations.md).

## 1. In one page

- **The owner marks** a landing commit worth testing with a `QA:`
  trailer: one line on what a user can now do (section 2).
- **Marked commits run by default** (the user, 10-27): once the
  director turns it on for a repository, every marked commit that lands
  after runs, in landing order and batched; the director's `qa decide
  ... backlog` is the exception, for when priorities change (section 3).
- **A service starts the passes by itself.** When a slot and a login
  of each of the rung's pools are free, and chosen commits wait, it
  starts a pass over them, on the newest `main` that after landing has
  cleared; passes run side by side, as many as slots and free logins
  allow, sharing the waiting commits. Commits chosen while passes run
  batch into the next ones (section 4).
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
- **Findings go to whoever landed them** (the user, 10-27): the service
  finds the landing that brought a finding's commit to `main`, and posts
  the finding to that mission's designer; one with no commit, a
  security hole, lost data or a stuck login goes to the director, who
  also routes by hand what the rules don't (section 6).
- **One tool, `qa`,** in `scripts/devel/`, which names no product. Its
  record is files in `records/qa/` (section 7).
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
  free again only once it is back (section 10). Logins of one kind make
  a pool (`chatgpt`, `chatgpt-2`, ...): a pass or a walk takes any free
  one, so that a stuck login leaves the others working (the user, 10-27:
  four ChatGPT accounts).
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
  `main` that have no decision yet and that no default covers (below),
  oldest first, each with its repository, short commit, subject and
  trailer.
- **The director decides** the exceptions at its check (director.md 7),
  from:
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
- **By default** (the user, 10-27): `qa default REPO on|off [--why
  TEXT]` appends to `qa/defaults.md` the repository, `on` or `off`, and
  origin's `main` at that moment. An `on` and the next `off` (or now)
  bound a stretch of `main`: every marked commit that the `on`'s `main`
  doesn't hold and the `off`'s does (or now's) is covered, by ancestry,
  never by a commit's time, which a rebase changes. A covered commit
  counts as a `run` decision made at its `on`'s time: any later event,
  a decision or a pass, comes after it, so that a `backlog` holds it
  and a pass that took it is never followed by another. The service
  takes covered commits in their order on `main`, batched (section 4).
  An `off` leaves the commits it covered chosen; `qa candidates` lists
  the undecided commits no stretch covers. A commit whose rung's pool
  has no login yet waits as any chosen commit does. Overlapping
  stretches give a commit the earliest `on`'s time, and at equal times
  a default ranks under a decision or a pass. Stretches assume that
  `main` only fast-forwards, as `land` never force-pushes; a repository
  whose defaults can't be read starts nothing at that check, its
  reservations kept (agents 45c713a).
- **What carries no mark:** a commit that changes only tests, fixtures
  or figures ([roles/owners.md](../../roles/owners.md) 4).

## 4. The pass

- **The service, `qa watch`,** is a user unit on the machine the
  director names, by writing its own address in
  `~/.config/agents-qa/director` there, as for after landing's runner.
  It checks every five minutes, and at once when a pass ends: its loop
  is the waiter of the mailbox `qa-watch`, where each pass's `codex-run`
  posts its end. It starts a pass when all of these hold:
  - a slot is free: `QA_SLOTS` of them, four on hetzner6 (the user,
    10-27: as many passes as free logins);
  - commits chosen to run are in no pass;
  - the newest `main` that after landing has cleared holds the oldest
    of those commits: `landings cleared REPO`, the newest run of the
    repository's tier whose verdicts are all cleared
    ([landing-flow.md](landing-flow.md) 4, step 8). Reds standing from
    older landings don't hold it back. A pass then spends no tokens
    finding again what the tier already showed;
  - one login of each of the repository's rung's pools is granted to
    the service, `logins take POOL --any` (section 10.3).

  A pass takes chosen commits that `main` holds, oldest first, up to the
  settings' `batch` (five, for now). Passes that start at one check
  share the waiting commits: n is the repository's commits that `main`
  holds and no pass has, k the passes for which a slot and every login
  were reserved, at most n, and each takes ⌈n/k⌉ of them at most,
  oldest first, at most the batch, leaving one for every later pass
  (five over four slots are 2, 1, 1, 1, never an empty fourth), so that
  free slots shorten the wait rather than idle. Each pass's commits are saved in its `pass.json` before any
  starts; a reservation that fails gives its share back to the next
  check. The rest wait for the next passes. A pass covers one
  repository, and a repository may have several at once, each on its
  own commits: chosen commits of several repositories make passes in
  turn, the repository with the oldest decision first.
- **Its checkout:** one clone per repository on that machine,
  `tmp/qa/repos/<repo>/`, and a worktree of it per further slot,
  `tmp/qa/repos/<repo>-<n>/` (n from 2), each with its own `target/`
  inside it, kept between passes, so that passes side by side never
  share a working tree or a target. A pass takes its repository's
  lowest free slot, named in its `pass.json`, and holds it until its
  session's unit and every deployment unit of its own are confirmed
  stopped (10.3), not merely until its report or its logins are back;
  a deployment stopped with a login still out releases the slot, its
  custody and scratch kept. Every call the service makes outside
  itself is bounded (`systemctl` 30 seconds, `logins` and `post` 60,
  `landings` and `codex-run` 120, `record` and a fetch 300); a launch
  that timed out is recovered from its run's meta, never taken for
  none; and one repository's failure, or one refused start, never
  stops the others.
  The service makes a slot's worktree under the clone's lock, and
  before each pass checks it is a worktree of that clone at its path;
  one half made (a crash, a failed checkout) is removed, the clone's
  worktrees pruned, and made again at the next check. It checks the
  slot out, detached, at the pass's `main`. The pass
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
     fresh one. Before a deployment's first start and every restart, it
     runs the checks the binding names on its configuration (temper's
     `qa.md` 3), and stops if one fails: a setup to redo, never a
     finding.
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
`failed`), `logins` (the logins it took, comma-separated, or `-`), and
`evidence`, the commit that keeps its evidence (section
11.4). It commits the file twice: at the pass's start, `running`,
so that the pass shows in `qa passes` and its commits are taken
wherever the record is read; and at its end, completed, with the body.
A third commit writes `evidence` when its copy was pushed after the
end's. A line of the body that the evidence's scan refuses is withheld
from the record, and said (section 11.4).
The pass writes the body, in [roles/qa.md](../../roles/qa.md) 3's
shape; past the cap, the service cuts it and says so. The service reads
`report.md` without following a link: a link there is no report, so
that a pass can't bring another file into the record.

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
- **Routed by landing:** after a pass's end (10.3's order, after its
  notice), the service routes each of its findings that has no triage
  line, by itself:
  - its `Commit:` names a commit on `main`; `landings landed REPO
    COMMIT` names the landing that brought it there: the oldest landing
    in the feed, a plain `land` record or a set's, whose commit holds it
    and whose base doesn't; a landing with no base is skipped;
  - the mission: a set's name, or a plain landing's branch's first
    segment, when it names a directory of the record's `missions/`
    holding a README whose front matter reads;
  - the recipient: the README's `parent` when it is a designer
    (`design/<d>@…`) whose own mission, `missions/<d>/`, is `active`;
    else its `owner` when its own mission is `active`; else the
    director;
  - it posts the finding there, as `qa triage` does, and only once the
    post is accepted (sent or queued) appends the triage line, `- <time>
    <pass> <n> <address> landed by <mission>`, which is what marks it
    routed: so a crash between the two posts it again, and nothing
    else does. The routes waiting are kept in the pass's `pass.json`
    and tried again at each check; a report's later commits (its
    evidence's link) route nothing new.

  The director gets the finding instead when its `Commit:` is absent,
  `unknown`, not on `main` or brought by no landing, when its mission
  or recipient can't be read, and when the finding says `Concerns:
  security` or `Concerns: lost data` (roles/qa.md 3). A designer passes
  on a finding that is another's, as designers do. `qa triage` stays
  the director's, to route by hand or route again: its line is the
  latest.
- **What the code settled** (agents 66efd32): a finding's `Commit:` and
  `Concerns:` come from its own lines under its heading, and a key
  given twice there is ambiguous and goes to the director; an accepted
  post's triage line is saved in `pass.json` before the record's
  commit, so that a refused commit never posts a finding twice;
  `landings landed` reads the whole feed and exits 4, not 1, when it
  can't, and prints `set|land NAME TIME COMMIT`; a post's subject is
  cut to 200 characters, the whole title in its body. Passes that ended
  before routing are never routed: their findings stay the director's.
- **`qa triage PASS N owner ADDRESS|backlog|drop [--why TEXT]`**
  routes one finding by appending its line:
  - an owner's finding goes to that owner by post, naming the report;
  - a backlog one gets an entry in `director/backlog.md` that points
    at the report.
- **The service posts the director** one line when it commits a report
  that has findings.
- **Who triages** was open (the user, 10-26), and is settled (the
  user, 10-27): the landing routes, the director keeps the exceptions.
  A Codex session per pass proposing routes, and a standing owner for
  QA's findings, were weighed and not taken: more tokens, and the
  director still in the loop, for what the feed already knows.

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
| `qa triage PASS N ROUTE [--why]` | routes one finding by hand |
| `qa default REPO [on\|off [--why]]` | runs marked commits by default from now, or stops; alone, shows it (section 3) |
| `qa rung REPO [RUNG [--login POOL]... [--why]]` | opens a rung, or shows the open one (section 10.1) |
| `qa watch` | runs the service (section 4) |
| `qa keep --check DIRECTORY` | scans what a copy of DIRECTORY would hold, and writes nothing (section 11.5) |
| `qa keep --walk NAME DIRECTORY` | keeps a focused walk's evidence (section 11.5) |
| `qa walk REPO RUNG [--kind KIND] [--build REF] [--login POOL]... [--cap MINUTES]` | starts a rung walk on a reserved login, ended by the service (section 10.7) |
| `qa walk REPO RUNG --resume NAME --build REF [--cap MINUTES]` | resumes a paused walk from its kept state, at a fix's build (section 10.7) |
| `qa take KIND [--login POOL] --as walk/<kind>/<what> [--note TEXT]`, `qa give NAME --as HOLDER` | a take by hand, admitted below the kind's cap (section 10.6) |
| `qa deploy DIRECTORY NAME -- COMMAND...` | starts a pass's deployment in a unit of its own, stopped by its give-back (section 10.5) |

The record is committed with `record commit`, and its rows are in
[records.md](records.md) 3's table:

| Path | Writer | Written | Holds |
|---|---|---|---|
| `qa/decisions.md` | the director, through `qa decide` | appended | one item per choice: `- <time> <repo> <commit> run\|backlog <why>` |
| `qa/passes/<pass>.md` | the pass, and `qa watch` for the front matter | at the pass's start and end | the report (section 5) |
| `qa/triage.md` | `qa watch`, by landing, and the director, through `qa triage` | appended | one item per finding: `- <time> <pass> <n> <route> <why>`, the route an owner's address, `backlog` or `drop` |
| `qa/defaults.md` | the director, through `qa default` | appended | one item per change: `- <time> <repo> on\|off <main> <why>`, `<main>` origin's at that moment |
| `qa/rungs.md` | the director or design/ladder, through `qa rung` | appended | one item per opening: `- <time> <repo> <rung> <logins> <why>`, the logins comma-separated, or `-` |

Times are UTC to the second, commits full SHAs. The settings are the
kit's: the machine, named as section 4 says, and `machine.env`'s
`QA_SLOTS` (1; 4 on hetzner6), `QA_LOGIN_RESERVE` (2, section
10.6), `QA_WALK_KINDS` (`forgejo=2:chatgpt claude=2:claude`, section 10.7), `QA_BATCH` (5), `QA_CAP_MINUTES` (120),
`QA_INTERVAL_SECONDS` (300), `QA_STOP_SECONDS` (50, section 10.5) and
`QA_EVIDENCE_KIB` (2048, section 11.1).

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

- **Triage:** settled, by landing (section 6).
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
  takes, by their pools' names in `logins` (temper's `docs/design/qa.md`
  3: fakes; a real model, with a ChatGPT login; GitHub).
- **The director, or design/ladder, opens a rung** (the user, 10-27:
  design/ladder judges when a walk has passed) for a repository: `qa rung REPO RUNG
  [--login POOL]... [--why TEXT]`, each POOL a pool's name (10.2),
  once the rung below has run clean,
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
- **A pool:** a name that doesn't end in `-<digits>`, and its numbered
  siblings: pool `chatgpt` is `chatgpt`, `chatgpt-2`, `chatgpt-3`,
  `chatgpt-4`, logins of one kind, each its own account and each one
  holder at a time. Two pools never share a login. `logins take POOL
  --any --as HOLDER` grants one of them that is at rest and held by
  nobody, this holder included, and prints its name and its resting
  path; a take by name still takes that login alone.
- **One order for every taker:** every change (`add`, `take`, `give`)
  is made under one lock for the whole tool, `tmp/logins/lock`, and
  every taker that waits is in one queue, `tmp/logins/waiting.json`,
  each with its request (a name, or a pool), when it first asked, and
  when it last asked. A free login goes to the earliest waiter it
  matches: in arrival order, each waiter reserves the first free login
  it matches, so that a waiter for a stuck login by name reserves none
  and a pool's waiter only one, and a taker is granted the login it
  reserves. Ties go by holder name. A waiter that hasn't asked again
  within 15 minutes leaves the queue, as today, and until then its row
  keeps its reservation: a taker that gives up asks no more and its row
  goes stale. The names `lock` and `waiting.json` are the tool's, never
  a login's. The lock is taken first, then each login's own lock in
  name order.
- **Leaving the queue:** a `--wait` that runs out removes its row, and
  `logins drop NAME --as HOLDER`, or `logins drop POOL --any --as
  HOLDER` for a pool's request, removes that waiter's row by hand
  (B0's walk waited 12 minutes behind a stale row, 10-27). A holder
  that asked only once and went is still gone after 15 minutes.
  A login not back stays held by its holder, as below, and the pool's
  others go on serving: the notice and `logins list` name the one that
  is stuck.
- **A login comes from a box the user signs in:** on the logins'
  machine, a box on real backends (temper's walk `box`, 2, 3, 5 and 8),
  where the user signs the account in from a browser elsewhere through
  `ssh -L` to the box's callback; its export to a private file, never
  read; `logins add NAME FILE`. An agent may run the box and the moves,
  by path alone; only the user's browser sees the account.
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
  story) by `logins take POOL --any` before their start, their brief
  naming the login granted, and `logins give NAME` after their end, each started with `codex-run task --on-stop` and a brief
  that writes the give-back file as 10.3 says. The director is their
  holder: it gives at the run's end post, and a give refused is its own
  to recover, as 10.3's last point says.
- **Saturation shows in `logins list`:** each login's holder and since
  when, its waiters, and its last 24 hours: time held, takes, longest
  wait. The director reads it at its check; a login held most of the
  day while passes wait is saturated, and the director tells the user.

### 10.3 A pass on a rung with held logins

- **The service takes before it starts:** at a check where a pass
  could start (section 4), it takes one login of each of the rung's
  pools as the pass's own holder, `qa-watch/<pass>`, `logins take POOL
  --any`, in the pools' name order, and saves each grant in the pass's
  `pass.json` before it asks for the next: so two passes never hold
  one login. One refused gives back those taken, still at rest, and
  the pass waits for a later check, its commits still chosen, the
  service's place in the queue kept. The brief names each login taken,
  with its resting path, and the report's front matter its name
  (section 5). An opening from before pools (`temper real-model
  chatgpt`) names a pool already. A login
  is held from the pass's start, its build and plan included: minutes,
  where a session taking it itself would wait inside its cap.
- **Nothing held without a pass:** at each check the service reads
  `logins list` for the logins held by `qa-watch/…` (and by
  `qa-watch`, from before), and gives back each that no saved pass
  holds a grant of, so that a crash between a take and its save, or a
  pass's start, strands nothing. A login out with one pass never holds
  back another pass: the next takes another of the pool.
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
- **A stuck login's alert** goes as soon as the service finds a moved
  login not back (step 2 of a pass's end, below), apart from the
  pass's notice and ahead of it: to the director and to each address
  in `~/.config/agents-qa/stuck` on the service's machine, one a line
  (design/upgrades-draft's, 10-27), the director's to keep. Each
  address's delivery is saved and tried again at each check until
  accepted, once per stuck login (per attempt, for a walk). Its body
  names the login, its resting path and pool, the pass or walk, its
  directory, its units still up, and that it counts against its class's
  cap until it is back. The recipients are read at the first failed
  give and kept; the file is read without following a link, a regular
  file of at most 16 KiB, at most 16 addresses, `#` for comments, and
  one absent or damaged leaves the director alone. As every post of
  the service's, an alert is sent at least once (agents 5330c8b).
- **A pass's end, in order,** each step saved in its `pass.json` before
  the next, and each one not done tried again at the next check:
  1. the report and the evidence (section 5, 11.4);
  2. each moved login given back (`logins give`, which frees it once it
     is back at rest);
  3. once every moved login is back, each of the pass's units stopped,
     those systemd lists for it (10.5), and its stop confirmed by
     `systemctl`; a pass that held no login has its units stopped at
     once;
  4. each login used in place given back, only once every unit of the
     pass is confirmed stopped, so that no deployment still uses it
     when it is free;
  5. the notice, which says what is still out: a login not back, a
     unit up or of unknown state;
  6. its findings routed (section 6).

  A moved login found not back at step 2 raises its alert at once
  (above), before the steps that follow.

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
| `logins take POOL --any --as HOLDER [--note TEXT] [--wait SECONDS \| --now]` | grants any free login of the pool, first come first served, and prints its name and resting path; exit 1 while none is free to HOLDER (10.2); `--now` never joins the queue (10.6) |
| `logins drop NAME --as HOLDER`, `logins drop POOL --any --as HOLDER` | removes HOLDER's place in the queue for that request (10.2) |
| `logins give NAME --as HOLDER` | frees NAME once its login is back; exit 1, still held, if it isn't |
| `logins list [NAME]` | each login's holder, waiters and last 24 hours |

### 10.5 A deployment's unit

- **`qa deploy DIRECTORY NAME -- COMMAND [ARG]...`** starts COMMAND as
  the transient user unit `qa-<pass>-<NAME>`, `<pass>` DIRECTORY's
  name, and prints the unit's name. DIRECTORY is a pass's scratch
  directory, or a focused walk's, absolute and of the characters a stop
  command may hold (codex-run's rule: no shell, no `$`); NAME is a
  lowercase slug that starts with a letter, so that `qa-P-2-box` is
  never both P's `2-box` and P-2's `box`. Before it starts the unit, it
  appends the unit's name to `DIRECTORY/deployments`: a trace for the
  director, never read by the service, since the pass can change it.
- **The service finds a pass's units by systemd's listing,**
  `systemctl --user list-units --all 'qa-<pass>-*'`, keeping a unit only
  when its name is exactly `qa-<pass>-<NAME>` and its working directory
  is the pass's scratch. A listing or a `show` that fails or reads
  oddly makes the units' state unknown: the pass's in-place logins and
  its scratch stay held. Each stop is `--no-block`, then confirmed by
  bounded `show`s, since a collected unit refuses a stop as not loaded;
  every `systemctl` call is bounded (30 seconds), and one pass's failure
  never stops the check for the others. A pass from before `qa deploy`
  has no logins' kinds in its state, and its units are never listed or
  stopped.
- **The unit:**
  - `Type=exec`, COMMAND in the foreground, `KillMode=control-group`;
    started with `--expand-environment=no` (systemd 257 expands `$` in a
    transient unit's command) and the caller's `PATH` alone;
  - works in DIRECTORY, its output appended to `DIRECTORY/<NAME>.log`;
  - its stop command (`ExecStop=`) is `qa`'s give-back wrapper on
    DIRECTORY: it runs `DIRECTORY/give-back` under a lock,
    `DIRECTORY/give-back.lock`, so that runs take turns; an absent file
    is nothing; a run is bounded, its output and exit appended to
    `DIRECTORY/give-back.log`; and a failure never fails the unit, as
    codex-run runs a stop command (post.md 5). Its bound is
    `QA_STOP_SECONDS` (50). A give-back child that leaves its process
    group (`setsid`) escapes the lock, though the unit's cgroup kill
    still ends it: a known limit;
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
  - the real command line: with no tool overridden, `qa deploy` runs the
    program named `systemd-run` on PATH, and the service the one named
    `systemctl` (10-27: `qa deploy` ran systemctl with systemd-run's
    arguments, since every story overrode the tool); where the machine
    has a user manager, a story on a real throwaway unit shows its stop
    command run before its process ends;
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

### 10.6 Passes side by side

- **As many as slots and logins allow:** `QA_SLOTS` caps the passes at
  once on the machine, and a rung with a pool runs no more passes than
  the pool has free logins. A pass on the fakes needs a slot alone.
- **Two logins kept for rung walks** (the user, 10-27: rung walks come
  first, as they prove the product end to end): of each pool, QA's
  passes hold at most its size less `QA_LOGIN_RESERVE` (2), counting
  every login held by `qa-watch/…` or by `qa-watch` from before, a
  stuck one included: a login a pass stranded counts against QA until
  it is back, and its report and notice say so. With four, QA holds two
  at most, and a walk's `logins take POOL --any` always finds one unless
  walks already hold two: the second is the first's backup. The
  reserve is the service's own cap, checked under its own lock, one
  admission at a time; `logins` keeps no class of holder. A pool no
  larger than the reserve runs no QA pass, and `qa passes` says why.
- **A pool shared out by caps** (the user, 10-27: ChatGPT+Forgejo walks
  are never blocked by anything): every taker of a pool is in a class,
  each class has a cap, and the caps add up to at most the pool's size,
  so that a class below its cap always finds a free login, whatever the
  others do. The classes: QA's passes, holders `qa-watch` and
  `qa-watch/…`, whose cap is the size less `QA_LOGIN_RESERVE`; and each
  kind of walk, holders `walk/<kind>/…`, whose cap is its walk slots
  (10.7), one login of a pool per walk. A take by hand (a live story,
  a recovery) goes through `qa take KIND [--login POOL] --as
  walk/<kind>/<what> [--note TEXT]`, which admits it as `qa walk` admits
  a walk, under the walks' lock, below the kind's cap, with `--now`, and
  prints the name and path granted; `qa give NAME --as HOLDER` gives it
  back. `logins take` by hand would count without being admitted, and
  could take a kind past its cap (o/qa-evidence-keep, 10-27). A class's count is every login its holders
  hold in `logins list`, whatever their state: a stuck one, a grant
  saved but not yet started, a walk ended with a login still out. Each
  class admits below its cap alone, machine-wide, under its own lock
  (the watch's, the walks'), and takes with `--now`: under the caps a
  free login is there, and a refused take means a cap was broken, so
  the walk or pass refuses at once and says so. The kit never waits in
  the queue.
- **The sum is checked:** each kind names its pools (10.7), and the
  tool refuses a configuration where, for a pool, the reserve is less
  than the slots of the kinds that use it. With ChatGPT+Forgejo's two
  alone, `QA_LOGIN_RESERVE` is 2; with ChatGPT+GitHub's one beside them,
  3, QA yielding one login until more accounts give it back. A cap
  lowered, or the reserve raised, reclaims nothing: the new guarantee
  holds once the class's holdings have drained below it, which `qa
  passes` shows, each class's holding beside its cap.
- **QA never waits in the queue:** its takes are `logins take POOL
  --any --now`, granted only a login that is free and that no waiter
  claims, refused at once otherwise without a place in the queue
  (10.4). So QA never holds a reservation a walk would need, and a walk
  that waits goes before it. While a `qa-watch` row from before `--now`
  still waits in the queue, QA admits no pass, so that an abandoned row
  never keeps a walk's login.
- **The count is strict:** it comes from one `logins list` per check,
  read line by line; a line out of its form or a login listed twice
  admits no pass and gives back no stray, and a note refuses every
  control character. A grant saved counts at once, and one past the cap
  is cancelled with the rest of its repository's reservations, the next
  check admitting within the cap; a take whose answer was lost counts
  until the next listing.
- **Built where they run:** each pass builds in its slot's checkout,
  through `heavy` at background weight, which queues builds so that
  they never starve the machine's other work. Measured on hetzner6
  (10-27): 8 cores, 15 GB with about 11 free, 232 GB of disk free over
  a 40 GB floor; a pass's box peaked at 0.4 GB and used 26 seconds of
  CPU in 15 minutes; a build in a warm target took 10 seconds to 2
  minutes; a slot's target is about 8 GB, so four slots take about 32
  GB, and a new slot's first build is cold once. Passes wait on the
  model far more than they build, so four at once cost little there,
  and building elsewhere would add a binary's transfer and a second
  machine's state for minutes saved: they build on the logins'
  machine.
- **Four walks and two passes** on hetzner6 (10-27, from 10.6's
  measures): six boxes at about 0.4 GB and six Codex sessions, about 5
  GB with the Claude walks' Claude Code processes (one per agent run,
  a few hundred MB each, not yet measured there) against about 11 GB
  free; six slots' targets about 48 GB against 232 free; builds queued
  by heavy. It holds, with a margin to watch: the first Claude walk is
  measured, and below 2 GB free QA's slots go to 1 before any walk
  waits.
- **Its fixture,** `test-logins` and `test-qa`:
  - a pool's take grants a free login and names it; never one already
    held, by this holder or another; a name ending in `-<digits>` is no
    pool;
  - one queue: a take by name and a take of the pool wait in arrival
    order, and a waiter for a stuck login holds back no take of a free
    one; a waiter gone 15 minutes leaves it;
  - a stuck login leaves the others taken and given, and the notice
    names it;
  - two passes start side by side in two slots, each with its own login
    and its own share of the commits, and each brief and report names
    its login and path;
  - a crash after a grant and before its save leaves the login given
    back at the next check; one half-made worktree is made again;
  - a finished pass whose units are up or unknown keeps its slot, and
    its logins as 10.3 says;
  - a pass waits while no login of its pool is free, and starts once
    one is given back;
  - the reserve: with four, two passes hold two and a third waits while
    two are free; a stuck login leaves QA one pass; a walk's take finds
    a login while walks hold fewer than two, whatever QA has asked; a
    `--now` take refused leaves no row in the queue.

### 10.7 Rung walks

The user, 10-27: rung walks come first, as they prove the product end to
end; a walk runs, its findings are filed, the fix is committed, and
again, as tightly as possible. A walk is the ladder's: its brief, its
rung and its findings are the rung owner's (design/ladder's loop), and
the kit only starts it and ends it, as the service ends a pass.

- **Kinds of walk** (the user, 10-27: per rung, ChatGPT+Forgejo first,
  then the same walk on Claude+Forgejo, then ChatGPT+GitHub; the first
  never blocked): a walk has a kind, `--kind KIND`, one of
  `QA_WALK_KINDS`, each kind with its walk slots and its pools
  (`forgejo=2:chatgpt claude=2:claude`, and `github=1:chatgpt` once
  its walks start), the first listed by default. A kind's walk slots are
  its own, machine-wide, never taken by another kind, and they cap its
  logins of each of its pools (10.6). A walk's logins are its kind's
  pools; `--login` may only name one of them.
  Its brief is `tmp/qa-focused/rung-<RUNG>-<KIND>-brief.md` where that
  file is, else the rung's. The default kind's walks keep their names,
  `rung-<RUNG>-<n>`; another kind's are `rung-<RUNG>-<KIND>-<n>`, with
  `<KIND>-<n>` in the clock's walk column.
- **`qa walk REPO RUNG [--kind KIND] [--build REF] [--login POOL]...
  [--cap MINUTES]`,** on the logins' machine, by the rung's owner, whose
  address (`POST_NAME`) and its REF it checks first, before it takes
  anything: REF is a commit (unique), `origin/<branch>`, or a bare
  `<branch>` that names a branch on origin; one it can't resolve is
  refused at once, naming the form to try (design/ladder, 10-27: a
  resume took and gave back a login before it refused its build). A
  branch resolves by its exact ref on origin, never to a tag or a
  local branch of that spelling, and the clones' fetch prunes, so that a
  branch deleted on origin never resolves; the resolved commit is saved
  and checked out even if the branch moves after (agents fe72017). RUNG is the ladder's name
  (`a`, `b0`), one namespace on the machine. Under the walks' lock,
  `tmp/qa/walks.lock`, one walk at a time:
  1. the walk is the rung's next number n of its kind, its name as
     above, `rung-<RUNG>-<n>` for the default kind, its directory
     `tmp/qa-focused/<name>/`, private, and its state
     `tmp/qa/walks/<name>.json`, saved before anything is
     taken and after each step: REPO, RUNG, REF, the starter, the cap
     and its start, the slot, each grant with its kind, the run, and how
     far its end has come;
  2. it takes the lowest free walk slot of its kind, a worktree of the
     service's clone, `tmp/qa/repos/<repo>-walk-<kind>-<k>/` (k from 1 to
     the kind's slots), made and checked as a pass's slot is (section
     4); with none free it refuses at once, having taken nothing;
  3. it takes one login of each of its kind's pools, `logins take POOL
     --any --now --as walk/<kind>/<name> --note DIRECTORY`, saving each
     grant before the next; with the caps kept (10.6), a kind below its
     cap finds a free login at once; one not granted gives back those
     taken, frees the slot, nothing starts, and the refusal names the
     broken cap;
  4. it checks the slot out, detached, at REF: a commit or a branch on
     origin, `main` by default (a fix's branch, for its confirming
     walk);
  5. it copies the rung's brief, `tmp/qa-focused/rung-<RUNG>-brief.md`,
     unchanged into the directory as `brief.md`, and writes beside it
     the session's task: read `brief.md`, then the walk's facts (its
     directory, its checkout and REF, each login's name and resting
     path, the give-back file, `qa deploy` for its deployments, its cap);
  6. it appends `walk-start` to the rung's clock,
     `tmp/qa-focused/<RUNG>/loop.tsv` (made with its heading, `time rung
     walk event note`, if absent; each append under a lock on the file,
     and saved as done in the state, so that a retry never writes it
     twice), its note the logins and REF;
  7. it starts the session, `codex-run task --to qa-watch --on-stop`
     the give-back wrapper (10.5), its report `DIRECTORY/report.md`,
     saves the run, and prints the walk's name, its logins and its run.

  A crash at any step leaves the state saying how far it came: the
  service's next check gives back each login held by a `walk/…` holder
  that no saved state holds a grant of (10.3's strays), and frees a slot
  whose walk never started.
- **The service ends it** as it ends a pass (10.3's order, steps 2 to
  5), from its saved state: it stops the session at its cap (MINUTES,
  180 by default, from its saved start) and waits for its stop wrapper
  before it gives anything back; its moved logins given back as
  `walk/<kind>/<name>`, its units stopped once they are back,
  in-place logins after, and a stuck login's alert at once. The walk
  slot is held until the session's unit and every deployment unit of
  the walk are confirmed stopped; one of unknown state keeps it. Then it
  appends `walk-end` to the clock (its note the run's exit and what is
  still out) and posts the walk's end to its saved starter: its report,
  and any login not back; each saved as done, and tried again at each
  check until accepted. It commits no record and routes no finding:
  the rung owner reads the report and files its findings by the loop's
  rules. At a walk's end, not its pause, the service keeps its evidence
  as a pass's (11.5).
- **A pause at a blocking finding** (the user, 10-27: resume from the
  very same state as soon as the fix is ready, even before it lands;
  meanwhile the login serves another walk). The walk's task says how,
  and the rung's brief and loop say when:
  1. the session writes the finding in its report and its notes, and
     the step it stopped at in `DIRECTORY/paused`, one line;
  2. it gives each moved login back by the give-back file and checks
     each by `stat` (give back before you break it), then stops its
     deployments, whose directories stay as they are, with the command
     that started each (`qa deploy`'s arguments, which the tool also
     saves), so that a restart needs neither the slot's checkout nor
     its unit;
  3. it ends. The service ends the run as any walk's (10.3's order:
     moved logins given back, units stopped and confirmed, in-place
     logins after), and makes one decision, saved: `walk-pause` when
     `paused` is there and every login is back and every unit
     confirmed stopped, else `walk-end`, a login not back making it a
     stuck end, alerted as any. A paused walk frees its walk slot,
     keeps its directory and state, appends `walk-pause` (its note the
     paused line) and posts the starter.
- **`qa walk REPO RUNG --resume NAME --build REF [--cap MINUTES]`**
  resumes the paused walk NAME (`rung-b1-claude-2`), of the kind its
  state saved, under the
  walks' lock and only once its pause's end is complete. It saves a new
  attempt in the walk's state (its run, start, slot, grants and end
  progress, so that nothing of the attempt before is given or ended
  twice), takes a free walk slot of its kind and one free login of each
  of its pools, one refused undoing all as at a start (steps 2 and 3
  above): a pause frees its kind's slot and logins for other walks, so
  a resume refuses at once while the kind has none free, and its owner
  asks again, checks the slot out at REF
  (the fix's branch, before it lands, or `main` for the walk that
  counts), removes `paused`, writes the session's task (the walk's
  facts, each kept deployment's saved command and directories to start
  again with REF's binary through `qa deploy` on their own data, the
  binding's configuration checks before that start, each login to
  import again, and the step to go on from, the removed `paused`
  line), appends `walk-resume` to the clock (its note the logins and
  REF), and resumes the walk's Codex thread with it, `codex-run task
  --resume RUN --to qa-watch --on-stop` the wrapper. A thread that
  can't resume gets a fresh session on the same task and the walk's
  notes, saved as the attempt's run; a launch that fails gives back
  what the attempt took. The walk keeps its number, directory and
  report; its cap starts again.
- **A kept store that won't open** (a fix moved a stored family, which
  no version guards before the first release): the resumed session
  says so in its report and walks again from the first step on a fresh
  deployment in the walk's directory.
- **The walk that counts ends on `main`:** a resume on a branch shows
  the fix; the rung's final walk confirms it at the landed commit,
  resumed from the kept state where the landed binary reads it, else
  from the start (design/ladder's loop).
- **What the code settled** (agents b844696): a resume moves the
  walk's `report.md` to `report-<k>.md` and `paused` to `paused-<k>`
  (codex-run refuses an existing report), and the resumed session writes
  `report.md` anew, carrying the earlier findings over; a run with its
  meta and no unit or end is a launch still possible for 10 minutes,
  and past them while a `codex-run task` process for its task lives; a
  `logins take` decided under an admission lock passes that lock to its
  child, so that a child outliving its caller keeps every class under
  its cap; a login two states claim is given back for neither, and a
  state over 1 MiB or unreadable is set aside, its custody kept. Left as
  they are, by decision: a pool smaller than its kinds' walk slots
  (a refused `--now` names the broken cap), and a starter's post sent
  again after a crash (at least once).
- **Not QA's:** a walk's logins are no `qa-watch` holder's, so they
  don't count against QA's cap (10.6), and its walk slots are no QA
  slot; QA's `--now` takes never stand ahead of a walk that waits.
- **Its fixture,** `test-qa`: a walk takes a free login of its pool and
  a walk slot, writes the rung's brief unchanged beside its task, and
  appends `walk-start` once; one refused login starts nothing and
  leaves nothing held; a third walk is refused at once, holding
  nothing; a crash after a take and before its save leaves the login
  given back at the next check; the service stops a walk at its cap,
  ends it in 10.3's order, appends `walk-end` once and posts its
  starter, again until accepted; a stuck login stays held by the walk
  and is alerted; a walk's slot stays held while a unit is up or
  unknown; a walk's logins leave QA's cap untouched; a paused walk
  frees its slot and logins, appends `walk-pause`, and resumes at a
  branch with another free login, its number, directory and report
  kept, appending `walk-resume`; a pause with a login out ends the walk
  stuck.

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
- **What the code settled** (agents 16c1655): a path is scanned part by
  part and whole, a match named by its entry; a quoted value is checked
  whole, and a comment cut only from an unquoted value after a name; a
  shell word with escaped spaces is read whole; a placeholder may end in
  one of `, ; ) . :`; a tree the cap leaves out is counted whole, an
  entry it can't read said. Left as they are, by decision: HTTP header
  folding (obsolete since RFC 7230), JSON's `\u` escapes inside a key,
  and the scratch path's own ancestors (the operator's). `record`'s
  private-key rule is the same as the scan's, linear.
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

- **The same path:** a rung walk reads roles/qa.md, so it lays its
  scratch out the same way, and its copy is kept the same way, in
  `walks/<name>/`, NAME the walk's start date and its name
  (`20261027-rung-b1-3`), so that a number the ladder reuses never takes
  another's place. A walk `qa walk` started is kept by the service at
  its end (10.7), as step 1 of its end, before its logins are given
  back, and its `walk-end` post names the commit or the refusal; a
  pause keeps nothing, and the walk's end after its last resume keeps
  the whole of it. A walk's allowlist adds its earlier attempts'
  reports, `report-<k>.md`. A walk from before `qa walk` (the ladder's
  rung-a and github-land walks of 10-26 and 10-27) is kept by hand,
  with `qa keep --walk NAME DIRECTORY` on its machine once its run has
  ended.
- **`qa keep --walk NAME DIRECTORY`** prints the commit, exit 0; or the
  refusal, exit 2; or exit 1 when the push failed, to run again, which
  keeps the same tree.
- **`qa keep --check DIRECTORY`** scans what a copy would hold, and
  prints its files, its bytes, what the cap would leave out and each
  refusal, exit 0 or 2. It reads DIRECTORY alone and writes nothing: no
  record, no clone, no network. A pass runs it on its own scratch
  before its report's last write, and moves out of the allowlist what
  it names (roles/qa.md 2, step 5).
- **One code path:** the service keeps a pass's and a walk's copy
  through the same snapshot, scan, cap, index and push as `qa keep
  --walk`; a walk's refusal is mended as a pass's (11.4), its state
  trying the copy again at each check while its directory is there.

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
