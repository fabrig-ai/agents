# QA passes

Provisional, 2026-10-26. A QA pass is a Codex session that `qa watch`
starts on a `main` that after landing has cleared, to test what a batch
of landed commits changed for a user, by driving the product the way
its users' agents do ([qa-flow.md](../docs/design/qa-flow.md) 4 and
5). It reads this file, then its brief, which names the repository,
the commits with their `QA:` trailers, the `main` and its checkout (its
working directory), its scratch directory, its wall cap and its
report's path.

## 1. In one page

- **A plan before anything runs,** in the scratch directory: for each
  commit, the happy path, then two to four tricky cases, each with the
  outcome it expects (section 2).
- **The product's own commands set it up,** as its guide says, on the
  product's fake backends.
- **The product's tool alone drives it:** the tool its users' agents
  use, for temper `temper ctl`, whose `help` is temper's guide for
  agents. Outcomes are checked through it too.
- **The report** gives each case's outcome, each finding with the
  commands that reproduce it, what a helper could automate, and what
  was blocked (section 3).
- **It changes nothing but its scratch:** no commit, push, landing,
  record or post, and the checkout's tracked files stay as they are.

## 2. The steps

1. **Read** each commit's diff (`git show`), its trailer, and the
   designs it touches; then the product's guide: for temper,
   `docs/guide/`, and `temper ctl help` once it is built.
2. **Plan,** in `plan.md` in the scratch directory, before running
   anything. For each commit: the happy path, then two to four tricky
   cases you pick (an error, a retry, odd input, a thing done twice or
   two at once), each with the outcome you expect. Write the
   expectation before the run, never after.
3. **Build and set up.** Build the product at the checkout through
   `heavy`, at background weight: `HEAVY_CLASS=background heavy
   COMMAND`, the narrowest build that gives the binaries the guide
   needs, once. Build in the checkout, whose `target/` the service keeps
   warm between passes (no `--target-dir`, no `CARGO_TARGET_DIR`); copy
   or install the binaries into the scratch directory, never into
   `~/.local`. Set up a deployment with the product's own commands, as
   its guide says, in a directory of the scratch, on its fake backends:
   for temper, `temper box --fake-backends` as `docs/guide/box.md`'s
   last section says, then `temper ctl`'s sign-in with the link it
   prints. Cases that don't disturb each other share one deployment; a
   case that would disturb others gets a fresh one.
4. **Drive each case through the tool alone,** and check its outcome
   through the tool. Where the tool can't show an outcome (a branch on
   the forge), you may read the backend, and say so in the report: the
   tool's not showing it is a finding in itself. Never act on the
   product any other way: not through its store, its HTTP API, or a
   fake's internals.
5. **Report** (section 3), then stop every deployment you started.

## 3. The report

Written whole over the report's path, and kept current as you go: past
the cap the session is stopped, and what the file holds then is the
report. At most 7 KiB; the service adds its front matter. Its shape,
which the tools read:

```
## Cases

### <short commit> <its subject>
- <what it tried>: expected <...>; saw <...>; ok
- <what it tried>: expected <...>; saw <...>; finding 1

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
  uses its fakes alone: no real forge, model or account.
- **Builds** go through `heavy` at background weight, never `--gate`,
  and nothing runs a repository's gate or after landing's tier.
