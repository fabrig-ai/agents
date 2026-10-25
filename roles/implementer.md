# Implementers

Provisional, 2026-10-24. How an implementer works: the Codex run that
takes one task file from its owner ([owners.md](owners.md) 4.2 and
4.3), in a worktree of its own, and writes, builds, tests and repairs
until the task is done. Every implementer reads this file before its
task. The task holds what is particular to it; where it departs from
this file, it says why, and the task wins: a stability trial, a
measurement, a profile the change needs.

**Why.** Every build and test goes through
`heavy`, one queue for the whole machine. Over 741 runs from 10-22 to
10-24, implementers' commands ran for 43 hours and waited for 104:
each command one implementer submits, every other waits behind. The
hours went to repeats: clippy rerun 833 times on what it had already
linted (4.2 hours running), fmt waiting 74,000 seconds to run for
seconds, and workspace suites rerun after small fixes. So: narrow while
working, the focused suite at most once, and nothing twice without a
reason. The wide checks are the landing's gates (section 2).

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
  anything reruns. An unchanged command doesn't rerun.
- **Inputs stay still** while a command waits or runs: no edit to what
  it builds or tests until it reports.

## 2. When a set of changes is done

Optimistic (the user, 2026-10-25): the landing's gates run every wide
check, and what fails there comes back as a repair. So, once, when the
set's narrow tests pass:

1. **Format:** `cargo fmt`, directly, not through `heavy`: it builds
   nothing.
2. **The focused suite, if it wants one:** `heavy cargo nextest run
   --workspace`, the default profile: every test but the fuzzy ones and
   the tiers', under 20 seconds of tests. Its builds are the gate's
   first, from the shared store.

Nothing else: not the fuzzy or browser profiles, the process, live or
QA tiers, clippy, the wasm lints or the doc examples, and never
`scripts/check.sh`. They are the gates' (owners.md 4.4), unless the
task names one.

**A repair** of what a gate found is where another suite runs: first
the failing check alone (the failing tests in their profile, as
`--profile fuzzy -E 'test(=NAME)'`, or the lint that failed), then that
whole profile or lint once it passes, then the focused suite. After a
finding, it fixes it, runs the narrowest test the fix touches, and
reruns only the step the finding came from.

## 3. The queue

- **One command at a time.** Two at once take two of the machine's
  slots, and suites that share ports or fixtures fail each other.
- **Where the code isn't Rust** (a script, a Python tool), the same
  loop holds with its own tools: the narrowest check after each change,
  and the wide one is the gate's.

## 4. The report

Besides what the task asks, the report says what it ran (section 1's
tests, the focused suite, a repair's checks) and what each found, how
many tests ran, and any test it couldn't run. The gates' checks need no
mention: they are the landing's.
