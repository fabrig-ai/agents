# after-landing status

2026-11-01. Contract: `docs/design/after-landing.md`. Split from `docs/design/fab.status.md`.

## Present

- **Reds reach their owners** (11-01; the user, after the night of 10-31,
  when every after-landing red and a hand-pushed rejection were handled by
  sessions noticing them by chance). Built and wired into the tick:
  - the records: the after-landing `run` carries `reds` and `commits`,
    `test` records their `key`, an unattributed red names the run's
    suspects' branches; the imports give `tiers.red` (new and
    unattributed, with key, state, error, rerun), `tiers.recovered` and
    `tiers.run`, each with `host`, deduplicated with the binary in the
    key; `fab after-landing run` wakes the tick after a new or unattributed
    red or a recovery (2, tick.md 6);
  - `fab/tier_reds.py` and `fab/roles/foreman-red.md`: the reds' one-pass
    fold and states (`covered` and unfixed among them), openings by tip and
    suspects, closings (the absent rule among them), owners, the evidence
    file, the red tasks `<draft>/red-<n>`, the red foreman's brief, start,
    remedy and settle (2, calls.md 2);
  - the tick: reds closed and opened each round (deferred after a failed
    load, never in a replay, against an empty owner map with no plan
    loaded), red foremen started and settled through the
    `examine-fix`/`remedy-fix` pair and `fab/fix.py`'s shared steps (qa.md
    2, plan findings-repair, retired 11-01), `<draft>/red-<n>` tasks run
    from `origin/main` in both landing modes, sorted with the repairs and
    readied to the queue, `RED_RUNS`, answer calls listing them in both
    modes (`RED_RUNS` is `fab.fix.RUNS`); the specless refusal foreman, for integration.md 3's repairs too; a fabrig
    plan's retire waiting for its verdict; `red.settled` and `red.closed`
    waking the tick again; the lost-event note counting after-landing
    records as one entry (2, calls.md 2, tick.md 5, tick.md 6, tick.md 7, integration.md 3);
  - hand-pushed queue records imported as `queue.*` with `gate` (landing.md 3), the
    page's `## Open signals` with its `queue:`, `red-` and `fault:` kinds,
    its first line, `fab page clear` and its wake (channel.md 2), and the landing
    report's red figures and signal line (reports.md 2); the queue's retire fix and
    `rejected`'s `tests` (landing.md 2, their own entry below).
  Tests use fake runners, records and logs. Deployed (11-01) to hetzner8
  (the queue and after-landing units) and hel8 (the tick follows main).
  What is left (bisection, a second repair round, the owner's spec, the
  pushing session told, reds standing from before `reds`, Fix mode's
  public-item gate) is in section 3.
- **After-landing CPU and starvation** (11-01): every pair and rerun uses
  the tested checkout's CPU collector, with one heavy-built wrapper per tip.
  Pair/test/run records and the page report CPU, wall, starvation and possible
  hangs. Optional `[after-landing]` limits have no default figures; per-pair
  budgets are diagnostic. Wall timeout passes as starved, unstarted tests
  stay unobserved, and removed profiles retire without a fault. Tests use
  fake services/JUnit/records; real slot-5 qa-smith and browser-jig checks
  and a scratch five-second total wall limit exercised the integration.
  The lead deploys the branch after landing; no live unit was changed here.

## Gaps and departures

- **After landing is live:** `fab-after-landing.service` on hetzner8,
  slot 7, since 11-01 (hetzner10 until it retired, 11-01); the tick imports its verdicts onto the user's page.
  The old `tools/after-landing` (hetzner7, slot 4) stopped with hetzner7,
  which no longer answers. Its reds reach their owners (Present, 11-01).
