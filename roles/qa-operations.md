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
  the box's owned Forgejo, and no walk on fakes. GitHub and Claude come a
  rung behind, on the user's word.
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
18:4xZ). The launcher, `qa walk`, is qa-flow.md 10.7; until it lands, a
walk takes its login with `logins take chatgpt --any`, gives it back by
the name it was given, and writes its clock by hand.

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
   on from the step it paused at. A fix that moves a stored family
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

**The clock:** each rung keeps `tmp/qa-focused/<rung>/loop.tsv` on the
logins' machine, one line per event (`time rung walk event note`):
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
- **Choosing:** once `qa default temper on` is set (qa-flow.md 3), every
  marked commit landed after it runs, in landing order, batched (at most
  `QA_BATCH`), and the director's `qa decide ... backlog` is the
  exception. Until then the director decides at every wake, not only at
  its check: QA sat idle twice on 10-27 with nothing chosen. It runs
  what the rung's path and QA's findings' fixes landed, and backlogs
  repins and test-only commits.
- **Side by side:** up to `QA_SLOTS` passes at once. Of each pool, QA
  holds at most its size less `QA_LOGIN_RESERVE`, a stuck login counted
  against it, and its takes never queue, so a walk is never kept waiting
  behind QA (qa-flow.md 10.6).
- **Triage:** once triage by landing is built (qa-flow.md 6), the tool
  posts each finding to the designer of the mission that landed its
  commit. The director gets a finding with no commit on `main`, or with
  no mission it can read, one that concerns security or lost data, and
  every stuck login. Until then, the director routes them the same way:
  a finding on v0.1.0's happy path goes to its designer at once, any
  other to the backlog until v0.1.0 is out (the record's
  `director/direction.md`, priority 3).
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
- **One account each:** an account signed in twice gives a second login
  but shares the first's usage limits, so a new held login is another
  account wherever one is to hand.
- **Two are the walks'** (section 3), the rest QA's (section 4).
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

### 6.3 Rolling the logins kit

- **Before** the kit with a change to `logins` reaches the logins'
  machine, no `logins take --wait` of the old code may be running
  (`pgrep -af 'logins take'`). Stop one that is, and ask it again after
  the roll.
- **After** a roll that changes `qa`, restart `agents-qa-watch.service`
  between passes, when `qa passes --running` is empty.

### 6.4 A stuck login

- **The alert** goes at once to the addresses in hetzner6's
  `~/.config/agents-qa/stuck` (design/upgrades-draft@hetzner6) and to
  the director.
- **One hand on the box:** design/upgrades-draft's owner alone touches
  the deployment that holds the login, and nobody restarts it
  meanwhile.
- **The recovery:** the deployment's own build plus the fix alone (no
  stored family moved), run once, alone, on its own config, data and
  cache. A setting raised for it goes into that deployment's config
  only, and is restored byte for byte after. Then the export, checked
  by `stat` (a regular file, 0600, its size) and its sha256. A
  deployment whose export hangs is stopped at once and never restarted
  until the fix is in.
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
  - `QA_SLOTS`: 1 until the reserve lands, then 2, so QA holds two of the
    four logins;
  - `QA_LOGIN_RESERVE` 2 and `QA_WALK_SLOTS` 2, the walks';
  - `QA_BATCH` 5, `QA_CAP_MINUTES` 120 and `QA_INTERVAL_SECONDS` 300;
  - `QA_EVIDENCE_KIB` 2048.

  qa-flow.md 7 lists them with their defaults.
- **`~/.config/agents-qa/stuck`:** `design/upgrades-draft@hetzner6`.
- **The open rung:** `qa rung temper real-model --login chatgpt`, the
  pool.
- **Once it is built:** `qa default temper on`.

## 8. The evidence

A pass's non-secret evidence goes into the private qa repository at its
end, and a walk keeps its own with `qa keep --walk` (qa-flow.md 11; the
user, 10-27). It never holds a credential, a cookie, a login or a
sign-in link. The scan is built, and the keeping waits under the soft
pause. Meanwhile a walk's evidence stays in its directory on the logins'
machine.

## 9. Open

- **The GitHub and Claude walks** of rungs A and B0 wait for the user's
  word. So do the ladder's paused owners: rung B2, the Claude pair, and
  GitHub's remaining tasks.
- **A held Claude login** waits for the user's sign-in.

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
