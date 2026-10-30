# Gate status

2026-10-30. Owner: s/deploy. Baseline: `deploy/design` `dfc2798`.
Contract: `docs/design/gate.md`, sections 1–4.

## Present

- **The test runner matches section 2.** `tools/check.sh:59` discovers nested
  test_*.py files, validates focused paths and sorts/deduplicates them.
  `:47` gives each file a new Python interpreter, HOME, TMPDIR and no stdin;
  `:70` uses up to eight workers and `:78` presents results in discovery order
  with a summary and exit 1 for file failures. `tools/test_check.py:32`, `:40`,
  `:51`, `:61`, `:88`, `:96` and `:102` cover these behaviors.
- **The lander implements section 3.** `tools/land:14` rejects arguments,
  dirty trees, main and detached HEAD, then checks, fetches, rebases, checks
  again if HEAD moved, and pushes HEAD:main without force. A competing push
  is a failure, with no automatic retry (`:31`).
  `tools/test_fleet_sync.py:1085`, `:1090`, `:1095` and `:1106` cover a normal
  landing, dirty refusal, repeated checking after rebase and gate failure.
- **Cooperating callers share a host lock.** `tools/check.sh:7` and
  `tools/land:17` use the same default lock path, support AGENTS_GATE_LOCK,
  and print a wait message. The lander holds the lock across checks, rebase
  and push. `tools/test_check.py:113` verifies waiting; `:135` verifies that
  the fixture strips inherited gate variables.

## Gaps and departures

- **AGENTS_GATE_HELD is a bypass, not verified lock ownership.** The statement
  at `docs/design/gate.md:52` is false as an implementation guarantee:
  any nonempty value skips flock in `tools/check.sh:7` and `tools/land:17`.
  Neither command checks that the caller holds a lock, and an alternate
  AGENTS_GATE_LOCK also selects a different lock. Thus `gate.md:14` describes
  cooperating callers, not enforced host-wide exclusion. Fix: call it a
  trusted-caller nesting convention and prohibit setting it by policy until
  ownership is verified in code.
- **The landing entrypoint is not enforced by repository tooling.**
  `docs/design/gate.md:8` is a policy, not a restriction on every main update.
  `tools/land:37` is an ordinary git push, while `tools/check.sh` is a voluntary
  command; neither prevents another caller pushing main directly. No tracked
  hook or CI entrypoint enforces land-only updates in this tree. Remote
  branch-protection/ruleset settings were not inspected, so this audit does
  not assert their configuration. Fix: distinguish the required workflow
  from the deferred enforced entrypoint in section 5.
- **The one-minute deployment guarantee is overstated.**
  `docs/design/gate.md:11` inherits the hold/pin, lock, backoff, network,
  validation and installation qualifications from `docs/design/fleet.status.md`.
  `fleet/units/fleet-sync.timer:6` sets a polling schedule, not a completion
  deadline. Fix: say that healthy, unheld/unpinned hosts poll minutely.
- **Isolation relies on fixtures, not a sandbox.** The blanket “never touch
  the real host” / “fakes every external command” claim at
  `docs/design/gate.md:16` exceeds `tools/check.sh:52`: the rest of the
  environment and repository cwd are inherited, and no filesystem, network or
  service confinement is applied. Tests intentionally run real local git and
  process commands in disposable fixtures (`tools/test_fleet_sync.py:143`,
  `:153`, `tools/test_check.py:127`). Fix: describe isolated HOME/TMPDIR and
  fixture-faked services as the test contract, rather than an enforced sandbox
  or replacement of every external executable.
- **Per-file timing already exists, but is not stored with a landing.** The
  Later item at `docs/design/gate.md:61` is partly present: `tools/check.sh:56`
  returns elapsed time and `:80` prints it per file. `tools/land:31` runs the
  check without persisting a timing artifact. Fix: retain only timing storage
  with landing evidence as deferred work.

## Verification

The full `bash tools/check.sh` passed: 26 files, 0 failures, 467.791 seconds
with four workers. HOME, TMPDIR and AGENTS_GATE_LOCK were inside the audit
clone. Gate tests use fixture locks and strip inherited gate variables
(`tools/test_check.py:26`). This documentation change requires no machine action
and was not landed.
