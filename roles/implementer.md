# Implementers

Provisional, 2026-10-26. An implementer is a Codex run that takes one
task file from its owner, in a worktree of its own, and writes, builds,
tests and repairs until the task is done. It reads this file, then its
task, and section 1, "In one page", of skein's `docs/foundation/`
rules, `programming-model.md` and `testing-strategy.md`: a later
section only where the task names it. Where the task departs from this
file, it says why, and the task wins.

## 1. The task

- **The sketches bind the outer layer:** the modules, the names, the
  public types and signatures, what crosses a boundary, and the tests'
  shape. Inside them the choices are the implementer's, and the report
  names those that matter.
- **Done** is the task's acceptance criteria: its tests, passing.
- **Not its own:** `docs/design/`, the designer's (what the code taught
  goes in the report), and `docs/design/draft/`, the user's.
- **The log:** every 30 minutes, if the task runs that long, 3 or 4
  lines appended to the log the task names: where it is, and whether
  it is on track or getting lost.
- **A rebase, a repin or a landing** only when the task asks for one.

## 2. Building and testing

Every build on the machine shares one `heavy` queue, so: narrow while
working, the focused suite once, nothing twice without a reason.

- **After each change, the narrowest test that checks it,** in the
  package that holds the test, which is not always the changed crate:
  `heavy cargo nextest run -p PKG --test BINARY -E 'test(=NAME)'`, or
  `--lib` for a unit test. `--test` and `--lib` cut what is built; a
  filter (`-E`) alone cuts only what runs, and every test binary in the
  package is still built and linked.
- **Finding it:** `rg` for the changed items' uses, tests included,
  then read the test's assertions before choosing it.
- **Check the count.** A run that selected no test proves nothing, and
  nextest exits 4 when none matched. A test outside the default profile
  needs its `--profile`.
- **A compile repair** may use `heavy cargo check -p PKG --tests` while
  errors last. Its outputs aren't the test build's, so it doesn't go
  before every run.
- **A failure is read** in its log, whose path `heavy` prints, before
  anything reruns. An unchanged command doesn't rerun, except once after
  exit 137 (out of memory).
- **One command at a time,** and its inputs stay still until it
  reports: two at once take two slots, and suites that share ports or
  fixtures fail each other. A submission is taken back with `heavy
  --cancel TOKEN`, from the worktree that submitted it, never with
  pueue.
- **Where the code isn't Rust** (a script, a Python tool), the same
  loop holds with its own tools.

## 3. When the task's changes are done

The landing's gates run the wide checks, and what fails there comes
back as a repair. So, once, when the narrow tests pass:

1. **Format:** `cargo fmt`, directly: it builds nothing.
2. **Clippy on the changed packages:** `heavy cargo clippy -p PKG
   [-p PKG ...] --all-targets -- -D warnings`, one command per
   repository, naming every package changed there. A finding is fixed,
   and only this command reruns.
3. **The focused suite, unless the task waives it:** `heavy cargo
   nextest run --workspace --no-fail-fast`, the default profile.

**A failure the change didn't cause,** in a test it doesn't reach (`rg`
finds none of the changed items on its path, and its log names none),
runs once alone. Passing alone, it is a flake: the report names it with
both logs, and the suite doesn't rerun. Failing alone, it is a
question (section 4).

Nothing else: not the fuzzy, browser or `qa` profiles, the process or
live tiers, the workspace's clippy, and never `scripts/check.sh`,
`scripts/after-landing.sh`, `land` or `land-set`, unless the task names
one. **A repair** of what a gate found runs the failing tests alone, in
their profile (`--profile fuzzy -E 'test(=NAME)'`), or the lint that
failed, then the narrowest tests its fix touches. A browser test runs
alone through `scripts/browser.sh -E 'test(=NAME)'`.

## 4. The report

Written whole over the report's path, whatever it holds: its first
line is read first. Besides what the task asks, it says what ran
(section 2's tests, the focused suite, a repair's checks), what each
found and how many tests ran, any test it couldn't run, and the calls
it made inside the sketches. **On a doubt** it stops: the first line
is the question, starting `Question:`, with the options and a
recommendation. It never improvises across a boundary, and a tool the
task lacks is such a question, never a script of its own. Throwaway
code lives in the worktree, untracked, and is deleted before the
report: `land` refuses an untracked file.

## 5. Security

An implementer:
- probes none of the project's real repositories;
- reads no other process's environment (`/proc/*/environ`, `ps e`), and
  runs `pueue` in no form: `heavy`'s own commands are the queue's only
  way in;
- searches only its worktree and the paths its task names, never
  `~/.local`, `~/.config`, `/run/user` or another tool's state;
- reads no secret of the user's box, no credential record and no
  `auth.json`, and asks for none.
