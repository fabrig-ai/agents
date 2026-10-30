# After-landing status

2026-10-30. Owner: s/dynamic-memory.
Contract: `docs/design/after-landing.md`, sections 1–9.

## Present

- **Polling avoids unchanged fetches and reuses SSH connections.** Remote main
  is checked with `ls-remote`; all tool-owned git network calls use a private
  state-directory control socket, with no state-file format change (section 2).

- **The serial loop and bisection exist.** `tools/after-landing/after-landing`
  implements polling, coalescing, confirmation, verdicts, durable replay,
  routing, records-before-posts, trim and bounded first-parent bisection.
  `tools/after-landing/test_after_landing.py` exercises these with temporary
  HOME, local git origins and fake tiers, heavy, registry, records and post.
- **The declared service uses hetzner7 slot 4.** The evidence is
  `fleet/units/after-landing.service` (`--slot .../slots/4 --host hetzner7`),
  `fleet/units/roles.toml` and `fleet/hosts.toml` (`hosts.hetzner7`). The command's
  standalone default is slot 9 (`arguments`), not the service's slot. These are
  checked-in deployment declarations; this task did not inspect live service
  state, claims or activation.

## Gaps, departures and limits

- **Version 2 starts only with a first bisection.** `initial` writes version 1;
  `Runner.__init__` accepts 1 and 2 and fills absent optional fields in memory.
  `Runner.finish` sets version 2 when it saves a nonempty bisection phase;
  finishing that phase does not downgrade it. See
  `test_interval_uses_identity_good_older_than_cursor`,
  `test_single_commit_interval_has_no_bisection` and
  `test_existing_state_loads_without_migration` in the test file above.
- **Exact filters support a conservative identity alphabet.** Section 2's
  exact selection is implemented by `exact_filter` with unquoted matchers;
  only ASCII letters, digits, underscore, colon, dot and hyphen are accepted.
  Other identities fault rather than being escaped. See
  `test_exact_filter_refuses_unsafe_identities` and
  `test_unsafe_identity_faults_without_confirmation`. General filter escaping
  remains unimplemented.
- **Polling observes tips, not every publication.** Section 1's expectation
  that batches last several minutes is a cadence assumption. `Runner.poll`
  fetches and reads only the current `origin/main`; an intermediate published
  tip between polls has no separate queue entry. Its commits remain suspects
  of the observed descendant. `test_fifo_coalescing_and_hourly_counts` checks
  observed-tip queuing/coalescing, not lossless publication discovery.
- **Interrupted trim is not repeated.** `Runner.trim` persists its launch intent
  before invoking trim. A restart after that intent, without a saved outcome,
  records unknown completion and a trim fault, then permits later work. See
  `test_interrupted_trim_is_not_repeated_or_blocking`. Thus section 7's trim
  policy is an attempt per saved verdict/phase, not guaranteed completion.
- **Fault-episode recovery also depends on routing.** Section 5 describes an
  episode ending at the next run without faulted pairs. `Runner.finish` clears
  `fault_episode` only when both the faulted-pair list and routing error are
  empty; `Runner.fault` suppresses further notices within that episode.
  Unresolved routing remains in the outbox independently of test history;
  see `test_unresolved_new_red_is_retried_after_restart`.
- **Heavy tokens are learned after launch.** Section 9 describes saving an
  invocation with its heavy token before launch. `Runner.launch` saves the
  invocation descriptor and incremented count before starting the guardian;
  `Runner.await_invocation` then saves tokens parsed from its output. An
  interrupted guardian with no provable completion retains the slot rather
  than treating a missing token as idle. See
  `test_interrupted_unknown_supervisor_never_switches_slot` and
  `test_restart_unknown_heavy_drains_then_redoes_whole_probe`.
- **Future consumers and tier expansion remain deferred.** Section 8's queue
  holds, status-page consumption, extra slots and additional tiers are not
  supplied by this tool. `tiers.toml` enrolls only section 3's nine profiles;
  `Runner.prepare` reads that explicit list rather than discovering profiles.

## Verification

End-to-end cases run in the periodic tier (`tools/after-landing/test_after_landing_periodic.py`); the gate core keeps inexpensive contract coverage.

The evidence above is source and offline fixture coverage, not a live fleet
acceptance run. The SSH polling repair passed all 26 core tests using temporary
HOME and in-process fake services; periodic tests were not run. Activation needs
the updated script deployed and the service restarted; no state migration is
needed.
