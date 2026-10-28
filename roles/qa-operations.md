# QA's operations

Provisional, 2026-10-27. How QA runs day to day: the rules the user and
the designers have set on top of QA's design, who does what, and the
recipes. The mechanisms are designed in
[qa-flow.md](../docs/design/qa-flow.md) (the `qa` and `logins` tools,
passes, walks, the evidence) and in each product's binding (temper's
`docs/design/qa.md`); a pass's own steps are [qa.md](qa.md). This file
holds what operates them, each rule with its date and source, so that
every session in QA's chain works from the same rules and their changes
are kept in git, not in notes or a session's memory (the user, 10-27).

**Who changes it.** A rule the user sets is written in by the director. A
rule a designer settles in its own part is written in by that designer:
design/ladder the walk loop (section 3), design/qa-evidence the tools'
settings and recipes (sections 6 and 7). Each lands with `land --docs`,
with its date and source, and adds a line to section 10. A rule that
lives only in a post, a brief or `tmp/` is not yet a rule: it goes here.
The director reads this file against what it sees at each check.

## 1. In one page

- **Rung walks come first** (the user, 10-27 18:2xZ): they prove real
  end-to-end correctness, which is what v0.1.0 needs. Two of the held
  ChatGPT logins are theirs, one used and one as its backup; QA after
  landing uses the rest (sections 3 and 6).
- **The ladder is climbed one rung at a time** (the user, 10-27
  10:4xZ): under the soft pause, the next rung's path is the only
  exempt work, beside what the user exempts by name (configuring's
  draft, 17:4xZ). design/ladder names the path; the director confirms.
  Green so far: rung 0 (10-24), A (10-27 18:07Z), B0 (18:30Z); next B1.
- **The loop is tight:** a walk runs, its findings go straight to the
  owners who fix them, the fix is committed, and the walk goes again. A
  walk at a blocking finding pauses and resumes from the very same state
  as soon as the fix is ready, even before it lands (the user, 10-27
  18:4xZ) (section 3).
- **Real backends, as planned** (the user, 10-27 10:2xZ): ChatGPT with
  the box's owned Forgejo, and no walk on fakes.
- **Each rung walks three ways, in order** (the user, 10-27 19:0xZ):
  ChatGPT+Forgejo green first, then the same walk on Claude+Forgejo, then,
  once that clears, ChatGPT+GitHub. Claude+GitHub is not planned unless
  capacity allows. ChatGPT+Forgejo "should never be blocked by anything":
  its two logins and walk slots are its own, and the other walks get two
  slots of their own (section 6); where an owner has fixes for both, the
  ChatGPT+Forgejo walk's goes first.
- **The box under test runs gpt-6.1-sol at effort high,** its budgets
  raised as a person would, so that a budget never stops a walk (the
  user, 10-27 10:2xZ) (section 5).
- **A held login is never read, printed or copied:** it moves in and out
  by the product's import and export, and is checked by `stat` and
  sha256 alone (section 6).
- **Give back before you break it:** a case that may break a deployment
  exports the held login first (section 5).
- **QA after landing becomes mechanical** (the user, 10-27 18:2xZ, "yes
  to everything"): marked commits run by default, a finding goes to the
  designer of the mission that landed its commit, and a stuck login
  alerts its fixer at once. The director keeps the exceptions (section
  4).
- **QA's evidence is kept** in the private qa repository, never a secret
  (the user, 10-27) (section 8).

## 2. Who does what

| Who | Does |
|---|---|
| the user | sets the rules; signs in each held login (6.2); budgets and time limits |
| the director | QA's settings and kit on the logins' machine (section 7); the exceptions in choosing and triage; a stuck login's escalation; `logins list`, the walks' clocks and the passes at each check; v0.1.0's progress page; the user's rules in this file |
| design/ladder | the rung briefs and the walk loop (section 3); opens rungs with `qa rung`; names each rung's path; answers a walk's design gaps within the half hour; posts each green rung |
| a rung's owner | runs its rung's walks, files their findings, fixes them, confirms each fix on its branch |
| design/qa-evidence and its owner | the `qa` and `logins` tools, and the evidence |
| design/upgrades-draft and its owner | restarts and exports: a stuck login's recovery (6.4) |
| each mission's designer | the findings routed to it, given to its owners |
| QA passes | Codex sessions, as [qa.md](qa.md) says |
| o/tier-flakes | a flake that fails a gate on the rung's path |

## 3. The rung walk loop

design/ladder's, with the rung owners (the user, 10-27 18:2xZ and
18:4xZ). Walks start with the launcher, `qa walk` (qa-flow.md 10.7, how
to use it in 6.1): `qa walk temper RUNG [--kind claude] [--build REF]`
to start, `--resume NAME --build REF` to resume; a login wanted by
hand, for a live story, is `qa take KIND --as walk/KIND/WHAT` and `qa
give`, never `logins take`. It writes the clock's walk events; the rest
are the owner's.

1. **A walk** runs its rung's brief, copied unchanged, on a login of
   the walks' two, at `main` or at a fix's branch: `qa walk temper RUNG
   [--build REF]`. It opens `tmp/qa-focused/rung-<RUNG>-<n>/` on the
   logins' machine, and gives the login back before its box stops.
2. **At its end, the rung's owner files every finding at once,** each a
   task with its evidence, and starts the fix in the same minute:
   - in its own code: its implementer, now, exempt from any pause;
   - in another owner's code: posted straight to that owner, with
     design/ladder copied, never through the director;
   - a design gap, or a question of what the rung means: to
     design/ladder, which answers within the half hour or says when.
3. **A blocking finding pauses the walk.** The walk stops at that step,
   files the finding, and gives the held login back by its export. It
   stops its box and keeps the box's directories and its notes as they
   are. The login goes to any other walk meanwhile, and the step it
   stopped at goes in one line in the walk's `paused` file.
   A finding blocks when the walk can't reach what its brief's "What
   passes" asks without a hand on the product: a step fails, a hold no
   act of the brief lifts, a refusal, a wrong result. One that blocks
   nothing (words, a slow but bounded step, a read that recovers) is
   filed, and the walk goes on.
4. **The walk resumes from the same state** the moment the fix is ready
   on its branch, before it lands: `qa walk temper RUNG --resume N
   --build FIX-BRANCH`. The kept box restarts with the fix branch's
   binary on its own data, any free login is imported, and the walk goes
   on from the step it paused at. A new binary may name a new memory
   figure at the restart (its worst case moved): it is raised as temper's
   qa.md 3 says and said in the report, a setup step, not a finding. A fix that moves a stored family
   restarts the walk from step 1, and the finding's line says so:
   nothing is versioned before the first release, so an older store may
   not open, and design/upgrades-draft says whether one does.
5. **The walk that counts for green ends on `main`:** once the fix lands,
   at the landed commit, without waiting for the tiers' verdicts or
   anyone's word. It resumes again from its kept state where the landed
   binary reads it, else from the start. A resume on the branch shows the
   fix; the one on `main` confirms it. A tier red found later counts
   against the walk only if it lies on the walk's path.
6. **A walk that passes** is posted to design/ladder at once. design/ladder
   posts the director, and opens the next rung's walk.
7. **Per rung, three walks in order** (the user, 10-27 19:0xZ): ChatGPT
   with an owned Forgejo green first, then the same walk on Claude with
   an owned Forgejo, then ChatGPT with GitHub; Claude with GitHub is not
   planned. ChatGPT with Forgejo is never blocked by anything: `qa walk
   temper RUNG --kind claude` (kinds `forgejo`, the default, and
   `claude`; `github` later) has its own two walk slots and its own
   logins, and a Claude walk's brief is
   `tmp/qa-focused/rung-<RUNG>-claude-brief.md`, the rung's with its
   step 2's model setup alone changed. Where an owner has both, a
   ChatGPT with Forgejo fix goes first.

**The clock:** each rung keeps `tmp/qa-focused/<rung>/loop.tsv` on the
logins' machine, one line per event (`time rung walk event note`; a
Claude walk's number written `claude-<n>`):
`walk-start`, `walk-end` (passed, or the step it stopped at), `filed`
(each finding, with its task), `walk-pause`, `fix-start`, `fix-pushed`,
`walk-resume`, `branch-walk-start`, `branch-walk-end`, `landed`, then the
next `walk-start`. `qa walk` writes its own events. design/ladder reads
the minutes between them at each check: the walk, the triage (walk-end
to fix-start), the fix (fix-start to fix-pushed), the landing
(fix-pushed to landed), and the gap to the next walk.

## 4. QA after landing

- **The mark:** an owner marks a landing commit a user meets through
  the product's tool with `QA:` ([owners.md](owners.md)). A commit that
  changes only tests, fixtures or figures carries none.
- **Choosing:** once `qa default temper on` is set (qa-flow.md 3; built
  10-27, agents 45c713a; the director sets it at the watch's restart),
  every marked commit landed after it runs, by ancestry, in landing
  order, batched (at most `QA_BATCH`), and the director's `qa decide ...
  backlog` is the exception; `qa candidates` lists only what no default
  covers. Until then the director decides at every wake, not only at
  its check: QA sat idle twice on 10-27 with nothing chosen. It runs
  what the rung's path and QA's findings' fixes landed, and backlogs
  repins and test-only commits.
- **Side by side:** up to `QA_SLOTS` passes at once. Of each pool, QA
  holds at most its size less `QA_LOGIN_RESERVE`, a stuck login counted
  against it, and its takes never queue, so a walk is never kept waiting
  behind QA (qa-flow.md 10.6).
- **Triage, by landing** (qa-flow.md 6; built 10-27, agents 66efd32,
  live on the logins' machine from its watch's restart after the roll):
  at a pass's end, each new finding goes by post to the active designer,
  else the active owner, of the mission that landed its commit
  (`landings landed REPO COMMIT` names it), with its triage line written
  once the post is accepted. The designer routes it on to its owner, or
  to another designer if it isn't theirs. The director gets the rest: a
  finding with no or an unknown commit, one not on `main` or with no
  landing, a mission it can't read, ambiguous metadata, `Concerns:
  security` or `lost data`, every stuck login, and every finding of a
  pass that ended before the restart. The director routes those as
  before: a finding on v0.1.0's happy path to its designer at once, any
  other to the backlog until v0.1.0 is out (the record's
  `director/direction.md`, priority 3). `qa triage` by hand still wins.
- **Rungs:** design/ladder opens the next rung with `qa rung` once the
  rung below is green.

## 5. The box under test

temper's binding, `docs/design/qa.md` 3, is the source; as of 10-27:

- **The model:** gpt-6.1-sol, effort high, output 32,000 (the user, 10-27
  10:2xZ).
- **Capacity:** the people's request table and the loads are raised
  (`people.requests`, `root.loads.loads`). QA runs 1008 and 1202 left the
  login inside a box whose table of 32 answers was full.
- **Budgets:** the project's period and role 0's allotment are raised,
  so that a budget never stops a walk.
- **Made unmissable** (temper 10286ac0f, 10-27 12:26Z): every change is
  made in the box's config after `init` and before its first start;
  three `jq -e` checks run before every start, and a failed one stops
  the pass as a setup to redo.
- **Give back before you break it** (design/ladder, temper 20d5bdd60,
  10-27 17:50Z, after QA 1659 left the login in a box for 46 minutes): a
  case that aborts serve, kills the box or risks its restore exports the
  held login first. The box's state stays in its store, and a restart
  needs no model. It imports a login again only if a later case needs
  the model. A login that a broken deployment still holds is the walk's
  finding, and its recovery is section 6.4's.

## 6. The held logins

### 6.1 The pool

- **Four ChatGPT logins,** `chatgpt`, `chatgpt-2`, `chatgpt-3` and
  `chatgpt-4`, at rest in `tmp/logins/` on hetzner6, in `logins`'
  custody (qa-flow.md 10.2 and 10.4). The user signed in the last three
  on 10-27 between 18:16 and 18:21Z.
- **Two Claude logins,** `claude` and `claude-2`, Claude Code's
  configuration directories, used in place (6.2a): the Claude walks'
  pool, one each for its two walk slots. The user signed in `claude` at
  18:56Z and `claude-2` at 19:2xZ on 10-27.
- **One account each:** an account signed in twice gives a second login
  but shares the first's usage limits, so a new held login is another
  account wherever one is to hand.
- **Two are the walks'** (section 3), the rest QA's (section 4): QA's
  passes take only a login free and claimed by no waiter (`--now`), and
  hold at most the pool's size less `QA_LOGIN_RESERVE`, a login one
  stranded included (qa-flow.md 10.6; agents 86f918b). `qa passes`
  shows each pool's size, QA's holding and the reserve.
- **A rung walk** is started by `qa walk REPO RUNG [--kind KIND]
  [--build REF] [--cap MINUTES]` (qa-flow.md 10.7; agents b844696):
  REF `main`, `origin/<branch>`, a bare `<branch>` on origin, or a
  unique commit, resolved before anything is taken (agents fe72017); it prints the walk's name, each login `NAME PATH` and its run.
  The default kind is ChatGPT+Forgejo's; `--kind claude` for Claude's.
  It paused, `qa walk REPO RUNG --resume NAME --build REF`, refused at
  once while its kind has no free slot or login. The service ends and
  pauses walks, and writes `walk-start`, `walk-pause`, `walk-resume` and
  `walk-end` on the rung's clock.
- **By hand,** a live story or a recovery takes through `qa take KIND
  [--login POOL] --as walk/KIND/WHAT [--note TEXT]`, admitted below the
  kind's cap, WHAT never a walk's name, and gives back with `qa give
  NAME --as walk/KIND/WHAT`; never `logins take`, which would count
  without being admitted. A queued `logins take` is dropped with
  `logins drop NAME|POOL [--any] --as HOLDER`, and a `--wait` that runs
  out drops itself.
- **Saturation:** the director reads `logins list` at each check. A
  login held most of the day while walks or passes wait is saturated,
  and the user hears of it.

### 6.2 A new held login

The user signs in; the agent never reads what it moves. On the logins'
machine, in a private directory `E`, with temper's binary copied in:

1. `temper init` with `E`'s config, data and cache; `temper box` on
   them, kept running (`systemd-run --user`); `temper ctl E/ctl sign-in
   -` fed the first line starting `http` after the box's notice "Open
   this link in a browser on this machine." (the line just after the
   notice is its second line, which ctl refuses).
2. The user keeps a tunnel open from their computer: `ssh -N -L
   1455:127.0.0.1:1455 free@<the logins' machine>`, with nothing else on
   their port 1455.
3. For each account, one at a time: `temper ctl E/ctl account connect 1
   --key enroll-N`, its address sent to the user, who opens it in a
   private window and signs in. The sign-in lapses after about ten
   minutes, and a browser returning later meets a reset connection: send
   a fresh one. Then `account list --until usable`, `account export
   ACCOUNT E/chatgpt-N` (the account whose `sign_in` is granted), and
   `logins add chatgpt-N E/chatgpt-N`.
4. Stop the box (SIGINT), check `logins list` shows each at rest and the
   box holds no granted source, then remove `E`.

`temper ctl` reads its standard input: in a script, give each call
`</dev/null`.

### 6.2a A new Claude login

`claude` is a program's login, Claude Code's configuration directory,
used in place and never moved (qa-flow.md 10.2; agents#11). A second
account makes the pool `claude`, `claude-2`: two Claude walks at once,
or one backing the other. The user, on the logins' machine, in a
terminal of their own (`ssh` to it), with another Claude account than
the first's:

1. `mkdir -m 700 ~/claude-qa-login-2`, then
   `CLAUDE_CONFIG_DIR=~/claude-qa-login-2 claude`, and `/login`: open
   the address it prints in a browser, sign in with that account, paste
   the code back, then `/exit`. No tunnel is needed.
2. The director, or an agent by path alone: `logins add claude-2
   ~/claude-qa-login-2`, then `logins list` shows it at rest.

### 6.3 Rolling the logins kit

- **Before** the kit with a change to `logins` reaches the logins'
  machine, no `logins take --wait` of the old code may be running
  (`pgrep -af 'logins take'`). Stop one that is, and ask it again after
  the roll.
- **After** a roll that changes `qa`, restart `agents-qa-watch.service`
  between passes, when `qa passes --running` is empty.
- **Rolling back** `qa` past b844696 needs no walk running or paused
  and no `walk/…` holder holding a login: the older service knows no
  walk.
- **Rolling back** `logins` past b3abf0e needs its queue drained and
  `tmp/logins/lock` and `tmp/logins/waiting.json` moved out first;
  rolling `qa` back past 8935bc9 needs the passes of the newer code
  drained, since the older service knows neither `qa-watch/<pass>`
  holders nor slots (agents b3abf0e, 8935bc9).

### 6.4 A stuck login

- **The alert** goes at once, before the pass's notice or the walk's
  end post, to the director and to the addresses in hetzner6's
  `~/.config/agents-qa/stuck` (design/upgrades-draft@hetzner6), once
  per stuck login, retried until accepted (qa-flow.md 10.3; agents
  5330c8b). Rolling `qa` back past 5330c8b drains pending alerts first.
- **One hand on the box:** the owner design/upgrades-draft names alone
  touches the deployment that holds the login (with none named, the
  director names one), and nobody restarts it meanwhile.
- **In place, never copied:** the deployment is diagnosed and recovered
  where it is. Its data is never copied, and no copy of it starts: a
  copy holds the same refresh token, and whichever refreshes first
  leaves the other dead (jig's `llm.md` 5.6). A diagnosis runs the
  deployment's own commit (a debug build with throwaway diagnostics
  allowed, never landed), one opener at a time.
- **The recovery:** the deployment's own build, with one setting
  raised (1008, 1202) or the cause's fix alone on top of that commit
  (1659, on a throwaway branch, never landed); never a later build, and
  no stored family moved. It runs once, alone, on the deployment's own
  config, data and cache. A setting raised for it
  goes into that deployment's config only, and is restored byte for
  byte after. Then the export, checked by `stat` (a regular file, 0600,
  its size) and its sha256, and the box stopped with the login at rest.
  A deployment whose export hangs is stopped at once and never
  restarted until the fix is in.
- **The director hears, and says yes only to a departure:** the owner
  posts the director when a recovery starts and when the login is
  back. A recovery that departs from this section (a later build, a
  copy, a second opener, anything it does not name) waits for the
  director's yes.
- **An export from a stopped deployment** is parked, not for v0.1.0
  (design/upgrades-draft, 10-27; jig's `llm.md` 10).
- **10-27's four,** each recovered:
  - 1008: the answers table was full;
  - 1121: the same, a near miss;
  - 1202: the box lacked QA's settings, and the give-back ran after the
    box had stopped;
  - 1659: a restore refused itself after repeated aborts (R8a's census
    reader).

## 7. Settings on the logins' machine

The director's, on hetzner6:

- **`agents-qa-watch.service`,** a user unit, which runs `qa watch`.
- **`machine.env`:**
  - `QA_SLOTS` 2, set once agents 86f918b runs there: every temper
    pass needs a login, and the reserve keeps the walks' two whatever
    the slots;
  - `QA_LOGIN_RESERVE` 2, the ChatGPT+Forgejo walks' two logins; 3 once
    ChatGPT+GitHub walks start, QA then yielding one (qa-flow.md 10.6);
  - `QA_WALK_KINDS`, by default `forgejo=2:chatgpt claude=2:claude`:
    each kind of walk (no hyphen in its name), its own walk slots and
    its pools, the first the default kind,
    ChatGPT+Forgejo's never taken by another; `github=1:chatgpt` added,
    with `QA_LOGIN_RESERVE` 3, when ChatGPT+GitHub walks start
    (qa-flow.md 10.6, 10.7). The tool refuses a reserve below the slots
    of the kinds that use a pool, in every `qa` command. A change
    reclaims nothing: it holds once holdings drain below it (`qa
    passes`). Each walk slot is a worktree with its own target, about 8
    GB, its first build cold;
  - `QA_BATCH` 5, `QA_CAP_MINUTES` 120 and `QA_INTERVAL_SECONDS` 300;
  - `QA_STOP_SECONDS` 50, the give-back wrapper's bound in a
    deployment's stop (qa-flow.md 10.5);
  - `QA_EVIDENCE_KIB` 2048, the copy's cap, and `QA_EVIDENCE_SECONDS`
    120, its push's bound (qa-flow.md 11);

  qa-flow.md 7 lists them with their defaults.
- **`~/.config/agents-qa/stuck`:** `design/upgrades-draft@hetzner6`;
  one address a line, `#` for comments, at most 16; absent or damaged,
  the alert goes to the director alone.
- **The open rung:** `qa rung temper real-model --login chatgpt`, the
  pool.
- **Default choosing:** `qa default temper on`, the director's, once
  agents 45c713a runs there: every marked commit landed after it runs
  by default (qa-flow.md 3); `qa default temper` shows it, `off` stops
  it. Rolling back past 45c713a needs an explicit `qa decide ... run`
  for each commit a default alone keeps chosen.
- **What lands next** (o/qa-evidence-keep): the evidence's keeping
  (section 8), once the director lifts its pause. Each
  landing's post says what hetzner6 needs. Landed: the pool (b3abf0e),
  passes side by side (8935bc9), the reserve and `--now` (86f918b), `qa
  walk` by kind with pause and resume, `qa take` and `logins drop`
  (b844696), marked commits by default (45c713a), triage by landing and
  `landings landed` (66efd32), the stuck alert (5330c8b). Rolling `qa` back past 66efd32 leaves
  saved routes unused: untriaged findings return to the director's
  queue.

## 8. The evidence

A pass's non-secret evidence goes into the private qa repository at its
end, and so does a rung walk's at its end (qa-flow.md 11; the user,
10-27, unpaused at 22:2xZ). It never holds a credential, a cookie, a
login or a sign-in link.

- **The scan** (agents 16c1655): `qa keep --check DIR` reads the
  allowlist (`brief.md`, `plan.md`, `notes.md`, `report.md`,
  `scripts/`, `evidence/`), applies the cap (`QA_EVIDENCE_KIB`), and
  names each refusal as `refused: PATH[, line N]: RULE`, never the
  text; it writes nothing. Every pass and walk runs it on its own
  scratch before its report's last write (roles/qa.md 2, step 5), and
  moves out of `evidence/` and `scripts/` what it names.
- **The copy** (agents 1d25b3b; qa 6d86471): at a pass's end, as the
  first step of its end, its allowlist goes to `passes/<pass>/` on
  fabrig-ai/qa's branch `evidence`, pushed with hetzner6's own key; its
  record's front matter names `evidence:` (the commit, `refused`, or
  `unknown` while it waits), and a refused line of the record's body is
  withheld as `(withheld: RULE)`. A refusal reaches the director once,
  each file, line and rule, and is mended on the machine by name and
  line, never by opening the file: the file moved out of `evidence/` or
  `scripts/`, or `sed -i 'Nd' FILE`; the next check tries again. A
  pass's scratch is deleted at 7 days only once its copy is kept or
  refused and its record names it. Rolling back: stop the service and
  keep the scratch of every pass whose copy waits, then revert.
- **Walks** (agents d9446fd): kept by the service at a walk's end,
  never at a pause, in `walks/<first start date>-<name>/`, its earlier
  attempts' reports with it; its `walk-end` post names the commit (`git
  show COMMIT:walks/NAME/`), the refusal, or the wait.
  A walk from before `qa walk` is kept by hand on hetzner6, `qa keep
  --walk YYYYMMDD-NAME DIR`: exit 0 prints the commit, 2 a refusal, 1
  run it again. The eight from before it (rung-a-1..5, rung-b0-1,
  github-land-1..2) were kept by the director on 10-27 at 23:5xZ.
- **Live since 10-28 00:0xZ** on hetzner6: the first check kept 25 of
  the 31 old passes and refused 6, the director's to mend by name and
  line or leave; the first pass after it, 20261028-0010-temper, names
  its evidence (f56a0d5).

## 9. Open

- **The GitHub and Claude walks** of rungs A and B0 wait for the user's
  word. So do the ladder's paused owners: rung B2, the Claude pair, and
  GitHub's remaining tasks.
- **A held Claude login,** `claude`, is at rest in `logins` since 10-27
  18:5xZ (the user signed Claude Code in, agents#11): a program's login,
  used in place (qa-flow.md 10.2). The Claude walks it serves wait for
  the user's word, as above.

## 10. Changes

Newest last, times UTC.

- 10-26 18:35Z: QA's design, the user's (agents ed8be8c, temper
  507cb216); passes climb the rungs to real backends.
- 10-27 01:55Z: the real-model rung opened.
- 10-27 10:2xZ: ChatGPT with an owned Forgejo; the box on gpt-6.1-sol
  at high; budgets raised if needed (the user).
- 10-27 10:4xZ: the ladder climbed one rung at a time under the soft
  pause (the user).
- 10-27: QA's evidence kept in the qa repository (the user).
- 10-27 12:26Z: the box's settings and checks made unmissable (temper
  10286ac0f).
- 10-27 13:31Z: the give-back runs before the box is signalled (agents
  a2de94db0).
- 10-27 14:11Z: an export is admitted whole, so a full table can't
  strand a login (jig 2c73bce26, temper fbf314eec).
- 10-27 14:35Z: the director chooses QA's commits at every wake.
- 10-27 17:4xZ: three more held ChatGPT logins (the user); configuring's
  draft exempt from the pause.
- 10-27 17:50Z: give back before you break it (temper 20d5bdd60).
- 10-27 18:05Z: `logins` pools (agents b3abf0e); 18:16-18:21Z,
  chatgpt-2, -3 and -4 signed in.
- 10-27 18:2xZ: rung walks first, two logins reserved for them; QA
  after landing made mechanical; the walk loop tightened (the user).
  Designed in agents 580aadaff; passes side by side landed in 8935bc98d.
- 10-27 18:4xZ: a walk pauses at a blocking finding and resumes from the
  same state (the user); qa-flow.md 10.7 (agents 209b58f, 03a0f49).
- 10-27 18:5xZ: this file (the user), with the walk loop moved here from
  design/ladder's notes.
- 10-27 18:5xZ: sections 6 and 7 brought to what is built and what each
  coming piece adds: the reserve and `--now`, `qa walk`, `logins drop`,
  the stuck alert, `QA_STOP_SECONDS`, the rollbacks (design/qa-evidence).
- 10-27 19:0xZ: 6.4 corrected to the day's recoveries: a setting raised
  or the fix alone on the deployment's own commit, in place and never
  copied, on the director's yes; the hand on the box the one
  design/upgrades-draft names (design/upgrades-draft).
- 10-27 19:0xZ: a recovery by 6.4 needs no yes: the director hears when
  it starts and when the login is back, and a departure from 6.4 waits
  for its yes (the director, the user wanting it out of QA's routine).
- 10-27 18:5xZ: the held Claude login in custody (agents#11, the user's sign-in); its walks wait for the user's word.
- 10-27 19:0xZ: the reserve and `--now` landed (agents 86f918b): QA holds
  at most two of the four logins; `QA_SLOTS` 2 once it runs on hetzner6
  (design/qa-evidence).
- 10-27 19:0xZ: each rung walks ChatGPT+Forgejo, then Claude+Forgejo, then ChatGPT+GitHub; ChatGPT+Forgejo never blocked; two more walk slots for the others (the user).
- 10-27 19:1xZ: walk kinds with their own slots (`QA_WALK_KINDS`
  `forgejo=2 claude=2`), a pool shared out by caps, a second Claude
  login's steps (6.2a; qa-flow.md 10.6, 10.7; the user, design/qa-evidence).
- 10-27 19:0xZ: per rung, ChatGPT+Forgejo, then Claude+Forgejo, then
  ChatGPT+GitHub, each kind with its own walk slots (the user; agents
  5bc4ad7): section 3, item 7.
- 10-27 19:2xZ: `claude-2` signed in, two Claude logins; 6.1's pool list
  (design/qa-evidence).
- 10-27 19:5xZ: a take by hand admitted by `qa take` below its kind's
  cap, after W (qa-flow.md 10.6; o/qa-evidence-keep's finding); until
  then, `qa passes` read first (design/qa-evidence).
- 10-27 20:4xZ: a resumed walk raises a new binary's memory figure at the
  restart, as a setup step (section 3, item 4; design/ladder).
- 10-27 20:4xZ: `qa walk` by kind with pause and resume, `qa take` and
  `qa give`, `logins drop` landed (agents b844696); 6.1, 6.3 and 7 as
  built (design/qa-evidence).
- 10-27 20:4xZ: walks start with `qa walk`, by-hand takes with `qa take` (agents
  b844696; section 3's preamble).
- 10-27 21:1xZ: marked commits by default landed (agents 45c713a); `qa
  default temper on` the director's once it runs on hetzner6
  (design/qa-evidence).
- 10-27 21:1xZ: findings routed by the landing of their commit (agents
  66efd32); passes ended before it stay the director's
  (design/qa-evidence).
- 10-27 21:2xZ: QA's choosing by default (agents 45c713a) and triage by landing (agents 66efd32) built; section 4 updated (the director).
- 10-27 21:4xZ: the stuck alert landed (agents 5330c8b): the last of
  the day's exempt QA kit (design/qa-evidence).
- 10-27 22:3xZ: `qa walk` resolves `--build` first and takes a bare
  branch on origin (agents fe72017; design/ladder's note).
- 10-27 23:1xZ: the evidence's scan and `qa keep --check` landed (agents
  16c1655); section 8 as built (design/qa-evidence).
- 10-27 23:2xZ: passes' evidence kept on qa's branch `evidence` (agents
  1d25b3b, qa 6d86471), live once hetzner6's watch restarts; old walks
  the director's to keep by hand (design/qa-evidence).
- 10-28 00:0xZ: walks' evidence kept at their end (agents d9446fd); the
  three evidence pieces in, live once hetzner6's watch restarts
  (design/qa-evidence).
- 10-28 00:0xZ: QA's evidence live on hetzner6; the old walks kept by
  hand, 25 old passes kept and 6 refused (design/qa-evidence).
