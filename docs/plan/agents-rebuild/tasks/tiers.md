+++
id = "tiers"
part = "after-landing"
kind = "migration"
needs = []
files = ["fab/tiers.py", "fab/tests/test_tiers.py"]
effort = "high"
minutes = 30
+++
# fab tiers: fabrig's slow tier runner, ported

Fill the bodies of `fab/tiers.py` as their docstrings say. Design:
`docs/design/fab.md`, section 11. The source is fabrig's `tools/tiers/run`
(on the builder at `~/src/fabrig/main/tools/tiers/run`; its `design.md`
sections 1-4 and 6 only if a detail is unclear). Leave out what the
docstrings leave out: the `--cpu` mode and its wrapper and budgets, and the
80 GB disk wait (heavy waits for disk itself).

## Acceptance

- `fab/tests/test_tiers.py`, under a temporary directory standing for the
  checkout (a small `.config/nextest.toml` with profiles `default`,
  `qa-skein`, `browser-jig` and `process-temper`, and a package map written
  in the test) and `fab.tests.support.FakeRunner`, covers:
  - load: the pairs and their split; `.config/tiers/packages.toml` winning
    over `tools/tiers/packages.toml`; each refusal of the docstring once
    (an unsorted package list, a binaries table missing a pair, a bad env
    name, two records sharing a bin);
  - pair: a known pair, and an unknown one naming the configured profiles;
  - bundle for browser-jig, qa-temper and qa-skein (None);
  - steps for browser-jig with a binary with env: the order, the `env`
    prefix with absolute paths, the bundle command's arguments, extra args
    last; steps for qa-skein with no target; a missing target refused;
  - run_pair with the fake: the nextest code returned (0 and 100); a failed
    prerequisite gives REFUSED and no nextest call; the log holds each
    step's command line;
  - listed on a small JSON listing with a filtered-out test; verify's
    missed and added sets;
  - main: `run` printing the log path and returning the code (patch
    run_pair), `verify` exit 0 and 1, an unknown pair exit 2.
- `bin/fab test` passes; `test_tiers.py` takes under a second.

## Options, settled up front

- Steps reuse `fab.gate.Step` and `fab.gate.run_steps`; their environment
  rides in the argv through `env`, so the fake runner sees it.
- `steps` builds the paths from target as given; `target_directory`
  resolves it.
