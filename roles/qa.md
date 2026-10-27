# QA passes

Provisional, 2026-10-26. A QA pass is a Codex session that `qa watch`
starts on a `main` that after landing has cleared, to test what a batch
of landed commits changed for a user, by driving the product the way
its users' agents do ([qa-flow.md](../docs/design/qa-flow.md) 4 and
5). It reads this file, then its brief, which names the repository,
the commits with their `QA:` trailers, the `main` and its checkout (its
working directory), its scratch directory, its wall cap and its
report's path; then the product's binding, `docs/design/qa.md` in its
repository, which says how a pass sets it up, whom it plays and what
makes a finding there.

## 1. In one page

- **A plan before anything runs,** in the scratch directory: for each
  commit, the happy path, then two to four tricky cases, each with the
  outcome it expects (section 2).
- **The product's own commands set it up,** as its binding says, on the
  rung the brief names: its fakes, or a real backend.
- **A held login is borrowed:** moved into the deployment, and moved
  back to its path by the give-back file before the deployment stops,
  whatever stops it (section 2, step 3; qa-flow.md 10.3).
- **It works as the product's users' agents do:** the product's tool for
  the product (for temper, `temper ctl`, with `temper help` and
  `temper ctl help` for its documentation), and tools of its own for
  the systems the product works with, as the binding names them (for
  temper's forges, `curl`).
  Outcomes are checked on both sides: what the product says, and what
  the backend shows.
- **The report** gives each case's outcome, each finding with the
  commands that reproduce it, what a helper could automate, and what
  was blocked (section 3).
- **It changes nothing but its scratch:** no commit, push, landing,
  record or post, and the checkout's tracked files stay as they are.

## 2. The steps

1. **Read** each commit's diff (`git show`), its trailer, and the
   designs it touches; then the product's binding and its documentation:
   for temper, `docs/design/qa.md`, `docs/help/`, `temper help` and
   `temper ctl help`.
2. **Plan,** in `plan.md` in the scratch directory, before running
   anything. For each commit: the happy path, then two to four tricky
   cases you pick (an error, a retry, odd input, a thing done twice or
   two at once), each with the outcome you expect. Write the
   expectation before the run, never after.
3. **Build and set up.** Build the product at the checkout through
   `heavy`, at background weight: `HEAVY_CLASS=background heavy
   COMMAND`, the narrowest build that gives the binaries the
   documentation needs, once. Build in the checkout, whose
   `target/` the service keeps warm between passes (no `--target-dir`, no `CARGO_TARGET_DIR`); copy
   or install the binaries into the scratch directory, never into
   `~/.local`. Set up a deployment with the product's own commands, as
   its binding says for the brief's rung, in a directory of the
   scratch: for temper's fakes, `temper box --fake-backends` as
   `docs/help/box.md`'s section on them says; for its real ones, the
   help's walk from empty directories. Then `temper ctl`'s sign-in
   with the link it prints, and the forge's hands from the files the box
   names (temper's `docs/design/qa.md`, 4). Cases that don't disturb
   each other share one deployment; a case that would disturb others
   gets a fresh one.

   **A held login,** when the brief names one, the service has taken
   for you: it rests at the path the brief gives. Move it into your
   deployment as the binding says (for temper, `temper ctl account import`; a
   program's login, a directory, is used in place, never moved),
   and at once write the give-back file the brief names: an executable
   that moves each login back to its path by the product's export (for
   temper, `temper ctl DIR account export N PATH`), safe to run twice, every
   program in it named by its absolute path: it runs outside your
   shell. Your
   unit runs it when it stops, whatever stops it, so keep it right as
   you go: a second deployment that takes the login over takes the file
   over too. Never run `logins`, and never read, copy or print a login.
4. **Drive each case as the product's users' agents do,** and check its
   outcome on both sides: the product's account through its tool, and
   the backend's through the tools the binding names. A finding is the
   product not saying where to look, the two accounts disagreeing, the
   product stale past its bound, documentation that doesn't get you
   there, or the product's words wrong (temper's binding, 6); having read
   the backend is none. What the product's `STATUS.md` lists as not yet
   built goes under Blocked. Never act on the product any other way:
   not through its store, its HTTP API, or a fake's internals; and act
   on a backend only as a case's plan says, with the hands the binding
   gives.
5. **Report** (section 3). Then give each held login back: run the
   give-back file, and check each path by `stat` alone (a regular file,
   `0600`, not empty). Then stop every deployment you started. A login
   not back is the report's first line, with what the export said, and
   its deployment stays as it is for the service to report.

## 3. The report

Written whole over the report's path, and kept current as you go: past
the cap the session is stopped, and what the file holds then is the
report. At most 7 KiB; the service adds its front matter. Its shape,
which the tools read:

```
## Cases

### <short commit> <its subject>
- <what it tried>: expected <...>; saw <the product's account>; <the backend's>; ok
- <what it tried>: expected <...>; saw <the product's account>; <the backend's>; finding 1

## Findings

### 1. <one line: what is wrong>
Commit: <the short commit it most likely comes from>
Reproduce, from a fresh deployment:
    <the commands>
Expected: <...>
Saw: <...>

## Automation
- <what was done by hand that a helper would make faster or surer>: <minutes it took>

## Blocked
- <what could not be tested>: <why>
```

- **Findings** are numbered from 1, each a level-3 heading as above;
  with none, the section says `None.`
- **Automation** names setup repeated, waits written, checks scripted,
  each with its time: these lists decide which helpers get built.
- **Blocked** includes a build or setup that failed, with the commands
  and the error's last lines.

## 4. Rules

- **Its scratch directory** holds its plan, notes, deployments and
  throwaway scripts; nothing goes elsewhere in `~/src/rust/tmp/`.
- **The security rules** are an implementer's
  ([implementer.md](implementer.md) 5), and the product's deployment
  uses its fakes alone, unless the brief names a real rung: then its
  accounts are used by path, never read, and given back before the
  deployment stops (section 2, steps 3 and 5).
- **Builds** go through `heavy` at background weight, never `--gate`,
  and nothing runs a repository's gate or after landing's tier.
