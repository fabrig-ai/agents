# Implementers

Provisional, 2026-10-24. How an implementer works: the Codex run that
takes one task file, in a worktree of its own, and writes, builds,
tests and repairs until the task is done. Every implementer reads this file before its
task, and outside agents, section 1 of skein's `docs/foundation/`
rules, `programming-model.md` and `testing-strategy.md`: a later
section only where the task names it. The task holds what is
particular to it; where it departs from this file, it says why, and
the task wins: a stability trial, a measurement, a profile the change
needs.

**Why.** Every build shares the machine's one `heavy` queue, so narrow
while working, run the focused suite once, and nothing twice without a
reason.

## 1. After each change

- **The narrowest test that checks it,** in the package that holds the
  test, which is not always the changed crate:
  `heavy cargo nextest run -p PKG --test BINARY -E 'test(=NAME)'`, or
  `--lib` for a unit test. `--test` and `--lib` cut what is built. A
  filter (`-E`) alone cuts only what runs: every test binary in the
  package is still built and linked, twelve for one test in a 10-24
  experiment.
- **Finding it.** `rg` for the changed items' uses, tests included;
  then read the test's assertions before choosing it.
- **Check the count.** A run that selected no test proves nothing, and
  nextest exits 4 when none matched. A test outside the default
  profile needs its `--profile`.
- **A compile repair** may use `heavy cargo check -p PKG --tests` while
  errors last. Its outputs aren't the test build's, so it doesn't go
  before every run.
- **A failure is read** in its log, whose path `heavy` prints, before
  anything reruns. An unchanged command doesn't rerun, except once after
  exit 137: out of memory, the kernel kills an agent's build before a
  landing's work (build-infrastructure.md, 2).
- **Inputs stay still** while a command waits or runs: no edit to what
  it builds or tests until it reports. A submission to take back is
  cancelled with `heavy --cancel TOKEN`, from the worktree that
  submitted it, never with pueue.

## 2. When a set of changes is done

Optimistic (the user, 2026-10-25): the landing's gates run the wide
checks (the workspace's lints and the focused and fuzzy suites), and
what fails there comes back as a repair. The slow tiers run after
landing. So, once, when the set's narrow tests pass:

1. **Format:** `cargo fmt`, directly, not through `heavy`: it builds
   nothing.
2. **Clippy on the changed packages:** `heavy cargo clippy -p PKG
   [-p PKG ...] --all-targets -- -D warnings`, one command per
   repository, naming every package the set changed there, its tests
   included. A finding is fixed, and only this command reruns. Why
   (the user, 2026-10-25): with the lints left to the gate, a test's
   disallowed method stopped a whole set, and forgejo-elsewhere-3's M4
   spent a land-set run and a repair on it.
3. **The focused suite, unless the task waives it:** `heavy cargo
   nextest run --workspace --no-fail-fast`, the default profile: every
   test but the fuzzy ones and the tiers'. Its builds are the gate's
   first, from the shared store. `--no-fail-fast`, so that one failure
   leaves the rest run: in a 10-25 trial a fail-fast stop left 4,690 of
   6,552 tests unrun.

**A failure the set didn't cause**, in a test its change doesn't reach
(`rg` finds none of the changed items on its path, and its log names
none), runs once alone, as section 1 runs a test. Passing alone, it is
a flake: the report names it with both logs, and the suite doesn't
rerun. Failing alone, it is a question (section 4). Why: in that trial a
skein world's 5 ms deadline failed while two suites shared the machine,
and passed alone and at the gate.

Nothing else: not the fuzzy, browser or `qa` profiles, the process or
live tiers, the workspace's clippy, the wasm lints or the doc examples,
and never `scripts/check.sh`, `scripts/after-landing.sh`, `land` or
`land-set`. They are the gates' and the slow tiers', and a repair's
(below), unless the task names one: a task may name `land-set --prove`,
which rebases, repins and gates the set without pushing it
(landing-flow.md 9.1).

**A repair** of what a gate found runs the failing tests alone, in
their profile (`--profile fuzzy -E 'test(=NAME)'`), or the lint that
failed, and the narrowest tests its fix touches: the gate's next run
is the wide check. A browser test runs alone through
`scripts/browser.sh -E 'test(=NAME)'`, which builds the bundle it
needs first. After a finding, it fixes it, runs the narrowest
test the fix touches, and reruns only the step the finding came from.

## 3. The queue

- **One command at a time.** Two at once take two of the machine's
  slots, and suites that share ports or fixtures fail each other.
- **Where the code isn't Rust** (a script, a Python tool), the same
  loop holds with its own tools: the narrowest check after each change,
  and the wide one is the gate's.
- **Throwaway code** (a probe, a driver for one measurement) lives in
  the worktree, untracked, and is deleted before the report: `land`
  refuses an untracked file. Never in `tmp/`, never beside the kit.

## 4. The report

The report is written whole over the file at the path the run is
given, whatever it holds: its first line is read first. Besides what the
task asks, it says what it ran (section 1's tests, the focused suite, a
repair's checks) and what each found, how many tests ran, and any test
it couldn't run. The gates' checks need no mention: they are the
landing's. **On a doubt** it stops: the report's first line is the
question, starting `Question:`, with the options and a recommendation.
It never improvises across a boundary. A tool the task lacks is such a
question, never a script of its own.

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
