+++
id = "after-landing-runner"
part = "after-landing"
kind = "migration"
needs = ["after-landing-verdicts", "nextest"]
files = ["fab/after_landing.py", "fab/tests/test_after_landing.py"]
effort = "high"
minutes = 30
+++
# fab after-landing: the loop, its records and its state

Fill `AfterLanding` and `main` in `fab/after_landing.py` as their
docstrings say. Design: `docs/design/fab.md`, section 11. It replaces the
agents repository's `tools/after-landing/after-landing` (read
`docs/design/after-landing.md` at 7a7df4f, sections 1-4, only if a detail is unclear);
what that tool does beyond these docstrings (posts, bisection, guardians,
replay, coverage posts) is deliberately left out.

## Acceptance

- `fab/tests/test_after_landing.py` gains tests under a temporary HOME,
  FAB_HOME and FAB_SLOTS, the slot a clone from `support.git_pair` with a
  small `.config/nextest.toml` committed, claimed with
  `fab.slots.claim(n, "after-landing", "after-landing")`. `fab.tiers.load`
  and `fab.tiers.run_pair` are patched: the fake writes a JUnit file beside
  the overlay passed in `--config-file` (`<name>.toml` gives `<name>.xml`),
  chosen per profile and per `-E` filter, and returns the code. It covers:
  - a slot missing, unclaimed or claimed by another run refused;
  - a green run: cursor and last moved, history saved, one `run` record
    with the suspects' branches since the previous cursor, the target swept
    (a stale `target/debug/incremental` gone);
  - a new red (passed at the cursor, fails twice now): a `test` record with
    good, branches and commits; the run red; a second tip with it still red
    gives standing, then a pass gives recovered;
  - a flake (fails, passes alone): recorded, run green;
  - a faulted pair (exit 2; then a JUnit missing; then a rerun selecting
    two cases): run partial, cursor kept, the faulted pair's history
    unchanged, and the next cycle at the same tip doing nothing;
  - cycle with nothing new; run stopping at the stop file, and an exception
    in a cycle giving an `error` record;
  - main: `log --since`, and `once` on an unclaimed slot exiting 1.
- `bin/fab test` passes; `test_after_landing.py` takes under two seconds.

## Options, settled up front

- `fab.tiers` may still be a skeleton when you start: import it by module
  (`from fab import tiers`) and patch it in tests.
- The run's start for the sweep is `time.time_ns()` taken before the
  checkout, as the queue's attempt takes it.
- Records are written with `fab.log.append(..., path=<FAB_HOME>/after-landing.jsonl)`;
  the state through `fab.run._write`.
