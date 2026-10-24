# QA in a milestone

Provisional, 2026-10-24. The QA pass: a QA agent ([qa.md](qa.md)) that
a milestone's owner starts on its part, which writes adversarial tests
of what the milestone has landed and reports them to that owner. The
owner's side, when to start one and how to judge what it finds, is
owners.md 4.6.

## 1. In one page

- **Started by the milestone's owner,** of App, UI or Infra, when it
  judges a pass warranted: most often at the milestone's end, beside
  the next milestone, or on the set queued for landing (landing-flow.md
  8). The owner may resume it after more has landed, and stops it.
- **Tests at whatever level it wants,** that don't run at gates (the
  user, 10-23): a kit's world, temper's real loop or process tier, a
  browser story. Each goes in the highest layer that can express it.
- **A suite apart.** Its test binaries are named `qa_<area>`, run by the
  repository's `qa` profile, which the gate builds and does not run, and
  no test-time ceiling counts (owners.md 4.6).
- **It reports to the owner,** who judges each failure: a bug to fix
  now, a gap kept as `#[ignore]`, a test that misread the design
  (owners.md 4.6).

## 2. The pass

- **Its brief** names the part and the design sections, the commits on
  `main` or the set's branches it tests, the repository and its `qa`
  profile, its worktree and notes (`qa/` beside the owner's), its effort
  and budget. Never the cases.
- **It reads** the design sections, and the public surface of the world
  or harness it writes in: its builders, its fakes' scenarios, its
  stories' steps, as the project's testing document names them
  (temper's `docs/design/domain/testing.md`). Never the code under test
  or its tests.
- **It writes** its tests on a branch of its own in its worktree, runs
  them through `heavy cargo nextest run --profile qa`, and commits them,
  passing or failing. It never lands: its owner lands them with the
  pass's fixes (owners.md 4.4).
- **A failing test is a finding** (qa.md 3), named by the test; the
  report says which fail, and why the agent thinks each does.
- **Resumed,** it tests what has landed since, and reruns its earlier
  tests on it.
