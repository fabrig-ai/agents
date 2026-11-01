# Request: starvation stays green in precheck too

From fabrig/qa via agents/loop, 2026-11-01 ~18:02Z: `v0.1.0-ladder/finding-5-2`'s precheck went
red only on the default suite's 120 s global timeout: 23,338 passed, 7 SIGTERMed, 938 never ran,
nothing asserted. The builder load was 14.4 on hetzner8 at the time. The queue's gate calls that
green (`docs/design/landing.md` 2, "Starvation stays green in the gate";
`skein/docs/foundation/testing-strategy.md` 8.1 in fabrig: starved is a warning, never red). But
`fab precheck` (`fab/precheck.py`) runs its steps through `gate.run_steps`, which checks exit
codes only, so a run's own check refuses what the queue would land, and the run asks a question.
finding-5 holds rung GitHub B1.

Build (`docs/design/landing.md` 2, "The selection and the steps are shared", now saying so):
- `fab precheck` runs its `default` and `fuzzy` test steps through `fab.queue_cpu.run_steps`
  (the queue's collector, its reconciliation and derived `gate-junit.xml`). Its other steps keep
  `gate.run_steps`.
- A step that is red only by starvation is green. Its receipt gains the starved count. The
  receipt's `outcome` stays `green` or `red` as the queue would judge it, so receipt reuse
  (landing.md 3) is unchanged.
- The precheck log names the starved tests, as the queue's detail log does.
- Tests: a fake nextest run with a global-timeout cancellation and no failure is green with
  starved > 0, and one with an assertion failure stays red. Use fixtures in the style of
  `fab/tests/test_queue_cpu.py`.

The user's rule: dogfood. Built by fab's loop (landed through `bin/fab land`); the plan's landing
is `queue` (the cut is started with `--set 'landing="queue"'`). One direct part, one task. The
fix reaches the builders when their installs follow main at the next run start (tick.md 3).
