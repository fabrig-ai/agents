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
working, wide once, and nothing twice without a reason.

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

Once, when the set's focused tests pass:

1. **Format:** `cargo fmt`, directly, not through `heavy`: it builds
   nothing.
2. **Widen the tests:** the whole package (`heavy cargo nextest run -p
   PKG`), where sibling tests in the same binary run too. Where the
   change reaches a public item, a feature, or a shared world, fake or
   harness, add its direct dependents (`cargo tree -i PKG --depth 1`
   lists them, and builds nothing) in the same command:
   `-p PKG -p DEP ...`.
3. **Lint:** `heavy cargo clippy --workspace --all-targets -- -D
   warnings`, the gate's native lint. It also compiles every crate with
   the features the workspace enables, so it catches a dependent or a
   path under a feature that the tests above didn't build.
4. **Doc examples:** where it changed one, `heavy cargo test --doc -p
   PKG`. temper's gate doesn't run them.

Steps 2 to 4 may go in one command, so that they wait once:
`heavy bash -c 'cargo nextest run ... && cargo clippy ...'`. After a
finding, it fixes it, runs the focused test the fix touches, and
reruns only the step the finding came from. The gate's other checks
(the wasm lints, the fuzzy and browser profiles, the builds for the
browser) are the landing's (owners.md 4.4), unless the task names them.
It never runs `scripts/check.sh`.

## 3. The queue

- **One command at a time.** Two at once take two of the machine's
  slots, and suites that share ports or fixtures fail each other.
- **Where the code isn't Rust** (a script, a Python tool), the same
  loop holds with its own tools: the narrowest check after each change,
  the wide one once.

## 4. The report

Besides what the task asks, the report says what section 2 ran and
what each step found, how many tests ran, and what wasn't run and why:
the gate's other checks, left to the landing, and any test it couldn't
run.
